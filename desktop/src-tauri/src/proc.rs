//! 进程管家用到的纯 std 辅助：探活、依赖定位、一次性 secret 生成、上游可达性。
//! 无第三方依赖，便于单测；有状态的子进程编排放在 lib.rs（持 Child 句柄）。

use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::PathBuf;
use std::time::Duration;

/// 对本地回环代理做 HTTP 探活：`GET /<secret>/health`，响应状态行含 200 即视为健康。
/// 代理带 path-secret 鉴权时必须带上 secret，否则会拿到 403。
pub fn http_health(port: u16, secret: Option<&str>, timeout_ms: u64) -> bool {
    let addr = match ("127.0.0.1", port).to_socket_addrs().ok().and_then(|mut a| a.next()) {
        Some(a) => a,
        None => return false,
    };
    let dur = Duration::from_millis(timeout_ms);
    let mut stream = match TcpStream::connect_timeout(&addr, dur) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(dur));
    let _ = stream.set_write_timeout(Some(dur));
    let path = match secret {
        Some(s) if !s.is_empty() => format!("/{s}/health"),
        _ => "/health".to_string(),
    };
    let req = format!("GET {path} HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = Vec::new();
    // 只需读到状态行；读上限防呆。
    let mut chunk = [0u8; 1024];
    while buf.len() < 8192 {
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
            Err(_) => break,
        }
        if buf.windows(4).any(|w| w == b"\r\n\r\n") {
            break;
        }
    }
    let head = String::from_utf8_lossy(&buf);
    let status_line = head.lines().next().unwrap_or("");
    status_line.contains(" 200")
}

/// 上游主机可达性（仅 TCP 连通，不校验 key）。绿灯=可达，黄灯=不可达。
pub fn tcp_reachable(host: &str, port: u16, timeout_ms: u64) -> bool {
    let dur = Duration::from_millis(timeout_ms);
    match (host, port).to_socket_addrs() {
        Ok(addrs) => {
            for a in addrs {
                if TcpStream::connect_timeout(&a, dur).is_ok() {
                    return true;
                }
            }
            false
        }
        Err(_) => false,
    }
}

/// 在 PATH 里找可执行文件（简易 which）。找不到返回 None。
pub fn which(name: &str) -> Option<PathBuf> {
    // 绝对/相对路径直接判定。
    let p = PathBuf::from(name);
    if p.is_absolute() {
        return if is_exec(&p) { Some(p) } else { None };
    }
    let path = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path) {
        let cand = dir.join(name);
        if is_exec(&cand) {
            return Some(cand);
        }
    }
    None
}

fn is_exec(p: &std::path::Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    match std::fs::metadata(p) {
        Ok(md) => md.is_file() && (md.permissions().mode() & 0o111 != 0),
        Err(_) => false,
    }
}

/// 生成一次性 path-secret：从 /dev/urandom 取 16 字节，hex 编码为 32 字符。
/// 失败时退回一个基于 pid 与时间的弱值（仅避免 panic；正常路径永远走 urandom）。
pub fn gen_secret() -> String {
    use std::fs::File;
    let mut b = [0u8; 16];
    if let Ok(mut f) = File::open("/dev/urandom") {
        if f.read_exact(&mut b).is_ok() {
            return hex(&b);
        }
    }
    let t = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("s{}{}", std::process::id(), t)
}

fn hex(bytes: &[u8]) -> String {
    const H: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::with_capacity(bytes.len() * 2);
    for &byte in bytes {
        s.push(H[(byte >> 4) as usize] as char);
        s.push(H[(byte & 0xf) as usize] as char);
    }
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn health_false_when_nothing_listening() {
        // 一个几乎肯定没人监听的高端口。
        assert!(!http_health(59999, None, 300));
    }

    #[test]
    fn which_finds_sh() {
        let sh = which("sh");
        assert!(sh.is_some(), "PATH 里应能找到 sh");
        assert!(sh.unwrap().is_absolute());
    }

    #[test]
    fn which_absent_returns_none() {
        assert!(which("definitely-not-a-real-binary-xyzzy").is_none());
    }

    #[test]
    fn gen_secret_is_32_hex_and_varies() {
        let a = gen_secret();
        let b = gen_secret();
        assert_eq!(a.len(), 32, "urandom 路径应是 32 hex 字符");
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, b, "两次生成应不同");
    }

    #[test]
    fn hex_encodes_known_bytes() {
        assert_eq!(hex(&[0x00, 0x0f, 0xff, 0xa5]), "000fffa5");
    }
}
