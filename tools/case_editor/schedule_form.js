const ROUTE_MARKERS = ["/cases", "/public-actions", "/iterations", "/schedules", "/api", "/reports"];
const APP_BASE_PATH = normalizeBasePath(window.__MINITEST_BASE_PATH__ || inferBasePath());
const EMBED_MODE = new URLSearchParams(window.location.search).get("embed") === "1";
const form = document.querySelector("#scheduleEditorForm");
const titleEl = document.querySelector("#scheduleEditorTitle");
const messageEl = document.querySelector("#scheduleFormMessage");
const saveButton = document.querySelector("#saveScheduleBtn");
const presetEl = document.querySelector("#schedulePreset");
const runTargetEl = document.querySelector("#scheduleRunTarget");
const iterationEl = document.querySelector("#scheduleIteration");
const legacyWarningEl = document.querySelector("#scheduleLegacyWarning");

function normalizeBasePath(value) {
  value = String(value || "").trim().replace(/\/+$/, "");
  if (!value || value === "/") return "";
  return value.startsWith("/") ? value : `/${value}`;
}
function inferBasePath() {
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  for (const marker of ROUTE_MARKERS) {
    const index = path.indexOf(marker);
    if (index > 0) return path.slice(0, index);
  }
  return "";
}
function withBasePath(path) {
  path = String(path || "");
  if (!path.startsWith("/")) return path;
  if (APP_BASE_PATH && (path === APP_BASE_PATH || path.startsWith(`${APP_BASE_PATH}/`))) return path;
  return `${APP_BASE_PATH}${path}` || path;
}
function appUrl(path) {
  const [pathname, query = ""] = String(path || "").split("?");
  const params = new URLSearchParams(query);
  if (EMBED_MODE && !params.has("embed")) params.set("embed", "1");
  const nextQuery = params.toString();
  return `${withBasePath(pathname)}${nextQuery ? `?${nextQuery}` : ""}`;
}
async function api(path, options = {}) {
  const response = await fetch(withBasePath(path), { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.error || `请求失败：${response.status}`);
  return data;
}
function setMessage(message = "", type = "") {
  messageEl.textContent = message;
  messageEl.className = `form-message ${type}`.trim();
}
function syncPreset() {
  const value = form.cron_expr.value.trim();
  const option = [...presetEl.options].find((item) => item.value === value);
  presetEl.value = option ? value : (value ? "custom" : "");
}
function fillSchedule(item) {
  for (const field of ["id", "schedule_name", "cron_expr", "run_target", "remark"]) form[field].value = item[field] || "";
  iterationEl.value = item.iteration_id || "";
  if (!item.iteration_id && item.legacy_case_id) {
    legacyWarningEl.textContent = `此旧任务原来绑定用例 ${item.legacy_case_id}，请为它选择一个迭代后保存；未迁移前不会执行。`;
    legacyWarningEl.hidden = false;
  }
  form.enabled.checked = Number(item.enabled) !== 0;
  titleEl.textContent = "编辑定时任务";
  document.title = `编辑定时任务 - ${item.schedule_name || item.id}`;
  syncPreset();
}
function buildPayload() {
  const payload = Object.fromEntries(new FormData(form).entries());
  for (const key of ["schedule_name", "iteration_id", "cron_expr", "run_target", "remark"]) payload[key] = String(payload[key] || "").trim();
  payload.enabled = form.enabled.checked ? 1 : 0;
  if (!payload.schedule_name) throw new Error("请填写任务名称");
  if (!payload.iteration_id) throw new Error("请选择要执行的迭代");
  if (!payload.cron_expr) throw new Error("请选择或填写执行时间");
  if (!payload.id) delete payload.id;
  return payload;
}
async function saveSchedule(event) {
  event.preventDefault();
  saveButton.disabled = true;
  setMessage("正在保存...");
  try {
    const payload = buildPayload();
    const endpoint = payload.id ? "/api/schedule_edit" : "/api/schedule_create";
    await api(endpoint, { method: "POST", body: JSON.stringify(payload) });
    setMessage("保存成功，正在返回任务列表。", "success");
    window.setTimeout(() => { window.location.href = appUrl("/schedules"); }, 350);
  } catch (error) {
    setMessage(`保存失败：${error.message}`, "error");
  } finally {
    saveButton.disabled = false;
  }
}
async function init() {
  document.querySelectorAll('a[href^="/"]').forEach((link) => link.setAttribute("href", appUrl(link.getAttribute("href"))));
  const id = new URLSearchParams(window.location.search).get("id") || new URLSearchParams(window.location.search).get("schedule_id") || "";
  try {
    const [agentsData, iterationData] = await Promise.all([
      api("/api/agents"),
      api("/api/iteration_options"),
    ]);
    fillRunTargets(agentsData);
    fillIterations(iterationData.iteration_options || []);
    if (id) {
      const data = await api(`/api/schedule_detail?id=${encodeURIComponent(id)}`);
      fillSchedule(data.schedule || {});
    }
  } catch (error) {
    setMessage(`页面初始化失败：${error.message}`, "error");
  }
}

function fillIterations(iterations) {
  iterationEl.replaceChildren(new Option("选择一个迭代", ""));
  for (const iteration of iterations) {
    const name = iteration.iteration_name || iteration.iteration_code || `#${iteration.iteration_id}`;
    const code = iteration.iteration_code || "";
    iterationEl.appendChild(new Option(code ? `${name} (${code})` : name, String(iteration.iteration_id)));
  }
  if (!iterations.length) {
    iterationEl.replaceChildren(new Option("暂无可执行迭代", ""));
    setMessage("请先创建迭代，并添加至少一个已启用的正式用例。", "error");
  }
}

function fillRunTargets(data = {}) {
  const current = runTargetEl.value || "center";
  runTargetEl.innerHTML = "";
  if (data.center_execution_enabled !== false) {
    runTargetEl.appendChild(new Option("中心机（当前服务所在电脑）", "center"));
  }
  if (data.remote_agents_enabled) {
    for (const agent of data.agents || []) {
      if (!agent.agent_id || Number(agent.enabled) === 0) continue;
      const label = agent.agent_name
        ? `${agent.agent_name}（${agent.agent_id}${agent.agent_ip ? ` / ${agent.agent_ip}` : ""}）`
        : `${agent.agent_id}${agent.agent_ip ? `（${agent.agent_ip}）` : ""}`;
      runTargetEl.appendChild(new Option(label, agent.agent_id));
    }
  }
  if (![...runTargetEl.options].some((option) => option.value === current)) {
    runTargetEl.value = runTargetEl.options[0]?.value || "";
  } else {
    runTargetEl.value = current;
  }
  if (!runTargetEl.options.length) {
    runTargetEl.appendChild(new Option("暂无可用执行机", ""));
  }
}
presetEl.addEventListener("change", () => {
  if (presetEl.value === "custom") return form.cron_expr.focus();
  if (presetEl.value) form.cron_expr.value = presetEl.value;
});
form.cron_expr.addEventListener("input", syncPreset);
form.addEventListener("submit", saveSchedule);
init();
