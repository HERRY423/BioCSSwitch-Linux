use std::process::Child;
use std::sync::{Mutex, MutexGuard};

#[derive(Default)]
pub(crate) struct AppState {
    pub(crate) proxy: Option<Child>,
    pub(crate) proxy_port: u16,
    pub(crate) secret: String,
    pub(crate) provider: String,
    pub(crate) key_fp: u64,
    pub(crate) sandbox: Option<Child>,
    pub(crate) sandbox_port: u16,
    pub(crate) sandbox_url: Option<String>,
}

pub(crate) fn key_fingerprint(s: &str) -> u64 {
    use std::hash::{Hash, Hasher};
    let mut h = std::collections::hash_map::DefaultHasher::new();
    s.hash(&mut h);
    h.finish()
}

pub(crate) fn kill_child(slot: &mut Option<Child>) {
    if let Some(mut c) = slot.take() {
        let _ = c.kill();
        let _ = c.wait();
    }
}

pub(crate) fn lock(m: &Mutex<AppState>) -> MutexGuard<'_, AppState> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}
