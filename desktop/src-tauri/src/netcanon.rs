//! 敏感模式白名单的 host 规范化 + 分类。
//!
//! 目标（对齐用户 phase-5 要求）：
//!   - 接受 URL **或**裸 host，内部统一成 host：去 scheme / port / userinfo / path / 末尾点、
//!     小写、IDNA punycode（中文 / 国际化域名 → xn--）。
//!   - 分类：localhost / 私网 IP / 公网域名。敏感模式只允许 localhost / 私网 /
//!     **用户明确确认的机构域名**。
//!   - denylist（公有大模型 API host）作为最外层硬拒。
//!
//! IDNA 由 `url` crate（内部 `idna`）负责，故中文机构域名也能被正确规范化比对。

use url::Url;

/// host 分类。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HostClass {
    /// localhost / 127.0.0.0/8 / ::1
    Localhost,
    /// RFC1918 私网 / 链路本地 / ULA
    PrivateIp,
    /// 公网域名 / 公网 IP —— 敏感模式下需用户明确确认才收
    Public,
}

/// 公有大模型 API host —— 绝不允许进白名单（否则等于绕过敏感模式）。
pub const PUBLIC_DENY: &[&str] = &[
    "api.deepseek.com",
    "dashscope.aliyuncs.com",
    "api.anthropic.com",
    "anthropic.com",
    "claude.ai",
    "openai.com",
    "api.openai.com",
    "open.bigmodel.cn",
    "api.xiaomimimo.com",
    "api.siliconflow.cn",
    "openrouter.ai",
    "generativelanguage.googleapis.com",
];

/// 把 URL 或裸 host 规范化成 host 字符串。失败返回 Err（附原因）。
///
/// 规则：
///   1. 没有 scheme 就补 `http://` 再解析（`url` 要求有 scheme）。
///   2. 取 host（`url` 已做 IDNA → punycode），小写，去末尾点。
///   3. 拒绝空 host / 带路径以外的怪异输入。
pub fn canonicalize_host(input: &str) -> Result<String, String> {
    let raw = input.trim();
    if raw.is_empty() {
        return Err("空 host".into());
    }
    // 若看起来已带 scheme（含 "://"）直接解析；否则补 http://。
    let with_scheme = if raw.contains("://") {
        raw.to_string()
    } else {
        // 裸 host 可能带 port（host:1234）或路径（host/x）——补 scheme 后交给 url 解析。
        format!("http://{raw}")
    };
    let parsed = Url::parse(&with_scheme).map_err(|e| format!("无法解析 `{raw}`：{e}"))?;
    let host = parsed
        .host_str()
        .ok_or_else(|| format!("`{raw}` 里没有 host"))?;
    // url 已 IDNA 编码；这里只做小写 + 去末尾点（punycode 全 ASCII，小写安全）。
    let mut h = host.to_ascii_lowercase();
    while h.ends_with('.') {
        h.pop();
    }
    if h.is_empty() {
        return Err(format!("`{raw}` 规范化后 host 为空"));
    }
    Ok(h)
}

/// 判断 host 是否命中 denylist（公有 API）。传入的 host 应已规范化。
pub fn is_public_deny(host: &str) -> bool {
    let h = host.to_ascii_lowercase();
    PUBLIC_DENY.iter().any(|d| h == *d || h.ends_with(&format!(".{d}")))
}

/// 分类一个已规范化的 host。
pub fn classify(host: &str) -> HostClass {
    let h = host.to_ascii_lowercase();
    if h == "localhost" || h == "localhost.localdomain" {
        return HostClass::Localhost;
    }
    // IPv6 loopback（url 会把 [::1] 的 host_str 返回 "[::1]"）
    if h == "[::1]" || h == "::1" {
        return HostClass::Localhost;
    }
    // 尝试按 IPv4 解析
    if let Some(cls) = classify_ipv4(&h) {
        return cls;
    }
    // IPv6 ULA fc00::/7 / 链路本地 fe80::/10（粗判前缀）
    let h6 = h.trim_start_matches('[').trim_end_matches(']');
    if h6.starts_with("fc") || h6.starts_with("fd") || h6.starts_with("fe8")
        || h6.starts_with("fe9") || h6.starts_with("fea") || h6.starts_with("feb")
    {
        return HostClass::PrivateIp;
    }
    HostClass::Public
}

