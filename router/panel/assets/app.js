(() => {
  const $ = (id) => document.getElementById(id);
  let config = null;
  let overview = null;
  let oauthFlowId = null;

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  }

  function flash(message, error = false) {
    const node = $("flash");
    node.textContent = message || "";
    node.className = message ? `flash show${error ? " error" : ""}` : "flash";
    if (message && !error) setTimeout(() => { node.className = "flash"; }, 3500);
  }

  function setVisible(authenticated) {
    $("login").hidden = authenticated;
    $("workspace").hidden = !authenticated;
  }

  function providerHealth(provider) {
    return overview?.providers?.[provider]?.health || {};
  }

  function management(provider) {
    return overview?.providers?.[provider]?.management || {};
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {credentials: "same-origin", ...options, headers: {"Content-Type": "application/json", ...(options.headers || {})}});
    let payload = {};
    try { payload = await response.json(); } catch (_) {}
    if (response.status === 401) { setVisible(false); throw new Error("登录已过期，请重新登录"); }
    if (!response.ok) throw new Error(payload.detail || payload.error || "操作失败");
    return payload;
  }

  async function action(path, body) {
    const payload = await api(path, {method: "POST", body: JSON.stringify(body)});
    await loadOverview();
    return payload;
  }

  function setTab(name) {
    document.querySelectorAll(".tab").forEach((node) => node.classList.toggle("active", node.dataset.tab === name));
    document.querySelectorAll(".tab-panel").forEach((node) => { node.hidden = node.id !== `tab-${name}`; node.classList.toggle("active", node.id === `tab-${name}`); });
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(Number(value) < 100000000000 ? Number(value) * 1000 : Number(value));
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", {hour12: false});
  }

  function renderOverview(payload) {
    overview = payload;
    const qHealth = providerHealth("qoder");
    const cHealth = providerHealth("codebuddy");
    const qMgmt = management("qoder");
    const cMgmt = management("codebuddy");
    const qData = qMgmt.data || {};
    const cData = cMgmt.data || {};
    const qAccounts = qData.accounts?.accounts || [];
    const cAccounts = cData.accounts || [];
    const checkin = payload.checkin || {providers: {}};
    const checkinCount = Object.values(checkin.providers || {}).reduce((sum, item) => sum + Number(item.count || 0), 0);

    $("api-base").textContent = config?.api_base || location.origin;
    $("gateway-summary").textContent = payload.status === "ok" ? "ONLINE" : "DEGRADED";
    $("gateway-detail").textContent = `${Object.keys(payload.gateway?.model_routes || {}).length} 条自定义路由`;
    $("qoder-summary").textContent = qHealth.ok ? `${qAccounts.length} 个账号` : "不可达";
    $("qoder-detail").textContent = qMgmt.ok === false ? qMgmt.error : (qData.status?.ready ? "已就绪" : "等待账号");
    $("codebuddy-summary").textContent = cHealth.ok ? `${cAccounts.length} 个账号` : "不可达";
    $("codebuddy-detail").textContent = cMgmt.ok === false ? cMgmt.error : (cData.pool?.routing === "manual" ? "手动调度" : "轮询调度");
    $("checkin-summary").textContent = `${checkinCount} 个账号`;
    $("checkin-detail").textContent = checkin.configured ? "配置文件已挂载" : "尚未配置账号";
    $("overall-status").textContent = payload.status === "ok" ? "所有服务已就绪" : "部分服务需要处理";
    $("overall-detail").textContent = "账号、密钥、配额和签到操作均由当前页面完成。";
    $("overall-dot").className = `status-dot ${payload.status === "ok" ? "online" : "bad"}`;
    $("gateway-pill").className = `pill ${payload.status === "ok" ? "online" : "bad"}`;
    $("gateway-pill").textContent = payload.status === "ok" ? "ONLINE" : "DEGRADED";
    $("default-provider").textContent = payload.gateway?.default_provider || "—";
    $("qoder-models").textContent = (payload.gateway?.models || []).join(", ") || "—";
    $("model-routes").textContent = Object.entries(payload.gateway?.model_routes || {}).map(([key, value]) => `${key} → ${value}`).join("，") || "未配置";
    $("last-updated").textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN", {hour12:false})}`;
    renderQoder(qData, qMgmt);
    renderCodeBuddy(cData, cMgmt);
    renderCheckin(checkin);
    const logs = checkin.log || [];
    $("activity-log").textContent = logs.length ? logs.slice(-30).join("\n") : "暂无签到日志";
  }

  function renderQoder(data, managementState) {
    const accounts = data.accounts?.accounts || [];
    $("qoder-account-count").textContent = `${accounts.length} 个账号`;
    if (!accounts.length) {
      $("qoder-accounts").innerHTML = '<tr><td colspan="5" class="empty">暂无 Qoder 账号，请使用 PAT 添加</td></tr>';
      return;
    }
    $("qoder-accounts").innerHTML = accounts.map((account) => {
      const active = account.uid === data.accounts.active_uid;
      const state = account.enabled === false ? "已暂停" : (account.last_status || (active ? "当前账号" : "可用"));
      return `<tr><td><strong>${escapeHtml(account.name || account.uid)}</strong><br><span class="muted">${escapeHtml(account.user_type || "")}</span></td><td><code>${escapeHtml(account.uid)}</code></td><td><span class="pill ${account.enabled === false ? "neutral" : "online"}">${escapeHtml(state)}</span></td><td>${escapeHtml(formatDate(account.token_expires_at || account.next_reset_at))}</td><td><div class="table-actions"><button class="secondary" data-qoder-action="select" data-id="${escapeHtml(account.uid)}">${active ? "当前" : "设为当前"}</button><button class="ghost" data-qoder-action="toggle" data-id="${escapeHtml(account.uid)}" data-enabled="${account.enabled === false}">${account.enabled === false ? "启用" : "暂停"}</button><button class="ghost" data-qoder-action="delete" data-id="${escapeHtml(account.uid)}">删除</button></div></td></tr>`;
    }).join("");
    if (managementState.ok === false) $("qoder-action-result").textContent = managementState.error || "Qoder 管理接口不可用";
  }

  function renderCodeBuddy(data, managementState) {
    const accounts = data.accounts || [];
    $("codebuddy-account-count").textContent = `${accounts.length} 个账号`;
    if (!accounts.length) $("codebuddy-accounts").innerHTML = '<tr><td colspan="5" class="empty">暂无 WorkBuddy 账号，可生成授权链接</td></tr>';
    else $("codebuddy-accounts").innerHTML = accounts.map((account) => `<tr><td><strong>${escapeHtml(account.name || account.nickname || account.id)}</strong><br><span class="muted">${escapeHtml(account.uid || "")}</span></td><td><span class="pill ${account.pool_state === "available" ? "online" : account.pool_state === "paused" ? "neutral" : "bad"}">${escapeHtml(account.pool_state || "unknown")}</span></td><td>${account.remaining == null ? "—" : escapeHtml(account.remaining)}</td><td>${account.today_checked_in ? "已签到" : "未签到"}</td><td><div class="table-actions"><button class="secondary" data-codebuddy-action="checkin" data-id="${escapeHtml(account.id)}">签到</button><button class="ghost" data-codebuddy-action="status" data-id="${escapeHtml(account.id)}">刷新</button><button class="ghost" data-codebuddy-action="toggle" data-id="${escapeHtml(account.id)}" data-enabled="${account.enabled === false}">${account.enabled === false ? "启用" : "暂停"}</button><button class="ghost" data-codebuddy-action="delete_account" data-id="${escapeHtml(account.id)}">删除</button></div></td></tr>`).join("");
    $("codebuddy-routing").value = data.pool?.routing || "round_robin";
    $("codebuddy-auto-checkin").checked = Boolean(data.pool?.auto_checkin);
    $("codebuddy-checkin-time").value = data.pool?.checkin_time || "09:00";
    const keys = data.keys || [];
    $("codebuddy-keys").innerHTML = keys.length ? keys.map((key) => `<tr><td>${escapeHtml(key.name)}</td><td><code>${escapeHtml(key.hint)}</code></td><td>${escapeHtml(formatDate(key.created))}</td><td><button class="ghost" data-codebuddy-action="revoke_key" data-id="${escapeHtml(key.id)}">撤销</button></td></tr>`).join("") : '<tr><td colspan="4" class="empty">暂无客户端 Key</td></tr>';
    if (managementState.ok === false) $("codebuddy-oauth-result").textContent = managementState.error || "WorkBuddy 管理接口不可用";
  }

  function renderCheckin(data) {
    for (const node of document.querySelectorAll(".checkin-provider")) {
      const provider = node.dataset.checkinProvider;
      const accounts = data.providers?.[provider]?.accounts || [];
      const list = node.querySelector(".checkin-list");
      list.innerHTML = accounts.length ? accounts.map((account) => `<div class="checkin-account"><span><strong>${escapeHtml(account.name)}</strong><br><small>${escapeHtml(account.token_hint || "未配置")}</small></span><button class="ghost" data-checkin-delete="${provider}" data-index="${account.index}">删除</button></div>`).join("") : '<div class="empty">暂无配置账号</div>';
    }
    $("checkin-log").textContent = data.log?.length ? data.log.slice(-60).join("\n") : "暂无签到日志";
  }

  async function loadConfig() {
    config = await api("/panel/api/config");
    $("api-base").textContent = config.api_base || location.origin;
    if (!config.enabled) $("login-error").textContent = "服务端未配置 PANEL_ADMIN_KEY。";
  }

  async function loadOverview() {
    const payload = await api("/panel/api/overview");
    renderOverview(payload);
  }

  async function refreshCheckin() {
    const payload = await api("/panel/api/checkin");
    if (overview) { overview.checkin = payload; renderCheckin(payload); }
  }

  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("login-error").textContent = "";
    try { await api("/panel/api/login", {method:"POST", body:JSON.stringify({key: $("panel-key").value})}); $("panel-key").value = ""; setVisible(true); await loadOverview(); }
    catch (error) { $("login-error").textContent = error.message; }
  });

  $("refresh").addEventListener("click", () => loadOverview().catch((error) => flash(error.message, true)));
  $("logout").addEventListener("click", async () => { try { await api("/panel/api/logout", {method:"POST"}); } finally { setVisible(false); } });
  $("copy-api").addEventListener("click", async () => { await navigator.clipboard.writeText($("api-base").textContent); $("copy-api").textContent = "已复制"; setTimeout(() => $("copy-api").textContent = "复制", 1500); });
  document.querySelectorAll(".tab").forEach((node) => node.addEventListener("click", () => setTab(node.dataset.tab)));
  document.querySelectorAll("[data-jump]").forEach((node) => node.addEventListener("click", () => setTab(node.dataset.jump)));

  $("qoder-pat-form").addEventListener("submit", async (event) => { event.preventDefault(); try { await action("/panel/api/qoder/action", {action:"import_pat", pat: $("qoder-pat").value}); $("qoder-pat").value = ""; $("qoder-action-result").textContent = "PAT 添加成功"; } catch (error) { $("qoder-action-result").textContent = error.message; } });
  $("qoder-batch-import").addEventListener("click", async () => { try { const records = JSON.parse($("qoder-batch").value); await action("/panel/api/qoder/action", {action:"batch_import", accounts: records}); $("qoder-batch").value = ""; flash("Qoder 批量导入完成"); } catch (error) { flash(error.message, true); } });
  $("qoder-refresh-tokens").addEventListener("click", async () => { try { const result = await action("/panel/api/qoder/action", {action:"refresh_tokens"}); $("qoder-action-result").textContent = `Token 刷新：成功 ${result.ok ?? 0}，失败 ${result.failed ?? 0}`; } catch (error) { flash(error.message, true); } });
  $("qoder-quota").addEventListener("click", async () => { try { const result = await action("/panel/api/qoder/action", {action:"quota"}); $("qoder-action-result").textContent = `已查询 ${result.total ?? 0} 个账号配额`; } catch (error) { flash(error.message, true); } });
  $("qoder-accounts").addEventListener("click", async (event) => { const button = event.target.closest("button[data-qoder-action]"); if (!button) return; const op = button.dataset.qoderAction; try { await action("/panel/api/qoder/action", {action: op, uid: button.dataset.id, enabled: op === "toggle" ? button.dataset.enabled === "true" : undefined}); } catch (error) { flash(error.message, true); } });

  $("codebuddy-pool-status").addEventListener("click", async () => { try { await action("/panel/api/codebuddy/action", {action:"pool_status"}); } catch (error) { flash(error.message, true); } });
  $("codebuddy-pool-checkin").addEventListener("click", async () => { try { await action("/panel/api/codebuddy/action", {action:"pool_checkin"}); } catch (error) { flash(error.message, true); } });
  $("codebuddy-settings-form").addEventListener("submit", async (event) => { event.preventDefault(); try { await action("/panel/api/codebuddy/action", {action:"pool_settings", routing: $("codebuddy-routing").value, auto_checkin: $("codebuddy-auto-checkin").checked, checkin_time: $("codebuddy-checkin-time").value}); flash("WorkBuddy 账号池设置已保存"); } catch (error) { flash(error.message, true); } });
  $("codebuddy-accounts").addEventListener("click", async (event) => { const button = event.target.closest("button[data-codebuddy-action]"); if (!button) return; const op = button.dataset.codebuddyAction; try { await action("/panel/api/codebuddy/action", {action: op === "toggle" ? "edit_account" : op, id: button.dataset.id, enabled: op === "toggle" ? button.dataset.enabled === "true" : undefined}); } catch (error) { flash(error.message, true); } });
  $("codebuddy-keys").addEventListener("click", async (event) => { const button = event.target.closest("button[data-codebuddy-action]"); if (!button) return; try { await action("/panel/api/codebuddy/action", {action: button.dataset.codebuddyAction, id: button.dataset.id}); } catch (error) { flash(error.message, true); } });
  $("codebuddy-add-key").addEventListener("click", async () => { try { const result = await action("/panel/api/codebuddy/action", {action:"add_key", name:"统一工作台客户端"}); const key = result.key || ""; $("codebuddy-new-key").hidden = false; $("codebuddy-new-key").textContent = key ? `新 Key 只显示这一次：${key}` : "Key 已生成"; } catch (error) { flash(error.message, true); } });
  $("codebuddy-oauth-form").addEventListener("submit", async (event) => { event.preventDefault(); try { const result = await api("/panel/api/codebuddy/action", {method:"POST", body:JSON.stringify({action:"oauth_start", name: $("codebuddy-account-name").value})}); oauthFlowId = result.id; $("codebuddy-oauth-link").href = result.url; $("codebuddy-oauth-flow").hidden = false; $("codebuddy-oauth-result").textContent = "授权链接已生成，请在新页面完成登录后查询结果。"; } catch (error) { $("codebuddy-oauth-result").textContent = error.message; } });
  $("codebuddy-oauth-poll").addEventListener("click", async () => { if (!oauthFlowId) return; try { const result = await action("/panel/api/codebuddy/action", {action:"oauth_poll", flow_id: oauthFlowId}); $("codebuddy-oauth-result").textContent = result.status === "success" ? "授权成功，账号已加入池。" : `授权状态：${result.status}`; if (result.status === "success") { oauthFlowId = null; $("codebuddy-oauth-flow").hidden = true; } } catch (error) { $("codebuddy-oauth-result").textContent = error.message; } });
  $("codebuddy-oauth-cancel").addEventListener("click", async () => { if (!oauthFlowId) return; try { await action("/panel/api/codebuddy/action", {action:"oauth_cancel", flow_id: oauthFlowId}); } catch (_) {} oauthFlowId = null; $("codebuddy-oauth-flow").hidden = true; });

  $("checkin-refresh").addEventListener("click", () => refreshCheckin().catch((error) => flash(error.message, true)));
  document.querySelectorAll(".checkin-provider").forEach((node) => {
    const provider = node.dataset.checkinProvider;
    node.querySelector(".checkin-run").addEventListener("click", async () => { try { const result = await api("/panel/api/checkin/run", {method:"POST", body:JSON.stringify({provider})}); renderCheckin(result.overview); flash(`${provider} 签到${result.ok ? "完成" : "失败"}` , !result.ok); } catch (error) { flash(error.message, true); } });
    node.querySelector(".checkin-form").addEventListener("submit", async (event) => { event.preventDefault(); const account = Object.fromEntries(new FormData(event.currentTarget).entries()); try { const result = await api("/panel/api/checkin/accounts", {method:"POST", body:JSON.stringify({provider, account})}); if (overview) overview.checkin = result; renderCheckin(result); event.currentTarget.reset(); flash(`${provider} 账号已保存`); } catch (error) { flash(error.message, true); } });
  });
  document.addEventListener("click", async (event) => { const button = event.target.closest("button[data-checkin-delete]"); if (!button) return; try { const result = await api(`/panel/api/checkin/accounts/${button.dataset.checkinDelete}/${button.dataset.index}`, {method:"DELETE"}); if (overview) overview.checkin = result; renderCheckin(result); flash("签到账号已删除"); } catch (error) { flash(error.message, true); } });

  (async () => {
    try {
      await loadConfig();
      const session = await api("/panel/api/session");
      setVisible(Boolean(session.authenticated));
      if (session.authenticated) await loadOverview();
    } catch (error) { $("login-error").textContent = error.message || "工作台连接失败"; }
    setInterval(() => { if (!$('workspace').hidden) loadOverview().catch(() => {}); }, 20000);
  })();
})();
