//! CSSwitch 菜单栏 app 后端（进程管家）。
//!
//! 职责：管理「翻译代理」与「沙箱 Science」两个子进程的生命周期；读写
//! `~/.csswitch/config.json`；把第三方 key 以【环境变量】注入代理子进程（绝不进 argv）；
//! 探活；把沙箱 URL 交系统浏览器打开。已验证的越权/翻译逻辑仍留在 Python/Node/shell
//! 里被当作子进程调用，以保住铁律护栏与已验证行为。
//!
//! 铁律相关：key 只在内存与 0600 的 config.json；回显前端只给掩码；沙箱端口/目录护栏
//! 由被调脚本负责（对 8765 与真实目录失败关闭）；退 app 默认停代理、保留沙箱。

mod config;
mod proc;

use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use serde::Deserialize;
use serde_json::json;
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, State};

const SCIENCE_BIN: &str = "/Applications/Claude Science.app/Contents/Resources/bin/claude-science";

#[derive(Default)]
struct AppState {
    proxy: Option<Child>,
    proxy_port: u16,
    secret: String,
    provider: String,
    sandbox: Option<Child>,
    sandbox_port: u16,
    sandbox_url: Option<String>,
}

// ---------- provider 元信息 ----------
fn key_env(provider: &str) -> &'static str {
    match provider {
        "qwen" => "DASHSCOPE_API_KEY",
        _ => "DEEPSEEK_API_KEY",
    }
}

fn upstream_host(provider: &str) -> &'static str {
    match provider {
        "qwen" => "dashscope.aliyuncs.com",
        _ => "api.deepseek.com",
    }
}

// ---------- 路径与日志 ----------
/// 定位 CSSwitch 仓库根（含 proxy/csswitch_proxy.py）。优先 CSSWITCH_REPO，
/// 否则从可执行文件与当前目录逐级上溯。找不到返回 None。
fn repo_root() -> Option<PathBuf> {
    let marker = Path::new("proxy/csswitch_proxy.py");
    // 显式指定优先：规范化后再判定，避免相对/软链歧义。
    if let Some(r) = std::env::var_os("CSSWITCH_REPO") {
        if let Ok(p) = std::fs::canonicalize(PathBuf::from(r)) {
            if p.join(marker).is_file() {
                return Some(p);
            }
        }
    }
    // 否则只从【可执行文件位置】上溯。刻意不看 current_dir：启动目录可被影响，
    // 若据此找到别处的 csswitch_proxy.py，会把带 key 的环境交给来路不明的脚本。
    if let Ok(exe) = std::env::current_exe() {
        let mut dir: Option<&Path> = exe.parent();
        while let Some(d) = dir {
            if d.join(marker).is_file() {
                return Some(d.to_path_buf());
            }
            dir = d.parent();
        }
    }
    None
}

fn log_path(name: &str) -> PathBuf {
    config::default_dir().join("logs").join(name)
}

/// 打开（truncate）一个子进程日志文件，父目录 0700、文件 0600（防同机其它用户读到 secret 尾巴）。
fn open_log(name: &str) -> std::io::Result<std::fs::File> {
    use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
    let p = log_path(name);
    if let Some(parent) = p.parent() {
        std::fs::create_dir_all(parent)?;
        let _ = std::fs::set_permissions(parent, std::fs::Permissions::from_mode(0o700));
    }
    let f = std::fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .open(&p)?;
    // 文件已存在时 mode() 不复位，显式再夹一次。
    let _ = std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o600));
    Ok(f)
}

/// 把字符串里的 secret 明文替换成 ****，用于任何要回显给前端的错误尾巴。
fn redact<'a>(s: &str, secret: &str) -> String {
    if secret.is_empty() {
        s.to_string()
    } else {
        s.replace(secret, "****")
    }
}

fn tail_file(path: &Path, max: usize) -> String {
    match std::fs::read(path) {
        Ok(b) => {
            let start = b.len().saturating_sub(max);
            String::from_utf8_lossy(&b[start..]).trim().to_string()
        }
        Err(_) => String::new(),
    }
}

fn kill_child(slot: &mut Option<Child>) {
    if let Some(mut c) = slot.take() {
        let _ = c.kill();
        let _ = c.wait();
    }
}

/// 取锁并从 poison 中恢复：某线程持锁时 panic 不应把整个 app 卡死。
fn lock(m: &Mutex<AppState>) -> std::sync::MutexGuard<'_, AppState> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

/// 用系统浏览器打开 URL（macOS `open`）。
fn open_in_browser(url: &str) -> Result<(), String> {
    Command::new("open")
        .arg(url)
        .status()
        .map_err(|e| format!("打开浏览器失败：{e}"))?;
    Ok(())
}

