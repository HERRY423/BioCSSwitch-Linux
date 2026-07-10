"""Privacy-first, local research-interest learning for BioCSSwitch.

This module deliberately sits below the MCP and desktop layers.  It has no
network code and it never accepts or stores raw prompts, paper titles, notes,
or model responses.  Callers submit small, structured events; the durable
state contains only decayed aggregates.

Privacy defaults:

* learning is opt-in (``consent=False`` blocks every write);
* topic and item identifiers are HMAC pseudonyms by default;
* work timing is reduced to six-hour weekday/weekend buckets;
* no event history is retained;
* files are written atomically with best-effort 0700/0600 permissions and
  symlink checks.

The HMAC key is stored separately from the JSON profile.  This is not a
replacement for full-disk encryption, but it prevents an accidentally shared
profile/export from disclosing a user's research topics.  In HMAC mode callers
provide a local topic catalog when human-readable interests or watch queries
are needed; candidate matching itself works by HMACing candidate topics.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple


PROFILE_SCHEMA = "biocsswitch/research-interest/1"
DEFAULT_HALF_LIFE_DAYS = 90.0
DEFAULT_SCHEDULE_HALF_LIFE_DAYS = 60.0
DEFAULT_MAX_FEATURES = 2048
DEFAULT_MAX_SEEN_ITEMS = 4096

_TASK_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class ConsentRequiredError(PermissionError):
    """Raised when a caller attempts learning without explicit consent."""


class ProfileCorruptError(ValueError):
    """Raised rather than silently overwriting an invalid local profile."""


class EventKind(str, Enum):
    PAPER_SAVED = "paper_saved"
    ENTITY_QUERIED = "entity_queried"
    SUGGESTION_ACCEPTED = "suggestion_accepted"
    SUGGESTION_REJECTED = "suggestion_rejected"
    WORKFLOW_OBSERVED = "workflow_observed"
    RECOMMENDATION_SHOWN = "recommendation_shown"


EVENT_WEIGHTS: Mapping[EventKind, float] = {
    EventKind.PAPER_SAVED: 3.0,
    EventKind.ENTITY_QUERIED: 1.0,
    EventKind.SUGGESTION_ACCEPTED: 1.5,
    # A rejection is weak negative evidence: it must not erase repeated
    # positive behaviour, and may mean "not now" rather than "not relevant".
    EventKind.SUGGESTION_REJECTED: -0.75,
    EventKind.WORKFLOW_OBSERVED: 0.0,
    EventKind.RECOMMENDATION_SHOWN: 0.0,
}


@dataclass(frozen=True)
class PrivacySettings:
    """Learning/storage policy chosen by the desktop integration."""

    storage_mode: str = "hmac"
    learn_schedule: bool = True
    time_bucket_hours: int = 6
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS
    schedule_half_life_days: float = DEFAULT_SCHEDULE_HALF_LIFE_DAYS
    max_features: int = DEFAULT_MAX_FEATURES
    max_seen_items: int = DEFAULT_MAX_SEEN_ITEMS

    def __post_init__(self) -> None:
        if self.storage_mode not in {"hmac", "plain"}:
            raise ValueError("storage_mode must be 'hmac' or 'plain'")
        if self.time_bucket_hours not in {4, 6, 8, 12, 24}:
            raise ValueError("time_bucket_hours must be one of 4, 6, 8, 12, 24")
        if self.half_life_days <= 0 or self.schedule_half_life_days <= 0:
            raise ValueError("half-life values must be positive")
        if self.max_features < 16 or self.max_seen_items < 16:
            raise ValueError("feature and seen-item limits must be at least 16")


@dataclass(frozen=True)
class ResearchEvent:
    """A data-minimized behavioural signal.

    ``topics`` are normalized biomedical concepts (gene, disease, pathway,
    intervention), never free-text queries. ``item_id`` is a stable public
    identifier such as ``PMID:123`` or ``NCT01234567`` and is HMACed before it
    reaches disk.  Exact timestamps are reduced to a day plus coarse schedule
    bucket in the aggregate profile.
    """

    kind: EventKind | str
    topics: Sequence[str] = field(default_factory=tuple)
    task_type: str = ""
    item_id: str = ""
    occurred_at: Optional[datetime] = None

    def validated(self) -> "ResearchEvent":
        try:
            kind = self.kind if isinstance(self.kind, EventKind) else EventKind(str(self.kind))
        except ValueError as exc:
            raise ValueError(f"unknown research event kind: {self.kind!r}") from exc

        topics = tuple(_normalize_topics(self.topics))
        weighted = EVENT_WEIGHTS[kind] != 0.0
        if weighted and not topics:
            raise ValueError(f"{kind.value} requires at least one structured topic")
        if kind is EventKind.RECOMMENDATION_SHOWN and not _normalize_item_id(self.item_id):
            raise ValueError("recommendation_shown requires item_id")

        task = _normalize_task(self.task_type)
        item = _normalize_item_id(self.item_id)
        at = self.occurred_at
        if at is not None and not isinstance(at, datetime):
            raise TypeError("occurred_at must be a datetime or None")
        return ResearchEvent(kind=kind, topics=topics, task_type=task, item_id=item, occurred_at=at)


def default_profile_path(env: Optional[Mapping[str, str]] = None) -> Path:
    env = env or os.environ
    explicit = env.get("BIOCSSWITCH_INTEREST_PROFILE_PATH") or env.get(
        "CSSWITCH_INTEREST_PROFILE_PATH"
    )
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".csswitch" / "research_partner" / "profile.json"


def _normalize_topic(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = " ".join(text.strip().split()).casefold()
    if not text:
        return ""
    if len(text) > 96:
        raise ValueError("topic must be <= 96 characters; pass a normalized concept, not free text")
    if _CONTROL_RE.search(text):
        raise ValueError("topic contains control characters")
    return text


def _normalize_topics(values: Sequence[str] | None) -> List[str]:
    if isinstance(values, (str, bytes)):
        raise TypeError("topics must be a sequence of structured concepts, not a free-text string")
    out: List[str] = []
    for value in values or ():
        topic = _normalize_topic(value)
        if topic and topic not in out:
            out.append(topic)
        if len(out) > 32:
            raise ValueError("an event may contain at most 32 topics")
    return out


def _normalize_task(value: Any) -> str:
    task = str(value or "").strip().lower().replace("_", "-")
    if task and not _TASK_RE.fullmatch(task):
        raise ValueError("task_type must be a short slug such as 'lit-review'")
    return task


def _normalize_item_id(value: Any) -> str:
    item = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not item:
        return ""
    if len(item) > 160 or _CONTROL_RE.search(item):
        raise ValueError("item_id must be a stable identifier of at most 160 characters")
    return item.casefold()


def _local_datetime(value: Optional[datetime] = None) -> datetime:
    value = value or datetime.now().astimezone()
    if value.tzinfo is None:
        # Naive datetimes are explicitly treated as local wall-clock time.
        return value.astimezone()
    return value.astimezone()


def _day(value: datetime) -> int:
    return value.date().toordinal()


def _decay(weight: float, previous_day: int, current_day: int, half_life: float) -> float:
    elapsed = max(0, int(current_day) - int(previous_day))
    return float(weight) * math.pow(0.5, elapsed / half_life)


def _coarse_bucket(value: datetime, hours: int) -> str:
    day_kind = "weekend" if value.weekday() >= 5 else "weekday"
    start = (value.hour // hours) * hours
    return f"{day_kind}:{start:02d}-{min(24, start + hours):02d}"


def _empty_profile(settings: PrivacySettings) -> Dict[str, Any]:
    return {
        "schema": PROFILE_SCHEMA,
        "storage_mode": settings.storage_mode,
        "time_bucket_hours": settings.time_bucket_hours,
        "features": {},
        "schedule": {"global": {}, "buckets": {}},
        "seen_items": {},
        "total_events": 0,
    }


def _validate_profile(raw: Any, settings: PrivacySettings) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ProfileCorruptError("research-interest profile must be a JSON object")
    if raw.get("schema") != PROFILE_SCHEMA:
        raise ProfileCorruptError(f"unsupported research-interest schema: {raw.get('schema')!r}")
    if raw.get("storage_mode") != settings.storage_mode:
        raise ProfileCorruptError(
            "profile storage mode differs from requested mode; migrate or delete explicitly"
        )
    if raw.get("time_bucket_hours") != settings.time_bucket_hours:
        raise ProfileCorruptError(
            "profile schedule bucket differs from requested policy; migrate or delete explicitly"
        )
    for key in ("features", "schedule", "seen_items"):
        if not isinstance(raw.get(key), dict):
            raise ProfileCorruptError(f"profile field {key!r} must be an object")
    schedule = raw["schedule"]
    if not isinstance(schedule.get("global"), dict) or not isinstance(schedule.get("buckets"), dict):
        raise ProfileCorruptError("profile schedule is malformed")
    raw.setdefault("total_events", 0)
    return raw


class InterestModel:
    """In-memory online model.  It performs no I/O and no network access."""

    def __init__(self, profile: Dict[str, Any], key: bytes, settings: PrivacySettings):
        if len(key) < 32:
            raise ValueError("profile HMAC key must contain at least 32 bytes")
        self.settings = settings
        self._key = key
        self._profile = _validate_profile(profile, settings)

    @property
    def total_events(self) -> int:
        return int(self._profile.get("total_events") or 0)

    def _token(self, topic: str) -> str:
        normalized = _normalize_topic(topic)
        if not normalized:
            raise ValueError("topic cannot be empty")
        if self.settings.storage_mode == "plain":
            return normalized
        digest = hmac.new(self._key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest}"

    def _item_token(self, item_id: str) -> str:
        normalized = _normalize_item_id(item_id)
        if not normalized:
            raise ValueError("item_id cannot be empty")
        digest = hmac.new(
            self._key, ("item\0" + normalized).encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return f"hmac-sha256:{digest}"

    def update(self, event: ResearchEvent) -> None:
        event = event.validated()
        at = _local_datetime(event.occurred_at)
        day = _day(at)
        increment = EVENT_WEIGHTS[event.kind]  # type: ignore[index]

        if increment:
            features = self._profile["features"]
            for topic in event.topics:
                token = self._token(topic)
                previous = features.get(token) or {"weight": 0.0, "count": 0, "day": day}
                weight = _decay(
                    float(previous.get("weight") or 0.0),
                    int(previous.get("day") or day),
                    day,
                    self.settings.half_life_days,
                )
                features[token] = {
                    "weight": round(weight + increment, 8),
                    "count": int(previous.get("count") or 0) + 1,
                    "day": day,
                }

        if event.task_type and self.settings.learn_schedule:
            self._update_schedule(event.task_type, at)

        if event.item_id and event.kind in {
            EventKind.PAPER_SAVED,
            EventKind.RECOMMENDATION_SHOWN,
            EventKind.SUGGESTION_ACCEPTED,
            EventKind.SUGGESTION_REJECTED,
        }:
            self._profile["seen_items"][self._item_token(event.item_id)] = day

        self._profile["total_events"] = self.total_events + 1
        self._prune(day)

    def _update_schedule(self, task: str, at: datetime) -> None:
        day = _day(at)
        schedule = self._profile["schedule"]
        for table in (
            schedule["global"],
            schedule["buckets"].setdefault(
                _coarse_bucket(at, self.settings.time_bucket_hours), {}
            ),
        ):
            previous = table.get(task) or {"weight": 0.0, "count": 0, "day": day}
            weight = _decay(
                float(previous.get("weight") or 0.0),
                int(previous.get("day") or day),
                day,
                self.settings.schedule_half_life_days,
            )
            table[task] = {
                "weight": round(weight + 1.0, 8),
                "count": int(previous.get("count") or 0) + 1,
                "day": day,
            }

    def _prune(self, day: int) -> None:
        features = self._profile["features"]
        if len(features) > self.settings.max_features:
            scored = sorted(
                features,
                key=lambda token: abs(
                    _decay(
                        float(features[token].get("weight") or 0.0),
                        int(features[token].get("day") or day),
                        day,
                        self.settings.half_life_days,
                    )
                ),
                reverse=True,
            )
            keep = set(scored[: self.settings.max_features])
            for token in list(features):
                if token not in keep:
                    del features[token]

        seen = self._profile["seen_items"]
        if len(seen) > self.settings.max_seen_items:
            keep_seen = set(
                token
                for token, _value in sorted(
                    seen.items(), key=lambda pair: int(pair[1]), reverse=True
                )[: self.settings.max_seen_items]
            )
            for token in list(seen):
                if token not in keep_seen:
                    del seen[token]

    def topic_score(self, topic: str, at: Optional[datetime] = None) -> float:
        now = _local_datetime(at)
        row = self._profile["features"].get(self._token(topic))
        if not isinstance(row, dict):
            return 0.0
        return _decay(
            float(row.get("weight") or 0.0),
            int(row.get("day") or _day(now)),
            _day(now),
            self.settings.half_life_days,
        )

    def top_interests(
        self,
        catalog: Optional[Iterable[str]] = None,
        *,
        at: Optional[datetime] = None,
        limit: int = 10,
        include_nonpositive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return interpretable interests without leaking stored HMAC tokens.

        In default HMAC mode, ``catalog`` is required to recover labels.  It
        should come from an already-local source such as the KG entity list or
        the current project's saved concepts.  No reverse lookup or outbound
        request is performed.
        """

        now = _local_datetime(at)
        labels: Iterable[str]
        if self.settings.storage_mode == "plain":
            labels = catalog if catalog is not None else self._profile["features"].keys()
        elif catalog is None:
            return []
        else:
            labels = catalog

        rows: List[Dict[str, Any]] = []
        seen_labels = set()
        for label in labels:
            normalized = _normalize_topic(label)
            if not normalized or normalized in seen_labels:
                continue
            seen_labels.add(normalized)
            token = self._token(normalized)
            stored = self._profile["features"].get(token)
            if not isinstance(stored, dict):
                continue
            score = self.topic_score(normalized, now)
            if score <= 0 and not include_nonpositive:
                continue
            rows.append(
                {
                    "topic": normalized,
                    "score": round(score, 6),
                    "observations": int(stored.get("count") or 0),
                }
            )
        rows.sort(key=lambda row: (-float(row["score"]), row["topic"]))
        return rows[: max(0, min(int(limit), 100))]

    def predict_workflow(
        self, at: Optional[datetime] = None, *, limit: int = 3
    ) -> List[Dict[str, Any]]:
        now = _local_datetime(at)
        day = _day(now)
        schedule = self._profile["schedule"]
        bucket_name = _coarse_bucket(now, self.settings.time_bucket_hours)
        bucket = schedule["buckets"].get(bucket_name) or {}
        global_table = schedule["global"]
        tasks = set(global_table) | set(bucket)
        rows: List[Dict[str, Any]] = []
        for task in tasks:
            local_row = bucket.get(task) or {}
            global_row = global_table.get(task) or {}
            local_score = _decay(
                float(local_row.get("weight") or 0.0),
                int(local_row.get("day") or day),
                day,
                self.settings.schedule_half_life_days,
            )
            global_score = _decay(
                float(global_row.get("weight") or 0.0),
                int(global_row.get("day") or day),
                day,
                self.settings.schedule_half_life_days,
            )
            # Local routine dominates, while the global prior prevents empty or
            # noisy buckets from producing brittle predictions.
            score = 0.7 * local_score + 0.3 * global_score
            if score > 0:
                rows.append(
                    {
                        "task_type": task,
                        "score": round(score, 6),
                        "time_bucket": bucket_name,
                        "observations": int(local_row.get("count") or 0),
                    }
                )
        rows.sort(key=lambda row: (-float(row["score"]), row["task_type"]))
        return rows[: max(0, min(int(limit), 20))]

    def was_seen(
        self,
        item_id: str,
        *,
        at: Optional[datetime] = None,
        cooldown_days: int = 14,
    ) -> bool:
        if cooldown_days < 0:
            raise ValueError("cooldown_days cannot be negative")
        seen_day = self._profile["seen_items"].get(self._item_token(item_id))
        if seen_day is None:
            return False
        return _day(_local_datetime(at)) - int(seen_day) <= cooldown_days

    def inspect(
        self, catalog: Optional[Iterable[str]] = None, *, at: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Return a safe, user-facing summary; never returns HMAC tokens."""

        return {
            "schema": PROFILE_SCHEMA,
            "storage_mode": self.settings.storage_mode,
            "raw_events_retained": False,
            "learning_events": self.total_events,
            "feature_count": len(self._profile["features"]),
            "seen_item_count": len(self._profile["seen_items"]),
            "top_interests": self.top_interests(catalog, at=at),
            "workflow_prediction": self.predict_workflow(at),
            "catalog_required_for_labels": (
                self.settings.storage_mode == "hmac" and catalog is None
            ),
        }

    def to_profile(self) -> Dict[str, Any]:
        # JSON round-trip returns a detached, JSON-safe object.
        return json.loads(json.dumps(self._profile, sort_keys=True))


class LocalInterestStore:
    """Atomic local persistence wrapper around :class:`InterestModel`."""

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        consent: bool = False,
        settings: Optional[PrivacySettings] = None,
        lock_timeout_seconds: float = 2.0,
    ):
        self.path = Path(path).expanduser() if path is not None else default_profile_path()
        self.key_path = self.path.with_suffix(".key")
        self.lock_path = self.path.with_suffix(".lock")
        self.settings = settings or PrivacySettings()
        self._consent = bool(consent)
        self.lock_timeout_seconds = max(0.1, float(lock_timeout_seconds))

    @property
    def learning_enabled(self) -> bool:
        return self._consent

    def record(self, event: ResearchEvent) -> Dict[str, Any]:
        """Learn from one event and return a privacy-safe summary."""

        if not self._consent:
            raise ConsentRequiredError(
                "local research-interest learning is disabled; obtain explicit user consent"
            )
        event = event.validated()
        self._ensure_parent()
        with self._lock():
            key = self._load_or_create_key(create=True)
            model = InterestModel(self._load_profile(create=True), key, self.settings)
            model.update(event)
            self._atomic_json_write(model.to_profile())
        return {
            "ok": True,
            "learning_enabled": True,
            "event": str(event.kind.value if isinstance(event.kind, EventKind) else event.kind),
            "total_events": model.total_events,
            "raw_event_retained": False,
        }

    def model(self) -> InterestModel:
        """Load the current model.  Reading never creates a profile or key."""

        if not self.path.exists():
            raise FileNotFoundError(str(self.path))
        self._assert_safe_existing(self.path)
        self._assert_safe_existing(self.key_path)
        key = self._load_or_create_key(create=False)
        return InterestModel(self._load_profile(create=False), key, self.settings)

    def inspect(
        self, catalog: Optional[Iterable[str]] = None, *, at: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Inspect local learning state even when learning is currently off."""

        if not self.path.exists():
            return {
                "schema": PROFILE_SCHEMA,
                "learning_enabled": self._consent,
                "profile_exists": False,
                "raw_events_retained": False,
            }
        result = self.model().inspect(catalog, at=at)
        result.update({"learning_enabled": self._consent, "profile_exists": True})
        return result

    def opt_out(self, *, delete_data: bool = False) -> Dict[str, Any]:
        """Disable writes for this instance, optionally erasing local state.

        Desktop integrations should persist the opt-out bit in their existing
        config.  The library remains fail-closed on every new instance because
        ``consent`` defaults to ``False``.
        """

        self._consent = False
        deleted = self.delete_local_data(confirm=True) if delete_data else {"deleted": False}
        return {
            "ok": True,
            "learning_enabled": False,
            "data_deleted": bool(deleted.get("deleted")),
        }

    def delete_local_data(self, *, confirm: bool = False) -> Dict[str, Any]:
        """Delete the aggregate profile and HMAC key after explicit confirmation."""

        if not confirm:
            raise ConsentRequiredError("delete_local_data requires confirm=True")
        parent = self.path.parent
        if not parent.exists():
            return {"ok": True, "deleted": False}
        self._ensure_parent()
        with self._lock():
            deleted = False
            for target in (self.path, self.key_path):
                if target.exists() or target.is_symlink():
                    self._assert_safe_existing(target)
                    target.unlink()
                    deleted = True
        return {"ok": True, "deleted": deleted}

    def _load_profile(self, *, create: bool) -> Dict[str, Any]:
        if not self.path.exists():
            if create:
                return _empty_profile(self.settings)
            raise FileNotFoundError(str(self.path))
        self._assert_safe_existing(self.path)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProfileCorruptError(f"cannot read research-interest profile: {exc}") from exc
        return _validate_profile(raw, self.settings)

    def _load_or_create_key(self, *, create: bool) -> bytes:
        if self.key_path.exists():
            self._assert_safe_existing(self.key_path)
            try:
                raw = bytes.fromhex(self.key_path.read_text(encoding="ascii").strip())
            except (OSError, ValueError) as exc:
                raise ProfileCorruptError("invalid research-interest HMAC key") from exc
            if len(raw) != 32:
                raise ProfileCorruptError("research-interest HMAC key must be 32 bytes")
            _chmod_private(self.key_path, 0o600)
            return raw
        if not create:
            raise FileNotFoundError(str(self.key_path))
        key = secrets.token_bytes(32)
        _atomic_bytes_write(self.key_path, key.hex().encode("ascii"), 0o600)
        return key

    def _ensure_parent(self) -> None:
        parent = self.path.parent
        if parent.exists() and parent.is_symlink():
            raise OSError(f"refusing symlinked research-interest directory: {parent}")
        parent.mkdir(parents=True, exist_ok=True)
        if parent.is_symlink() or not parent.is_dir():
            raise OSError(f"unsafe research-interest directory: {parent}")
        _chmod_private(parent, 0o700)

    def _assert_safe_existing(self, target: Path) -> None:
        if target.is_symlink():
            raise OSError(f"refusing symlinked research-interest file: {target}")
        if not target.is_file():
            raise OSError(f"research-interest path is not a regular file: {target}")

    @contextmanager
    def _lock(self) -> Iterator[None]:
        started = time.monotonic()
        stale_after = max(30.0, self.lock_timeout_seconds * 4)
        fd: Optional[int] = None
        while fd is None:
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                fd = os.open(self.lock_path, flags, 0o600)
                os.write(fd, f"{os.getpid()} {time.time():.6f}".encode("ascii"))
                os.close(fd)
                fd = -1
            except FileExistsError:
                if self.lock_path.is_symlink():
                    raise OSError(f"refusing symlinked lock: {self.lock_path}")
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > stale_after:
                    try:
                        self.lock_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() - started >= self.lock_timeout_seconds:
                    raise TimeoutError("timed out waiting for research-interest profile lock")
                time.sleep(0.02)
        try:
            yield
        finally:
            try:
                if self.lock_path.is_symlink():
                    raise OSError(f"lock path changed into a symlink: {self.lock_path}")
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    def _atomic_json_write(self, value: Mapping[str, Any]) -> None:
        payload = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        _atomic_bytes_write(self.path, payload, 0o600)


def _chmod_private(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        # ACL-oriented platforms may not implement POSIX bits.  The desktop
        # layer should additionally apply its native user-only ACL policy.
        pass


def _atomic_bytes_write(path: Path, payload: bytes, mode: int) -> None:
    if path.is_symlink():
        raise OSError(f"refusing symlinked destination: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(6)}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(temp, flags, mode)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _chmod_private(temp, mode)
        if path.is_symlink():
            raise OSError(f"destination became a symlink: {path}")
        os.replace(temp, path)
        _chmod_private(path, mode)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def event_from_mapping(raw: Mapping[str, Any]) -> ResearchEvent:
    """Parse the JSON-friendly event schema used by a future MCP server."""

    if not isinstance(raw, Mapping):
        raise TypeError("event must be an object")
    allowed = {"kind", "topics", "task_type", "item_id", "occurred_at"}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(
            "event contains unsupported fields (raw text/metadata are intentionally forbidden): "
            + ", ".join(sorted(map(str, unknown)))
        )
    occurred = raw.get("occurred_at")
    if isinstance(occurred, str):
        occurred = datetime.fromisoformat(occurred.replace("Z", "+00:00"))
    return ResearchEvent(
        kind=str(raw.get("kind") or ""),
        topics=raw.get("topics") or (),
        task_type=str(raw.get("task_type") or ""),
        item_id=str(raw.get("item_id") or ""),
        occurred_at=occurred,
    ).validated()


def record_research_event(
    event: Mapping[str, Any],
    *,
    profile_path: str | os.PathLike[str] | None = None,
    consent: bool = False,
    settings: Optional[PrivacySettings] = None,
) -> Dict[str, Any]:
    """JSON-friendly MCP integration function; fail-closed unless consented."""

    store = LocalInterestStore(profile_path, consent=consent, settings=settings)
    return store.record(event_from_mapping(event))


def inspect_research_profile(
    *,
    profile_path: str | os.PathLike[str] | None = None,
    topic_catalog: Optional[Iterable[str]] = None,
    settings: Optional[PrivacySettings] = None,
) -> Dict[str, Any]:
    """JSON-friendly, read-only MCP integration function."""

    return LocalInterestStore(profile_path, consent=False, settings=settings).inspect(topic_catalog)


def delete_research_profile(
    *,
    profile_path: str | os.PathLike[str] | None = None,
    confirm: bool = False,
    settings: Optional[PrivacySettings] = None,
) -> Dict[str, Any]:
    """JSON-friendly local-data deletion function."""

    return LocalInterestStore(profile_path, consent=False, settings=settings).delete_local_data(
        confirm=confirm
    )
