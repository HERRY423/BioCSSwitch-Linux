//! phase-1 路径验证 —— 让 pack 机制不再靠"惯例猜测"运行。
//!
//! # 背景
//! `packs.rs` 目前假定：
//!   - MCP 配置文件：`<sandbox data-dir>/mcp-servers.json`
//!   - Skill 目录：`<sandbox data-dir>/skills/<id>/`
//! 这两个都是 Claude Code 惯例；Claude Science 二进制侧尚未逆向确认。若真实位置不同，
//! 我们写的文件 Science 根本不会读。用户会以为 pack 生效了、实际什么工具都没挂进去。
//!
//! # 策略
//! 用**canary pack + subprocess detection** 做真实 smoke test：
//!   1. 生成一个 128-bit hex marker
//!   2. 把 `bio-mcp-smoke` server 写进沙箱 mcp-servers.json（脚本 `packs/_lib/smoke/smoke_mcp.py`）
//!   3. 让 smoke_mcp.py 的启动参数带上 `CSSWITCH_SMOKE_MARKER=<marker>`
//!   4. 让 canary_skill 也拷到 `<data-dir>/skills/bio-mcp-smoke-canary/`
//!   5. **等待用户手动重启沙箱**（我们不代做，防止打断正在进行的会话）
//!   6. 5s 后开始轮询 `~/.csswitch/smoke/latest.json`：
//!      - marker 匹配 → MCP 路径正确 ✓
//!      - 5 分钟内文件从没出现 → 路径可能不对 ✗
//!   7. Skill 需要**用户主动核对**：SKILL.md 的触发词是"CSSwitch canary skill verification please"，
//!      用户去 Science 里发一句，看 Claude 是否回 "canary-ok"。UI 提供一个"我看到 canary 回复了"按钮。
//!
//! # 为什么不完全自动
//! 完全自动的方式需要重启 Science / 调用 Science 内部 API，两者都受铁律约束。
//! 让用户点一下"我已重启沙箱"是最诚实的做法：如果用户不肯重启，我们就诚实回复"未验证"。

use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::config;

/// 验证结论。持久化到 `config.verification`。
#[derive(Serialize, Deserialize, Clone, Debug, Default, PartialEq)]
pub struct VerificationStatus {
    /// UNIX ms；从没跑过为 None。
    pub last_run_ms: Option<i64>,
    /// 三态：`unverified` | `mcp_path_ok` | `mcp_path_fail` | `mcp_path_pending`（重启等待中）
    #[serde(default)]
    pub mcp_verdict: String,
    /// Skill 三态：`unverified` | `skill_path_ok` | `skill_path_fail`（只能由用户手动确认）
    #[serde(default)]
    pub skill_verdict: String,
    /// 本次跑的 marker；重启后应能在 spawned marker 里看到相同值
    #[serde(default)]
    pub last_marker: String,
    /// 人话说明（回显给 UI）
    #[serde(default)]
    pub reason: Option<String>,
}

impl VerificationStatus {
    pub fn is_mcp_verified(&self) -> bool {
        self.mcp_verdict == "mcp_path_ok"
    }
    pub fn is_skill_verified(&self) -> bool {
        self.skill_verdict == "skill_path_ok"
    }
}

/// smoke marker 输出目录：`~/.csswitch/smoke/`。canary MCP 把 `latest.json` 写到这里。
pub fn smoke_dir() -> std::path::PathBuf {
    config::default_dir().join("smoke")
}

/// 生成一个 128-bit hex marker。
fn new_marker() -> String {
    use std::io::Read;
    let mut buf = [0u8; 16];
    if let Ok(mut f) = fs::File::open("/dev/urandom") {
        if f.read_exact(&mut buf).is_ok() {
            return buf.iter().map(|b| format!("{b:02x}")).collect();
        }
    }
    format!("{:032x}", config::now_ms() as u128)
}

/// **准备阶段**：把 canary MCP + canary Skill 写进沙箱；返回 marker 供后续 poll。
///
/// 幂等：多次调用会覆盖 marker + 重写 canary MCP entry；不改动其它 pack 的 MCP entries。
///
/// # 参数
///   - `asset_root`：`packs/` 所在根
///   - `sandbox_data_dir`：`<SANDBOX_HOME>/.claude-science/`
///   - `mcp_config_rel`：mcp-servers.json 的相对路径（从 packs 模块传入，保证一致）
///   - `skills_rel`：skills 目录的相对路径
pub fn prepare_smoke(
    asset_root: &Path,
    sandbox_data_dir: &Path,
    mcp_config_rel: &str,
    skills_rel: &str,
    python_exe: &str,
) -> Result<String, String> {
    let marker = new_marker();

    // 1) canary MCP 写进 mcp-servers.json
    let mcp_path = sandbox_data_dir.join(mcp_config_rel);
    let mut cfg = read_mcp(&mcp_path)?;
    let servers = cfg
        .get_mut("mcpServers")
        .and_then(|v| v.as_object_mut())
        .ok_or("mcp-servers.json schema 异常：mcpServers 不是 object")?;
    let script = asset_root
        .join("packs/_lib/smoke/smoke_mcp.py")
        .to_string_lossy()
        .to_string();
    let smoke_dir_env = smoke_dir().to_string_lossy().to_string();
    servers.insert(
        "bio-mcp-smoke".to_string(),
        serde_json::json!({
            "command": python_exe,
            "args": [script],
            "env": {
                "CSSWITCH_SMOKE_MARKER": marker,
                "CSSWITCH_SMOKE_DIR": smoke_dir_env,
            }
        }),
    );
    write_mcp(&mcp_path, &cfg).map_err(|e| format!("写 canary MCP 失败：{e}"))?;

    // 2) canary Skill 拷到 skills 目录
    let skill_src = asset_root.join("packs/_lib/smoke/canary_skill");
    let skill_dst = sandbox_data_dir
        .join(skills_rel)
        .join("bio-mcp-smoke-canary");
    if skill_dst.exists() {
        config::assert_not_symlink(&skill_dst).map_err(|e| e.to_string())?;
        fs::remove_dir_all(&skill_dst).map_err(|e| e.to_string())?;
    }
    copy_dir(&skill_src, &skill_dst).map_err(|e| format!("拷贝 canary Skill 失败：{e}"))?;

    // 3) 清掉旧 marker，避免残留读到旧值
    let d = smoke_dir();
    let _ = fs::create_dir_all(&d);
    let _ = fs::remove_file(d.join("latest.json"));

    Ok(marker)
}