// ---------- 代理生命周期核心 ----------
/// 确保代理在跑且健康；返回 (端口, secret)。幂等：已健康则复用。
fn ensure_proxy(state: &State<'_, Mutex<AppState>>) -> Result<(u16, String), String> {
    let dir = config::default_dir();
    let cfg = config::load_from(&dir).map_err(|e| e.to_string())?;
    let provider = cfg.provider.clone();
    let key = cfg
        .key_for(&provider)
        .ok_or_else(|| format!("缺少 {provider} 的 API key，请先在面板填写并保存。"))?;
    let port = cfg.proxy_port;
    let root = repo_root()
        .ok_or("找不到 CSSwitch 仓库根（含 proxy/csswitch_proxy.py）。可设 CSSWITCH_REPO 环境变量。")?;
    let py = proc::which("python3").ok_or("缺少依赖 python3。")?;

    // 整个「检查 → 清残留 → 起进程 → 记账」在同一把锁内完成，避免并发双击时
    // 两路都判定「没健康代理」各起一个、后者覆盖前者的 Child 句柄导致前者被孤儿泄漏。
    let secret;
    {
        let mut st = lock(state);
        // 幂等：已在跑且健康且同端口则复用。
        if st.proxy.is_some()
            && st.proxy_port == port
            && proc::http_health(port, Some(&st.secret), 500)
        {
            return Ok((port, st.secret.clone()));
        }
        // 清残留（换端口/不健康）。
        kill_child(&mut st.proxy);

        let new_secret = proc::gen_secret().map_err(|e| format!("无法生成安全 secret：{e}"))?;
        let script = root.join("proxy/csswitch_proxy.py");
        let logf = open_log("proxy.log").map_err(|e| format!("建日志失败：{e}"))?;
        let logf2 = logf.try_clone().map_err(|e| e.to_string())?;
        let child = Command::new(&py)
            .arg(&script)
            .arg("--provider")
            .arg(&provider)
            .arg("--port")
            .arg(port.to_string())
            .arg("--auth-token")
            .arg(&new_secret)
            // key 经环境变量注入，绝不作为命令行参数（避免 ps 泄露）。
            .env(key_env(&provider), &key)
            .stdout(Stdio::from(logf))
            .stderr(Stdio::from(logf2))
            .spawn()
            .map_err(|e| format!("启动代理失败：{e}"))?;
        st.proxy = Some(child);
        st.proxy_port = port;
        st.secret = new_secret.clone();
        st.provider = provider;
        secret = new_secret;
    }

    // 探活最多 ~4s（锁外，不阻塞 status 等命令）。
    let mut ok = false;
    for _ in 0..40 {
        std::thread::sleep(Duration::from_millis(100));
        if proc::http_health(port, Some(&secret), 400) {
            ok = true;
            break;
        }
    }
    if !ok {
        let mut st = lock(state);
        // 只在仍是本次起的代理时才清（secret 匹配），避免误杀并发重启起来的新代理。
        if st.secret == secret {
            kill_child(&mut st.proxy);
        }
        let tail = redact(&tail_file(&log_path("proxy.log"), 500), &secret);
        return Err(format!(
            "代理起后探活超时（端口 {port} 可能被占用，或 key 无效）。\n{tail}"
        ));
    }
    Ok((port, secret))
}

fn stop_sandbox_inner(st: &mut AppState) {
    // 沙箱由脚本以 --detached 起 Science，本进程持有的是脚本 child（已退出）。
    // 真正停 Science 要调 stop 脚本（按 data-dir，绝不碰真实 8765）。
    if let Some(root) = repo_root() {
        let stop = root.join("scripts/stop-science-sandbox.sh");
        if stop.is_file() {
            let _ = Command::new("zsh") // stop 脚本是 #!/bin/zsh（用了 ${VAR:A} realpath）
                .arg(&stop)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
        }
    }
    kill_child(&mut st.sandbox);
    st.sandbox_url = None;
}

// ---------- Tauri commands ----------
#[tauri::command]
fn get_config() -> Result<serde_json::Value, String> {
    let dir = config::default_dir();
    let cfg = config::load_from(&dir).map_err(|e| e.to_string())?;
    let mut keys = serde_json::Map::new();
    for p in ["deepseek", "qwen"] {
        let masked = cfg.key_for(p).map(|k| config::mask(&k)).unwrap_or_default();
        keys.insert(p.to_string(), serde_json::Value::String(masked));
    }
    Ok(json!({
        "provider": cfg.provider,
        "proxy_port": cfg.proxy_port,
        "sandbox_port": cfg.sandbox_port,
        "keys": keys,
    }))
}

