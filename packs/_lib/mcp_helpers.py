"""Shared helpers for bio pack MCP servers.

This module is intentionally stdlib-only and thin over `_lib.server` / `_lib.http`.
It gives new pack code one place for tool registration, safe HTTP error shapes,
and minimal JSON-object validation without pulling in jsonschema.
"""

from __future__ import annotations

import json
import urllib.error
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from . import http
from .server import MCPServer

F = TypeVar("F", bound=Callable[..., Any])


def mcp_tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    *,
    server: MCPServer | None = None,
) -> Callable[[F], F] | Callable[[MCPServer], Callable[[F], F]]:
    """Return a standard MCP tool decorator.

    Use `@mcp_tool(..., server=server)` for new code. When `server` is omitted,
    the function returns a binder so modules can write
    `tool = mcp_tool(...); @tool(server)`.
    """
    if server is not None:
        return server.tool(name, description, input_schema)

    def bind(target: MCPServer) -> Callable[[F], F]:
        return target.tool(name, description, input_schema)

    return bind


def validate_json_object(value: Any, schema: Mapping[str, Any]) -> list[str]:
    """Validate a small JSON object subset used by MCP input schemas.

    This is not a full JSON Schema implementation; it covers required fields,
    basic scalar types, enum, and numeric min/max so pack servers can fail early
    with consistent messages while keeping zero runtime dependencies.
    """
    errors: list[str] = []
    if schema.get("type") == "object" and not isinstance(value, dict):
        return ["input must be an object"]
    if not isinstance(value, dict):
        return errors

    props = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if key not in value or value.get(key) is None:
            errors.append(f"missing required field: {key}")

    for key, spec in props.items():
        if key not in value or value[key] is None:
            continue
        expected = spec.get("type")
        item = value[key]
        if not _matches_json_type(item, expected):
            errors.append(f"{key} must be {expected}")
            continue
        if "enum" in spec and item not in spec["enum"]:
            errors.append(f"{key} must be one of {spec['enum']}")
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            if "minimum" in spec and item < spec["minimum"]:
                errors.append(f"{key} must be >= {spec['minimum']}")
            if "maximum" in spec and item > spec["maximum"]:
                errors.append(f"{key} must be <= {spec['maximum']}")
    return errors


def _matches_json_type(value: Any, expected: Any) -> bool:
    if not expected:
        return True
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    type_map = {
        "string": str,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    py_type = type_map.get(expected)
    return py_type is None or isinstance(value, py_type)


def safe_http_get(
    url: str,
    timeout: int = 10,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """GET JSON with retries and a standardized non-throwing result."""
    try:
        return {
            "ok": True,
            "data": http.get_json(url, params=params, headers=headers, timeout=timeout),
            "status": 200,
        }
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "error_kind": "http", "status": e.code, "error": detail or str(e)}
    except json.JSONDecodeError as e:
        return {"ok": False, "error_kind": "json", "status": None, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "error_kind": e.__class__.__name__,
            "status": None,
            "error": str(e),
        }
