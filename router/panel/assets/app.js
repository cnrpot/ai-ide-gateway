(() => {
  const $ = (id) => document.getElementById(id);
  let config = null;

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  }

  function setVisible(authenticated) {
    $("login").hidden = authenticated;
    $("workspace").hidden = !authenticated;
  }

  function setProvider(name, data) {
    const pill = $(`${name}-status`);
    const detail = $(`${name}-detail`);
    const ok = Boolean(data && data.ok);
    pill.className = `pill ${ok ? "online" : "bad"}`;
    pill.textContent = ok ? "ONLINE" : "OFFLINE";
    detail.textContent = ok ? `HTTP ${data.status_code}` : (data.error || "不可达");
  }

  function renderStatus(payload) {
    setProvider("qoder", payload.providers.qoder);
    setProvider("codebuddy", payload.providers.codebuddy);
    $("qoder-link").href = payload.consoles.qoder;
    $("codebuddy-link").href = payload.consoles.codebuddy;
    $("api-base").textContent = payload.api_base || config.api_base;
    $("gateway-url").textContent = payload.api_base || config.api_base;
    const healthy = payload.status === "ok";
    $("overall-status").textContent = healthy ? "所有后端已就绪" : "部分服务需要处理";
    $("overall-detail").textContent = healthy ? "统一入口和两个管理控制台均可访问。" : "请查看卡片状态或打开对应控制台。";
    $("last-updated").textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN", {hour12:false})}`;
  }

  async function loadConfig() {
    const response = await fetch("/panel/api/config", {credentials:"same-origin"});
    config = await response.json();
    $("api-base").textContent = config.api_base;
    $("gateway-url").textContent = config.api_base;
    if (!config.enabled) $("login-error").textContent = "服务端未配置 PANEL_ADMIN_KEY。";
  }

  async function loadStatus() {
    const response = await fetch("/panel/api/status", {credentials:"same-origin"});
    if (response.status === 401) { setVisible(false); return; }
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "状态读取失败");
    renderStatus(payload);
  }

  async function checkSession() {
    const response = await fetch("/panel/api/session", {credentials:"same-origin"});
    const payload = await response.json();
    setVisible(Boolean(payload.authenticated));
    if (payload.authenticated) await loadStatus();
  }

  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("login-error").textContent = "";
    const response = await fetch("/panel/api/login", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body:JSON.stringify({key:$("panel-key").value})});
    const payload = await response.json();
    if (!response.ok) { $("login-error").textContent = payload.detail || "登录失败"; return; }
    $("panel-key").value = ""; setVisible(true);
    try { await loadStatus(); } catch (error) { $("login-error").textContent = error.message; }
  });

  $("refresh").addEventListener("click", () => loadStatus().catch((error) => { $("overall-detail").textContent = error.message; }));
  $("logout").addEventListener("click", async () => { await fetch("/panel/api/logout", {method:"POST", credentials:"same-origin"}); setVisible(false); });
  $("copy-api").addEventListener("click", async () => { await navigator.clipboard.writeText($("api-base").textContent); $("copy-api").textContent = "已复制"; setTimeout(() => $("copy-api").textContent = "复制", 1500); });

  (async () => {
    try { await loadConfig(); await checkSession(); } catch (error) { $("login-error").textContent = error.message || "面板连接失败"; }
    setInterval(() => { if (!$('workspace').hidden) loadStatus().catch(() => {}); }, 15000);
  })();
})();