#[derive(Deserialize)]
struct UiSettings {
    provider: String,
    proxy_port: u16,
    sandbox_port: u16,
}

#[tauri::command]
fn set_config(cfg: UiSettings) -> Result<(), String> {
    // 铁律防御：代理/沙箱端口都不许用真实实例保留端口 8765。
    if cfg.proxy_port == 8765 || cfg.sandbox_port == 8765 {
        return Err("端口 8765 是真实 Science 实例保留端口，不能用。".into());
    }
    let dir = config::default_dir();
    config::update(&dir, move |c| {
        c.provider = cfg.provider;
        c.proxy_port = cfg.proxy_port;
        c.sandbox_port = cfg.sandbox_port;
    })
    .map(|_| ())
    .map_err(|e| e.to_string())
}

#[tauri::command]
fn save_provider_key(provider: String, key: String) -> Result<String, String> {
    let dir = config::default_dir();
    let key2 = key.clone();
    config::update(&dir, move |c| {
        c.providers.entry(provider).or_default().key = key2;
    })
    .map_err(|e| e.to_string())?;
    Ok(config::mask(&key))
}

#[tauri::command]
fn start_proxy(state: State<'_, Mutex<AppState>>) -> Result<serde_json::Value, String> {
    let (port, _secret) = ensure_proxy(&state)?;
    Ok(json!({ "port": port }))
}

#[tauri::command]
fn stop_all(state: State<'_, Mutex<AppState>>) -> Result<(), String> {
    let mut st = lock(&state);
    stop_sandbox_inner(&mut st);
    kill_child(&mut st.proxy);
    st.secret.clear();
    Ok(())
}

#[tauri::command]
fn one_click_login(state: State<'_, Mutex<AppState>>) -> Result<serde_json::Value, String> {
    // 1~3. 确保代理在跑且健康（内部已查 key、探活）。
    let (pport, secret) = ensure_proxy(&state)?;

    let dir = config::default_dir();
    let cfg = config::load_from(&dir).map_err(|e| e.to_string())?;
    let sport = cfg.sandbox_port;
    let root = repo_root().ok_or("找不到 CSSwitch 仓库根。")?;

    if proc::which("node").is_none() {
        return Err("缺少依赖 node（写虚拟登录需要）。".into());
    }
    let launch = root.join("scripts/launch-virtual-sandbox.sh");
    if !launch.is_file() {
        return Err("找不到 scripts/launch-virtual-sandbox.sh。".into());
    }

    // 4. 起沙箱：脚本内部写虚拟 OAuth 并以 --detached 起 Science，然后返回。
    let proxy_url = format!("http://127.0.0.1:{pport}/{secret}");
    let logf = open_log("sandbox.log").map_err(|e| format!("建日志失败：{e}"))?;
    let logf2 = logf.try_clone().map_err(|e| e.to_string())?;
    let status = Command::new("zsh") // launch 脚本是 #!/bin/zsh（用了 ${VAR:A} realpath）
        .arg(&launch)
        .arg("--port")
        .arg(sport.to_string())
        .arg("--proxy-url")
        .arg(&proxy_url)
        .stdout(Stdio::from(logf))
        .stderr(Stdio::from(logf2))
        .status()
        .map_err(|e| format!("起沙箱失败：{e}"))?;
    if !status.success() {
        let tail = redact(&tail_file(&log_path("sandbox.log"), 600), &secret);
        return Err(format!("起沙箱脚本失败。\n{tail}"));
    }

    // 5. 轮询沙箱 /health 直到就绪或超时（~8s）。
    let mut ok = false;
    for _ in 0..80 {
        std::thread::sleep(Duration::from_millis(100));
        if proc::http_health(sport, None, 400) {
            ok = true;
            break;
        }
    }
    if !ok {
        let tail = redact(&tail_file(&log_path("sandbox.log"), 600), &secret);
        return Err(format!("沙箱起后探活超时（端口 {sport}）。\n{tail}"));
    }

    // 6. 取 UI URL（登录态），交系统浏览器打开。
    let url = sandbox_url(&root, sport);
    {
        let mut st = lock(&state);
        st.sandbox_port = sport;
        st.sandbox_url = Some(url.clone());
    }
    let _ = open_in_browser(&url);
    Ok(json!({ "url": url }))
}

/// 取沙箱 UI 链接：`<bin> url --data-dir <home>/.claude-science`，HOME 指向沙箱 HOME。
/// 失败退回 http://127.0.0.1:<port>。
fn sandbox_url(root: &Path, port: u16) -> String {
    let home = root.join(".sandbox/home");
    let data_dir = home.join(".claude-science");
    if Path::new(SCIENCE_BIN).is_file() {
        if let Ok(out) = Command::new(SCIENCE_BIN)
            .arg("url")
            .arg("--data-dir")
            .arg(&data_dir)
            .env("HOME", &home)
            .output()
        {
            let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
            if s.starts_with("http") {
                return s;
            }
        }
    }
    format!("http://127.0.0.1:{port}")
}