/// **poll 阶段**：读 `~/.csswitch/smoke/latest.json`，看 marker 是否匹配。
/// 返回 `Some(true)` 匹配 / `Some(false)` 不匹配（存在但 marker 是旧的）/ `None` 未出现。
pub fn poll_smoke(expected_marker: &str) -> Option<bool> {
    let p = smoke_dir().join("latest.json");
    let data = fs::read(&p).ok()?;
    let v: serde_json::Value = serde_json::from_slice(&data).ok()?;
    let got = v.get("marker")?.as_str()?;
    Some(got == expected_marker)
}

/// 拆掉 canary（清理阶段）：从 mcp-servers.json 里移除 `bio-mcp-smoke`，从 skills 里删掉
/// canary skill 目录。**不影响用户 pack**。
pub fn cleanup_smoke(
    sandbox_data_dir: &Path,
    mcp_config_rel: &str,
    skills_rel: &str,
) -> io::Result<()> {
    let mcp_path = sandbox_data_dir.join(mcp_config_rel);
    if mcp_path.is_file() {
        let mut cfg = read_mcp(&mcp_path).map_err(io::Error::other)?;
        if let Some(obj) = cfg.get_mut("mcpServers").and_then(|v| v.as_object_mut()) {
            obj.remove("bio-mcp-smoke");
        }
        write_mcp(&mcp_path, &cfg)?;
    }
    let skill_dst = sandbox_data_dir
        .join(skills_rel)
        .join("bio-mcp-smoke-canary");
    if skill_dst.exists() {
        config::assert_not_symlink(&skill_dst)?;
        fs::remove_dir_all(&skill_dst)?;
    }
    Ok(())
}

// ---------- 与 packs.rs 共享的最小 I/O ----------

fn backup_corrupt_mcp(path: &Path, bytes: &[u8]) -> io::Result<PathBuf> {
    if let Some(parent) = path.parent() {
        config::assert_not_symlink(parent)?;
    }
    let name = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("mcp-servers.json");
    let backup = path.with_file_name(format!(
        "{name}.corrupt.{}.{}",
        std::process::id(),
        config::now_ms()
    ));
    config::write_bytes_atomic_0600(&backup, bytes)?;
    Ok(backup)
}

fn read_mcp(path: &Path) -> Result<serde_json::Value, String> {
    if !path.is_file() {
        return Ok(serde_json::json!({"mcpServers": {}}));
    }
    config::assert_not_symlink(path).map_err(|e| e.to_string())?;
    let bytes = fs::read(path).map_err(|e| e.to_string())?;
    let mut v: serde_json::Value = match serde_json::from_slice(&bytes) {
        Ok(v) => v,
        Err(e) => {
            let backup = backup_corrupt_mcp(path, &bytes)
                .map_err(|be| format!("mcp-servers.json 解析失败：{e}；坏文件备份失败：{be}"))?;
            return Err(format!(
                "mcp-servers.json 解析失败：{e}；已备份坏文件到 {}，为避免覆盖用户配置，本次未写入。",
                backup.display()
            ));
        }
    };
    if v.get("mcpServers").is_none() {
        if let Some(m) = v.as_object_mut() {
            m.insert("mcpServers".into(), serde_json::json!({}));
        }
    }
    Ok(v)
}

fn write_mcp(path: &Path, v: &serde_json::Value) -> io::Result<()> {
    let json = serde_json::to_vec_pretty(v)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    config::write_bytes_atomic_0600(path, &json)
}

fn copy_dir(src: &Path, dst: &Path) -> io::Result<()> {
    fs::create_dir_all(dst)?;
    for e in fs::read_dir(src)? {
        let e = e?;
        let ft = e.file_type()?;
        if ft.is_symlink() {
            continue;
        }
        let sp = e.path();
        let dp = dst.join(e.file_name());
        if ft.is_dir() {
            copy_dir(&sp, &dp)?;
        } else {
            fs::copy(&sp, &dp)?;
        }
    }
    Ok(())
}
