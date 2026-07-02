// CSSwitch 菜单栏面板前端。只调用后端 Tauri command，绝不碰任何密钥落盘逻辑。
// 后端只把 key 的【掩码】回显给这里；完整 key 永不进前端。
const { invoke } = window.__TAURI__.core;

const $ = (id) => document.getElementById(id);
const els = {};
let statusTimer = null;
let busy = false;

const KEY_LABELS = { deepseek: "DeepSeek API Key", qwen: "DashScope (通义千问) API Key" };

function setMsg(text, kind) {
  els.msg.textContent = text;
  els.msg.className = "msg" + (kind ? " " + kind : "");
}

function setLight(el, state) {
  // state: "green" | "amber" | "red"
  const cls = { green: "g", amber: "a", red: "r" }[state] || "a";
  el.className = "lt " + cls;
}

function setBusy(on) {
  busy = on;
  [els.oneClickBtn, els.startProxyBtn, els.stopBtn, els.saveKeyBtn].forEach(
    (b) => (b.disabled = on)
  );
}

async function call(cmd, args) {
  return await invoke(cmd, args);
}

async function loadConfig() {
  try {
    const cfg = await call("get_config");
    els.provider.value = cfg.provider || "deepseek";
    els.proxyPort.value = cfg.proxy_port ?? 18991;
    els.sandboxPort.value = cfg.sandbox_port ?? 8990;
    window._keys = cfg.keys || {};
    reflectProvider();
  } catch (e) {
    setMsg("读取配置失败：" + e, "err");
  }
}

function reflectProvider() {
  const p = els.provider.value;
  els.keyLabel.textContent = KEY_LABELS[p] || "API Key";
  const masked = (window._keys && window._keys[p]) || "";
  els.keyInput.value = "";
  els.keyInput.placeholder = masked ? "已存：" + masked : "粘贴第三方 key（只存本地）";
}

function currentSettings() {
  return {
    provider: els.provider.value,
    proxy_port: parseInt(els.proxyPort.value, 10) || 18991,
    sandbox_port: parseInt(els.sandboxPort.value, 10) || 8990,
  };
}

async function persistSettings() {
  try {
    await call("set_config", { cfg: currentSettings() });
  } catch (e) {
    setMsg("保存设置失败：" + e, "err");
  }
}

async function saveKey() {
  const key = els.keyInput.value.trim();
  if (!key) {
    setMsg("请先粘贴 key。", "err");
    return;
  }
  setBusy(true);
  try {
    const masked = await call("save_provider_key", { provider: els.provider.value, key });
    window._keys[els.provider.value] = masked;
    reflectProvider();
    setMsg("已保存到 ~/.csswitch/config.json（0600）。", "ok");
  } catch (e) {
    setMsg("保存 key 失败：" + e, "err");
  } finally {
    setBusy(false);
  }
}

async function startProxy() {
  setBusy(true);
  setMsg("启动代理中…");
  try {
    await persistSettings();
    const r = await call("start_proxy");
    setMsg("代理已启动，端口 " + r.port + "。", "ok");
    await refreshStatus();
  } catch (e) {
    setMsg("启动代理失败：" + e, "err");
  } finally {
    setBusy(false);
  }
}

async function stopAll() {
  setBusy(true);
  setMsg("停止中…");
  try {
    await call("stop_all");
    setMsg("已停止代理与沙箱。", "ok");
    await refreshStatus();
  } catch (e) {
    setMsg("停止失败：" + e, "err");
  } finally {
    setBusy(false);
  }
}

async function oneClick() {
  setBusy(true);
  setMsg("一键越过登录：起代理 → 起沙箱 → 探活…");
  try {
    await persistSettings();
    const r = await call("one_click_login");
    setMsg("登录态就绪。正在打开浏览器面板…\n" + (r.url || ""), "ok");
    await refreshStatus();
  } catch (e) {
    setMsg("一键越登录失败：" + e, "err");
  } finally {
    setBusy(false);
  }
}

async function openBrowser() {
  try {
    await call("open_url", {});
  } catch (e) {
    setMsg("打开浏览器失败：" + e, "err");
  }
}

async function runDoctor() {
  setMsg("自检中…");
  try {
    const out = await call("run_doctor");
    setMsg(out, out.includes("失败 0") ? "ok" : null);
  } catch (e) {
    setMsg("自检失败：" + e, "err");
  }
}

async function refreshStatus() {
  try {
    const s = await call("status");
    setLight(els.ltProxy, s.proxy);
    setLight(els.ltSandbox, s.sandbox);
    setLight(els.ltUpstream, s.upstream);
    const anyGreen = s.proxy === "green" || s.sandbox === "green";
    els.brandDot.className = "dot" + (s.proxy === "green" ? "" : " amber");
  } catch (e) {
    // 状态探测失败不打断，静默降级为黄灯。
    [els.ltProxy, els.ltSandbox, els.ltUpstream].forEach((l) => setLight(l, "amber"));
  }
}

function wire() {
  [
    "provider", "keyLabel", "keyInput", "saveKeyBtn", "proxyPort", "sandboxPort",
    "oneClickBtn", "startProxyBtn", "stopBtn", "ltProxy", "ltSandbox", "ltUpstream",
    "msg", "brandDot", "openBrowserBtn", "doctorBtn", "quitBtn",
  ].forEach((id) => (els[id] = $(id)));

  els.provider.addEventListener("change", async () => {
    reflectProvider();
    await persistSettings();
  });
  els.proxyPort.addEventListener("change", persistSettings);
  els.sandboxPort.addEventListener("change", persistSettings);
  els.saveKeyBtn.addEventListener("click", saveKey);
  els.startProxyBtn.addEventListener("click", startProxy);
  els.stopBtn.addEventListener("click", stopAll);
  els.oneClickBtn.addEventListener("click", oneClick);
  els.openBrowserBtn.addEventListener("click", openBrowser);
  els.doctorBtn.addEventListener("click", runDoctor);
  els.quitBtn.addEventListener("click", () => call("quit_app").catch(() => {}));
}

window.addEventListener("DOMContentLoaded", async () => {
  wire();
  await loadConfig();
  await refreshStatus();
  statusTimer = setInterval(refreshStatus, 2500);
});