#[tauri::command]
fn status(state: State<'_, Mutex<AppState>>) -> serde_json::Value {
    // 只在锁内取值，锁外做阻塞探活。
    let (pport, secret, sport, provider) = {
        let st = lock(&state);
        let cfg = config::load_from(&config::default_dir()).unwrap_or_default();
        let pport = if st.proxy_port != 0 { st.proxy_port } else { cfg.proxy_port };
        let sport = if st.sandbox_port != 0 { st.sandbox_port } else { cfg.sandbox_port };
        (pport, st.secret.clone(), sport, cfg.provider)
    };
    let proxy = if !secret.is_empty() && proc::http_health(pport, Some(&secret), 300) {
        "green"
    } else {
        "amber"
    };
    let sandbox = if proc::http_health(sport, None, 300) { "green" } else { "amber" };
    let upstream = if proc::tcp_reachable(upstream_host(&provider), 443, 500) {
        "green"
    } else {
        "amber"
    };
    json!({ "proxy": proxy, "sandbox": sandbox, "upstream": upstream })
}

#[tauri::command]
fn open_url(state: State<'_, Mutex<AppState>>) -> Result<(), String> {
    let url = { lock(&state).sandbox_url.clone() };
    let url = url.ok_or("还没有沙箱 URL，请先「一键越过登录」。")?;
    open_in_browser(&url)
}

#[tauri::command]
fn run_doctor() -> Result<String, String> {
    let root = repo_root().ok_or("找不到 CSSwitch 仓库根。")?;
    let cfg = config::load_from(&config::default_dir()).unwrap_or_default();
    let doctor = root.join("scripts/doctor.sh");
    let mut cmd = Command::new("bash");
    cmd.arg(&doctor)
        .env("CSSWITCH_PROVIDER", &cfg.provider)
        .env("CSSWITCH_PROXY_PORT", cfg.proxy_port.to_string())
        .env("CSSWITCH_SANDBOX_PORT", cfg.sandbox_port.to_string());
    // doctor 只做 -n 判空来报 key 有无。只让它知道「存在」，绝不把真实 key 传进其环境。
    if cfg.key_for(&cfg.provider).is_some() {
        cmd.env(key_env(&cfg.provider), "***present***");
    }
    let out = cmd.output().map_err(|e| e.to_string())?;
    let mut text = String::from_utf8_lossy(&out.stdout).to_string();
    let err = String::from_utf8_lossy(&out.stderr);
    if !err.trim().is_empty() {
        text.push_str("\n[stderr] ");
        text.push_str(err.trim());
    }
    Ok(text)
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle, state: State<'_, Mutex<AppState>>) -> Result<(), String> {
    // 默认：退 app 停代理、保留沙箱运行（spec §5.1）。
    {
        let mut st = lock(&state);
        kill_child(&mut st.proxy);
        st.secret.clear();
    }
    app.exit(0);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::redact;

    #[test]
    fn redact_scrubs_secret_and_is_noop_when_empty() {
        assert_eq!(redact("推理指向 http://127.0.0.1:18991/abcd1234 尾巴", "abcd1234"),
                   "推理指向 http://127.0.0.1:18991/**** 尾巴");
        assert_eq!(redact("原样返回", ""), "原样返回");
        assert!(!redact("leak abcd1234 leak abcd1234", "abcd1234").contains("abcd1234"));
    }
}

// ---------- 入口 ----------
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(Mutex::new(AppState::default()))
        .invoke_handler(tauri::generate_handler![
            get_config,
            set_config,
            save_provider_key,
            start_proxy,
            stop_all,
            one_click_login,
            status,
            open_url,
            run_doctor,
            quit_app
        ])
        .setup(|app| {
            // 菜单栏 app：从 Dock 隐藏（macOS）。
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            // 托盘图标：左键切换面板显隐。
            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("CSSwitch")
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(win) = app.get_webview_window("main") {
                            if win.is_visible().unwrap_or(false) {
                                let _ = win.hide();
                            } else {
                                let _ = win.show();
                                let _ = win.set_focus();
                            }
                        }
                    }
                })
                .build(app)?;

            // 面板失焦即隐藏（点面板外自动收起）。
            if let Some(win) = app.get_webview_window("main") {
                let w2 = win.clone();
                win.on_window_event(move |ev| {
                    if let tauri::WindowEvent::Focused(false) = ev {
                        let _ = w2.hide();
                    }
                });
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