fn classify_ipv4(h: &str) -> Option<HostClass> {
    let octets: Vec<u8> = h.split('.').filter_map(|s| s.parse::<u8>().ok()).collect();
    if octets.len() != 4 || h.split('.').count() != 4 {
        return None;
    }
    let (a, b) = (octets[0], octets[1]);
    if a == 127 {
        return Some(HostClass::Localhost);
    }
    // 10.0.0.0/8
    if a == 10 {
        return Some(HostClass::PrivateIp);
    }
    // 172.16.0.0/12
    if a == 172 && (16..=31).contains(&b) {
        return Some(HostClass::PrivateIp);
    }
    // 192.168.0.0/16
    if a == 192 && b == 168 {
        return Some(HostClass::PrivateIp);
    }
    // 169.254.0.0/16 链路本地
    if a == 169 && b == 254 {
        return Some(HostClass::PrivateIp);
    }
    // 其它都是公网 IP
    Some(HostClass::Public)
}

/// 一条白名单条目校验的结论。
#[derive(Debug, Clone, PartialEq)]
pub enum HostVerdict {
    /// 自动接受（localhost / 私网）
    AutoAccept(String),
    /// 公网域名，需要用户显式确认（confirm_public=true 才收）
    NeedsConfirm(String),
    /// 命中 denylist，硬拒
    Denied(String),
    /// 规范化失败
    Invalid(String),
}

/// 校验一条输入（URL 或 host）。不落盘，纯函数便于测试。
pub fn vet_one(input: &str) -> HostVerdict {
    let host = match canonicalize_host(input) {
        Ok(h) => h,
        Err(e) => return HostVerdict::Invalid(e),
    };
    if is_public_deny(&host) {
        return HostVerdict::Denied(host);
    }
    match classify(&host) {
        HostClass::Localhost | HostClass::PrivateIp => HostVerdict::AutoAccept(host),
        HostClass::Public => HostVerdict::NeedsConfirm(host),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonicalize_strips_scheme_port_path() {
        assert_eq!(canonicalize_host("https://LLM.Hospital.Internal:8443/v1").unwrap(),
                   "llm.hospital.internal");
        assert_eq!(canonicalize_host("llm.hospital.internal").unwrap(),
                   "llm.hospital.internal");
        assert_eq!(canonicalize_host("http://10.0.0.5:11434").unwrap(), "10.0.0.5");
        assert_eq!(canonicalize_host("Host.Local.").unwrap(), "host.local");
        assert_eq!(canonicalize_host("localhost:8080").unwrap(), "localhost");
    }

    #[test]
    fn canonicalize_idna_punycode() {
        // 中文机构域名 → punycode。比对时两边都规范化，故仍能匹配。
        let h = canonicalize_host("https://医院.example/v1").unwrap();
        assert!(h.starts_with("xn--"), "IDNA 应转 punycode：{h}");
        // 同一域名不同写法规范化后一致
        assert_eq!(canonicalize_host("医院.example").unwrap(), h);
    }

    #[test]
    fn canonicalize_rejects_empty() {
        assert!(canonicalize_host("").is_err());
        assert!(canonicalize_host("   ").is_err());
    }

    #[test]
    fn classify_localhost_and_private() {
        assert_eq!(classify("localhost"), HostClass::Localhost);
        assert_eq!(classify("127.0.0.1"), HostClass::Localhost);
        assert_eq!(classify("[::1]"), HostClass::Localhost);
        assert_eq!(classify("10.1.2.3"), HostClass::PrivateIp);
        assert_eq!(classify("172.16.0.1"), HostClass::PrivateIp);
        assert_eq!(classify("172.32.0.1"), HostClass::Public); // 172.32 不在 /12
        assert_eq!(classify("192.168.1.1"), HostClass::PrivateIp);
        assert_eq!(classify("169.254.1.1"), HostClass::PrivateIp);
        assert_eq!(classify("8.8.8.8"), HostClass::Public);
        assert_eq!(classify("llm.hospital.internal"), HostClass::Public);
    }

    #[test]
    fn deny_public_api_hosts_incl_subdomains() {
        assert!(is_public_deny("api.deepseek.com"));
        assert!(is_public_deny("foo.api.anthropic.com"));
        assert!(is_public_deny("dashscope.aliyuncs.com"));
        assert!(!is_public_deny("llm.hospital.internal"));
        assert!(!is_public_deny("10.0.0.1"));
    }

    #[test]
    fn vet_one_paths() {
        assert_eq!(vet_one("http://127.0.0.1:11434"), HostVerdict::AutoAccept("127.0.0.1".into()));
        assert_eq!(vet_one("10.0.0.5"), HostVerdict::AutoAccept("10.0.0.5".into()));
        assert_eq!(vet_one("https://api.deepseek.com"), HostVerdict::Denied("api.deepseek.com".into()));
        assert_eq!(vet_one("llm.hospital.internal"),
                   HostVerdict::NeedsConfirm("llm.hospital.internal".into()));
        assert!(matches!(vet_one(""), HostVerdict::Invalid(_)));
    }
}
