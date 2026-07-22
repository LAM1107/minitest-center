const DEFAULT_RUNTIME_PAGE_SIZE = 10;
const DEFAULT_PUBLIC_ACTION_PAGE_SIZE = 10;
const DEFAULT_ITERATION_PAGE_SIZE = 10;
// 执行位置属于当前浏览器的全局选择，迭代、正式用例和编辑页都会复用它。
const EXECUTION_TARGET_STORAGE_KEY = "minitest.execution_target";
const LEGACY_EXECUTION_TARGET_STORAGE_KEY = "minitest.iteration_execution_target";

// 页面运行时状态：接口返回的数据先放在这里，再由各个 render 函数渲染到表格。
// 它只存在于浏览器内存，刷新页面后会重新从 API 加载。
const state = {
  runtimeCases: [],
  iterations: [],
  executionAgents: [],
  remoteAgentsEnabled: false,
  centerExecutionEnabled: true,
  executionTargetId: "",
  jobs: [],
  reports: [],
  runtimePagination: {
    page: 1,
    page_size: DEFAULT_RUNTIME_PAGE_SIZE,
    total: 0,
    total_pages: 1,
  },
  publicActionPagination: {
    page: 1,
    page_size: DEFAULT_PUBLIC_ACTION_PAGE_SIZE,
    total: 0,
    total_pages: 1,
  },
  iterationPagination: {
    page: 1,
    page_size: DEFAULT_ITERATION_PAGE_SIZE,
    total: 0,
    total_pages: 1,
  },
  options: {
    step_actions: [],
    locator_methods: [],
    assert_types: [],
    public_step_actions: [],
    public_step_actions_pagination: {},
    page_options: [],
    iteration_options: [],
  },
  activeView: "runtime",
  pollTimer: null,
  publicActionFilterTimer: null,
  publicActionEditId: "",
  publicActionEditEnabled: 1,
};

// 管理页既支持根路径，也支持反向代理挂载到 /minitest 之类的子路径。
const EXPECTED_SERVER_VERSION = "case-editor-20260722-center-runtime-v23";
const ROUTE_MARKERS = ["/cases", "/public-actions", "/iterations", "/api", "/reports"];
const APP_BASE_PATH = normalizeBasePath(window.__MINITEST_BASE_PATH__ || inferBasePath());
const EMBED_MODE = new URLSearchParams(window.location.search).get("embed") === "1";
const CONDITION_TYPES = [
  { value: "always", label: "总是执行" },
  { value: "exists", label: "元素存在才执行" },
  { value: "not_exists", label: "元素不存在才执行" },
  { value: "page_is", label: "当前页面等于" },
  { value: "page_contains", label: "当前页面包含" },
];

const outputEl = document.querySelector("#output");
const outputPanel = document.querySelector(".output");
const toggleOutputBtn = document.querySelector("#toggleOutputBtn");
const runtimeCasesEl = document.querySelector("#runtimeCases");
const runtimeDetailEl = document.querySelector("#runtimeDetail");
const runtimePaginationEl = document.querySelector("#runtimePagination");
const runtimePageSizeEl = document.querySelector("#runtimePageSize");
const runtimeIterationFilterEl = document.querySelector("#runtimeIterationFilter");
const runtimePrevBtn = document.querySelector("#runtimePrevBtn");
const runtimeNextBtn = document.querySelector("#runtimeNextBtn");
const iterationListEl = document.querySelector("#iterationList");
const iterationPaginationEl = document.querySelector("#iterationsPagination");
const iterationPageSizeEl = document.querySelector("#iterationsPageSize");
const iterationPrevBtn = document.querySelector("#iterationsPrevBtn");
const iterationNextBtn = document.querySelector("#iterationsNextBtn");
const iterationExecutionTargetEl = document.querySelector("#iterationExecutionTarget");
const runtimeExecutionTargetHint = document.querySelector("#runtimeExecutionTargetHint");
const deleteIterationDialog = document.querySelector("#deleteIterationDialog");
const deleteIterationNameEl = document.querySelector("#deleteIterationName");
const deleteIterationCaseCountEl = document.querySelector("#deleteIterationCaseCount");
const confirmDeleteIterationBtn = document.querySelector("#confirmDeleteIterationBtn");
const cancelDeleteIterationBtn = document.querySelector("#cancelDeleteIterationBtn");
const closeDeleteIterationDialogBtn = document.querySelector("#closeDeleteIterationDialogBtn");


const newIterationBtn = document.querySelector("#newIterationBtn");
const refreshIterationsBtn = document.querySelector("#refreshIterationsBtn");
const runJobsEl = document.querySelector("#runJobs");
const reportListEl = document.querySelector("#reportList");
const publicActionListEl = document.querySelector("#publicActionListContainer");
const publicActionSearch = document.querySelector("#publicActionSearch");
const publicActionPageFilter = document.querySelector("#publicActionPageFilter");
const publicActionPageSizeEl = document.querySelector("#publicActionPageSize");
const publicActionPaginationEl = document.querySelector("#publicActionPagination");
const publicActionPrevBtn = document.querySelector("#publicActionPrevBtn");
const publicActionNextBtn = document.querySelector("#publicActionNextBtn");
const publicActionDraftForm = document.querySelector("#publicActionDraftForm");
const publicActionStepsEl = document.querySelector("#publicActionSteps");
const publicActionStepTemplate = document.querySelector("#publicActionStepTemplate");
const publicActionStepCountEl = document.querySelector("#publicActionStepCount");
const publicActionsTitle = document.querySelector("#publicActionsTitle");
const publicActionsHint = document.querySelector("#publicActionsHint");
const savePublicActionBtn = document.querySelector("#savePublicActionBtn");
const cancelPublicActionEditBtn = document.querySelector("#cancelPublicActionEditBtn");
let deleteIterationDialogResolve = null;
let deleteIterationPreviousFocus = null;

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

function stripBasePath(path) {
  path = String(path || "/");
  if (APP_BASE_PATH && path === APP_BASE_PATH) return "/";
  if (APP_BASE_PATH && path.startsWith(`${APP_BASE_PATH}/`)) {
    return path.slice(APP_BASE_PATH.length) || "/";
  }
  return path || "/";
}

function withBasePath(path) {
  // 所有相对站内 API/页面地址统一补上部署前缀，避免前端写死域名。
  path = String(path || "");
  if (!path || path.startsWith("#") || /^[a-z][a-z0-9+.-]*:/i.test(path)) return path;
  if (!path.startsWith("/")) return path;
  if (APP_BASE_PATH && (path === APP_BASE_PATH || path.startsWith(`${APP_BASE_PATH}/`))) return path;
  return `${APP_BASE_PATH}${path}` || path;
}

function appUrl(path) {
  const [rawPath, hash = ""] = String(path || "").split("#");
  const [pathname, query = ""] = rawPath.split("?");
  const params = new URLSearchParams(query);
  if (EMBED_MODE && !params.has("embed")) params.set("embed", "1");
  const nextQuery = params.toString();
  return `${withBasePath(pathname)}${nextQuery ? `?${nextQuery}` : ""}${hash ? `#${hash}` : ""}`;
}

function applyShellMode() {
  document.body.classList.toggle("embed-mode", EMBED_MODE);
  document.querySelectorAll('a[href^="/"]').forEach((link) => {
    link.setAttribute("href", appUrl(link.getAttribute("href")));
  });
}

function log(message) {
  const now = new Date().toLocaleTimeString();
  outputEl.textContent += `[${now}] ${message}\n`;
  outputEl.scrollTop = outputEl.scrollHeight;
}

function setOutputExpanded(expanded) {
  outputPanel?.classList.toggle("output-collapsed", !expanded);
  if (toggleOutputBtn) {
    toggleOutputBtn.textContent = expanded ? "收起" : "展开";
  }
}

async function api(path, options = {}) {
  // 前端所有 API 请求都经过这里：统一补路径、解析 JSON 和抛出后端错误。
  const response = await fetch(withBasePath(path), {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function optionList(values, selected) {
  return values
    .map((value) => `<option value="${escapeHtml(value)}" ${value === selected ? "selected" : ""}>${escapeHtml(value || "-")}</option>`)
    .join("");
}

function fillSelect(select, values, selected) {
  select.innerHTML = optionList(values, selected);
}

function fillConditionTypeSelect(select, selected = "always") {
  select.innerHTML = CONDITION_TYPES
    .map((item) => `<option value="${item.value}" ${item.value === selected ? "selected" : ""}>${item.label}</option>`)
    .join("");
}

function conditionText(step = {}) {
  const type = step.condition_type || "always";
  if (!type || type === "always") return "总是执行";

  const label = (CONDITION_TYPES.find((item) => item.value === type) || {}).label || type;
  const locatorMethod = step.condition_locator_method || step.locator_method || "";
  const locatorValue = step.condition_locator_value || step.locator_value || "";
  const locatorText = [
    locatorMethod,
    locatorValue,
  ].filter(Boolean).join(":");
  const optionsText = step.condition_options ? ` (${step.condition_options})` : "";
  return [label, locatorText || locatorValue || ""].filter(Boolean).join("：") + optionsText;
}

function allowedErrorsText(value) {
  if (!value) return "";
  if (Array.isArray(value)) return value.filter(Boolean).join("|");
  return String(value);
}

function apiErrorPolicyText(item = {}) {
  const mode = item.api_error_check_mode || "normal";
  if (mode === "allow_list") {
    const allowed = allowedErrorsText(item.allowed_errors);
    return allowed ? `接口白名单：${allowed}` : "接口白名单：未填写";
  }
  return "接口错误：正常检查";
}

function apiErrorModeText(item = {}) {
  const mode = item.api_error_check_mode || "normal";
  if (mode === "allow_list") return "白名单放行";
  return "正常检查";
}

function iterationText(item = {}) {
  const name = item.iteration_name || "";
  const code = item.iteration_code || "";
  if (name && code) return `${name} (${code})`;
  return name || code || "未分配";
}

function ignoredApiText(item = {}) {
  if ((item.api_error_check_mode || "normal") !== "allow_list") return "-";
  return allowedErrorsText(item.allowed_errors) || "未填写";
}

function currentPath() {
  return stripBasePath(window.location.pathname).replace(/\/+$/, "") || "/";
}

function routeView() {
  const path = currentPath();
  if (["/public-actions", "/public-actions/new", "/public-actions/edit"].includes(path)) return "publicActions";
  if (path === "/iterations") return "iterations";
  if (path === "/" || path === "/cases") return "runtime";
  return "";
}

function syncRouteMode() {
  const path = currentPath();
  const isPublicActionForm =
    state.activeView === "publicActions" &&
    ["/public-actions/new", "/public-actions/edit"].includes(path);
  const isPublicActionEdit = state.activeView === "publicActions" && path === "/public-actions/edit";

  document.body.classList.toggle("public-action-new-route", isPublicActionForm);
  if (publicActionsTitle) {
    publicActionsTitle.textContent = isPublicActionEdit
      ? "编辑公共动作"
      : isPublicActionForm
        ? "封装公共动作"
        : "公共动作库";
  }
  if (publicActionsHint) {
    publicActionsHint.textContent = isPublicActionEdit
      ? "读取 mt_public_actions / mt_public_action_steps 后更新"
      : isPublicActionForm
        ? "保存到 mt_public_actions / mt_public_action_steps，供用例步骤复用"
        : "来源：数据库公共动作配置";
  }
}

function setPublicActionDraftMode(publicActionId = "", enabled = 1) {
  state.publicActionEditId = String(publicActionId || "");
  state.publicActionEditEnabled = Number(enabled) === 0 ? 0 : 1;
  if (savePublicActionBtn) {
    savePublicActionBtn.textContent = state.publicActionEditId ? "保存编辑" : "保存到数据库";
  }
  if (cancelPublicActionEditBtn) {
    cancelPublicActionEditBtn.classList.toggle("hidden", !state.publicActionEditId);
  }
}

function ensurePublicActionPageOption(pageCode, pageTitle = "") {
  const select = publicActionDraftForm.target;
  pageCode = String(pageCode || "").trim();
  if (!pageCode) return;
  const exists = [...select.options].some((option) => option.value === pageCode);
  if (exists) return;

  const option = document.createElement("option");
  option.value = pageCode;
  option.textContent = pageTitle ? `${pageTitle} - ${pageCode}` : pageCode;
  option.dataset.pageName = pageTitle || pageCode;
  select.appendChild(option);
}

function resetPublicActionDraft() {
  publicActionDraftForm.reset();
  publicActionStepsEl.innerHTML = "";
  setPublicActionDraftMode("", 1);
  ensurePublicActionSteps();
}

function switchView(view) {
  state.activeView = view;
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.view === view);
  });
  document.querySelectorAll(".view-panel").forEach((panel) => {
    panel.classList.remove("active");
  });
  const activePanel = document.querySelector(`#${view}View`);
  if (!activePanel) return;
  activePanel.classList.add("active");

  if (view === "runtime") loadRuntimeCases();
  if (view === "publicActions") renderPublicActionLibrary();
  if (view === "iterations") loadIterations();
  if (view === "runs") loadRuns();
  syncRouteMode();
}

function iterationStatusText(status) {
  return {
    planning: "规划中",
    active: "进行中",
    completed: "已完成",
    archived: "已归档",
  }[status] || status || "-";
}

function iterationPeriodText(iteration = {}) {
  const start = iteration.start_date || "";
  const end = iteration.end_date || "";
  if (start && end) return `${start} 至 ${end}`;
  return start || end || "未设置";
}

function savedIterationExecutionTarget() {
  try {
    return (
      window.localStorage.getItem(EXECUTION_TARGET_STORAGE_KEY) ||
      window.localStorage.getItem(LEGACY_EXECUTION_TARGET_STORAGE_KEY) ||
      ""
    );
  } catch (_) {
    return "";
  }
}

function saveIterationExecutionTarget(agentId) {
  try {
    if (agentId) {
      window.localStorage.setItem(EXECUTION_TARGET_STORAGE_KEY, agentId);
    } else {
      window.localStorage.removeItem(EXECUTION_TARGET_STORAGE_KEY);
    }
    // 升级后不再使用旧键，避免两个位置保存不同选择。
    window.localStorage.removeItem(LEGACY_EXECUTION_TARGET_STORAGE_KEY);
  } catch (_) {
    // 浏览器禁用本地存储时，仍允许用户在当前页面选择执行位置。
  }
}

function currentExecutionTargetId() {
  return state.executionTargetId || savedIterationExecutionTarget();
}

function iterationExecutionTargetText(agentId) {
  if (!agentId) return state.centerExecutionEnabled ? "中心机" : "请选择执行机";
  const agent = state.executionAgents.find((item) => item.agent_id === agentId);
  return agent?.agent_name || agentId;
}

function renderExecutionTargetHints() {
  if (!runtimeExecutionTargetHint) return;
  const agentId = currentExecutionTargetId();
  runtimeExecutionTargetHint.textContent = `当前执行位置：${iterationExecutionTargetText(agentId)}`;
  runtimeExecutionTargetHint.title = agentId
    ? `当前任务会派发给执行机 ${agentId}`
    : state.centerExecutionEnabled
      ? "当前任务由中心机执行"
      : "中心机执行已禁用，请到需求迭代页选择执行机";
}

function fillIterationExecutionTargets() {
  if (!iterationExecutionTargetEl) return;

  const currentValue = currentExecutionTargetId() || iterationExecutionTargetEl.value;
  iterationExecutionTargetEl.innerHTML = "";

  if (state.centerExecutionEnabled) {
    const centerOption = document.createElement("option");
    centerOption.value = "";
    centerOption.textContent = "中心机";
    iterationExecutionTargetEl.appendChild(centerOption);
  } else {
    const placeholderOption = document.createElement("option");
    placeholderOption.value = "";
    placeholderOption.textContent = "请选择执行机";
    placeholderOption.disabled = true;
    iterationExecutionTargetEl.appendChild(placeholderOption);
  }

  if (state.remoteAgentsEnabled) {
    for (const agent of state.executionAgents) {
      if (!agent.agent_id || Number(agent.enabled) === 0) continue;
      const option = document.createElement("option");
      option.value = agent.agent_id;
      option.textContent = agent.agent_name
        ? `${agent.agent_name} (${agent.agent_id})`
        : agent.agent_id;
      iterationExecutionTargetEl.appendChild(option);
    }
  }

  const exists = [...iterationExecutionTargetEl.options].some(
    (option) => option.value === currentValue
  );
  const selectedAgentId = exists ? currentValue : "";
  iterationExecutionTargetEl.value = selectedAgentId;
  state.executionTargetId = selectedAgentId;
  if (selectedAgentId !== savedIterationExecutionTarget()) {
    saveIterationExecutionTarget(selectedAgentId);
  }
  renderExecutionTargetHints();
}

async function loadExecutionAgents() {
  try {
    const data = await api("/api/agents");
    state.remoteAgentsEnabled = Boolean(data.remote_agents_enabled);
    state.centerExecutionEnabled = data.center_execution_enabled !== false;
    state.executionAgents = data.agents || [];
  } catch (error) {
    // 临时读取失败时不清掉浏览器中的远程选择，避免网络波动把任务意外改派到中心机。
    state.remoteAgentsEnabled = false;
    state.executionAgents = [];
    renderExecutionTargetHints();
    log(`读取执行机列表失败，暂时保留当前执行位置: ${error.message}`);
    return;
  }
  fillIterationExecutionTargets();
}

function renderIterations() {
  if (!iterationListEl) return;
  iterationListEl.innerHTML = "";
  if (!state.iterations.length) {
    iterationListEl.innerHTML = `<div class="iteration-empty">暂无迭代，请点击“新建迭代”添加。</div>`;
    renderIterationsPagination();
    return;
  }


  for (const iteration of state.iterations) {
    const node = document.createElement("div");
    node.className = "iteration-item";
    node.innerHTML = `
      <div class="iteration-code">${escapeHtml(iteration.iteration_code || "-")}</div>
      <div>
        <div class="iteration-name">${escapeHtml(iteration.iteration_name || "-")}</div>
        <div class="iteration-meta">${escapeHtml(iteration.description || "")}</div>
      </div>
      <span class="iteration-status ${escapeHtml(iteration.status || "")}">${escapeHtml(iterationStatusText(iteration.status))}</span>
      <div class="iteration-meta">${escapeHtml(iterationPeriodText(iteration))}</div>
      <div class="iteration-meta">${escapeHtml(iteration.case_count ?? 0)}</div>
      <div class="iteration-meta">${escapeHtml(iteration.updated_at || "-")}</div>
      <div class="toolbar-actions">
        <a class="btn btn-secondary btn-sm" data-action="edit" href="${appUrl(`/iterations/edit?iteration_id=${encodeURIComponent(iteration.iteration_id)}`)}">编辑</a>
        <button class="btn btn-danger btn-sm" type="button" data-action="delete">删除</button>
        <button class="btn btn-primary btn-sm" type="button" data-action="run">执行</button>
      </div>
    `;
    node.querySelector('[data-action="run"]').addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        await runIteration(iteration);
      } catch (error) {
        log(`执行迭代失败: ${error.message}`);
      } finally {
        button.disabled = false;
      }
    });
    node.querySelector('[data-action="delete"]').addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        await deleteIteration(iteration);
      } catch (error) {
        log(`删除迭代失败: ${error.message}`);
      } finally {
        button.disabled = false;
      }
    });
    iterationListEl.appendChild(node);
  }
  renderIterationsPagination();
}

async function loadIterations() {
  const pagination = state.iterationPagination;
  const params = new URLSearchParams({
    page: pagination.page || 1,
    page_size: iterationPageSizeEl?.value || pagination.page_size || DEFAULT_ITERATION_PAGE_SIZE,
  });
  const data = await api(`/api/iterations?${params.toString()}`);
  state.iterations = data.iterations || [];
  state.iterationPagination = data.pagination || {
    page: 1,
    page_size: DEFAULT_ITERATION_PAGE_SIZE,
    total: state.iterations.length,
    total_pages: 1,
  };
  await loadExecutionAgents();
  renderIterations();
}

function closeDeleteIterationDialog(confirmed = false) {
  if (!deleteIterationDialog) return;
  deleteIterationDialog.classList.add("hidden");
  deleteIterationDialog.setAttribute("aria-hidden", "true");
  document.body.classList.remove("dialog-open");

  const resolve = deleteIterationDialogResolve;
  deleteIterationDialogResolve = null;
  resolve?.(confirmed);

  if (deleteIterationPreviousFocus instanceof HTMLElement) {
    deleteIterationPreviousFocus.focus();
  }
  deleteIterationPreviousFocus = null;
}

function confirmIterationDeletion(iteration) {
  if (!deleteIterationDialog) return Promise.resolve(false);
  if (deleteIterationDialogResolve) {
    closeDeleteIterationDialog(false);
  }

  const iterationName =
    iteration.iteration_name ||
    iteration.iteration_code ||
    iteration.iteration_id;
  const caseCount = Number(iteration.case_count || 0);

  deleteIterationNameEl.textContent = iterationName;
  deleteIterationCaseCountEl.textContent = `${caseCount} 条`;
  deleteIterationPreviousFocus = document.activeElement;
  deleteIterationDialog.classList.remove("hidden");
  deleteIterationDialog.setAttribute("aria-hidden", "false");
  document.body.classList.add("dialog-open");

  return new Promise((resolve) => {
    deleteIterationDialogResolve = resolve;
    window.requestAnimationFrame(() => confirmDeleteIterationBtn?.focus());
  });
}

async function deleteIteration(iteration) {
  const iterationId = iteration.iteration_id;
  const iterationName =
    iteration.iteration_name ||
    iteration.iteration_code ||
    iterationId;

  const confirmed = await confirmIterationDeletion(iteration);

  if (!confirmed) return;

  const response = await api(
    "/api/iteration/delete",
    {
      method: "POST",
      body: JSON.stringify({
        iteration_id: iterationId,
      }),
    }
  );

  log(
    `迭代已删除：${iterationName}，${response.result.msg}`
  );

  await loadIterations();
  await loadOptions();
  await loadRuntimeCases();
}


function actionParamNames(item) {
  return (item.params || []).map((param) => param.name);
}

function actionDisplayName(item) {
  return (item.action_name || item.title || item.desc || "").trim() || item.action || `#${item.id}`;
}

function publicActionId(item = {}) {
  return String(item.public_action_id || item.id || item.action || "");
}

function firstPublicActionStep(item = {}) {
  const steps = item.steps || [];
  return steps[0] || item.first_step || {};
}

function publicActionStepSummary(item = {}) {
  const steps = item.steps || [];
  if (!steps.length) return "";
  return steps
    .slice(0, 3)
    .map((step) => {
      const actionText = [step.step_action, step.locator_method, step.locator_value].filter(Boolean).join(" ");
      const condition = conditionText(step);
      return condition === "总是执行" ? actionText : `${actionText} [${condition}]`;
    })
    .join(" / ");
}

function publicActionSearchText(item) {
  return [
    item.action,
    item.action_name,
    item.desc,
    item.description,
    item.page_code,
    item.page_title,
    item.target,
    item.method,
    ...(item.aliases || []),
    ...(item.steps || []).flatMap((step) => [
      step.step_action,
      step.locator_method,
      step.locator_value,
      step.locator_options,
      step.step_value,
      step.condition_type,
      step.condition_locator_method,
      step.condition_locator_value,
      step.condition_options,
      step.remark,
    ]),
    ...actionParamNames(item),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function filteredPublicStepActions() {
  const keyword = (publicActionSearch?.value || "").trim().toLowerCase();
  const pageCode = (publicActionPageFilter?.value || "").trim();
  let actions = state.options.public_step_actions || [];

  // 后端已经支持 keyword/page_code 查询；这里再过滤一次，作为前端兜底。
  // 好处是首次全量加载、或者接口没有带筛选条件时，页面搜索仍然能立即生效。
  if (pageCode) {
    actions = actions.filter((item) => String(item.page_code || item.target || "") === pageCode);
  }
  if (!keyword) return actions;
  return actions.filter((item) => publicActionSearchText(item).includes(keyword));
}

function renderPublicActionLibrary() {
  const actions = filteredPublicStepActions();
  publicActionListEl.innerHTML = "";

  if (!actions.length) {
    publicActionListEl.innerHTML = `<div class="hint">暂无公共动作，或没有匹配的搜索结果。</div>`;
    return;
  }

  for (const item of actions) {
    const params = actionParamNames(item);
    const stepCount = (item.steps || []).length;
    const stepSummary = publicActionStepSummary(item);
    const pageTitle = item.page_title || item.source_group || item.target || item.page_code || "";
    const row = document.createElement("div");
    row.className = "public-action-item";
    row.innerHTML = `
      <div>
        <strong>${escapeHtml(pageTitle)}</strong>
        <span>${escapeHtml(item.page_code || item.target || "")}</span>
      </div>
      <div>
        <strong>${escapeHtml(actionDisplayName(item))}</strong>
        <span>ID: ${escapeHtml(publicActionId(item))}</span>
      </div>
      <div>${escapeHtml(stepCount ? `${stepCount} step` : "")}</div>
      <div>${escapeHtml(stepSummary)}</div>
      <div>${params.length ? escapeHtml(params.join(", ")) : "-"}</div>
      <div class="toolbar-actions">
        <a class="btn btn-secondary btn-sm" href="${appUrl(`/public-actions/edit?public_action_id=${encodeURIComponent(publicActionId(item))}`)}">编辑</a>
      </div>
    `;
    publicActionListEl.appendChild(row);
  }
}

function renderPublicActionPagination() {
  const pagination = state.publicActionPagination;
  if (!publicActionPaginationEl || !publicActionPrevBtn || !publicActionNextBtn) return;

  publicActionPaginationEl.textContent = `第 ${pagination.page} / ${pagination.total_pages} 页，共 ${pagination.total} 条`;
  publicActionPrevBtn.disabled = pagination.page <= 1;
  publicActionNextBtn.disabled = pagination.page >= pagination.total_pages;
  publicActionPrevBtn.classList.toggle("disabled", publicActionPrevBtn.disabled);
  publicActionNextBtn.classList.toggle("disabled", publicActionNextBtn.disabled);
}

const LOCATOR_HELP = {
  text: {
    value: "文本，例如：我的 或 {goods_name}",
    options: "tag=view,index=2,parent=class:父级class",
  },
  class: {
    value: "class，多个用 | 分隔，例如：buy-agree-wrap|user-tips",
    options: "class_names=追加class,tag=view,index=2,exact=false,parent=class:父级class",
  },
  class_text: {
    value: "文本|class，例如：{goods_num}|bottom-button",
    options: "class_names=bottom-button,text_tag=text,index=2,exact=false,parent=class:父级class",
  },
  src: {
    value: "图片 src 片段，例如：https://xxx.png",
    options: "tag=image,index=1,parent=class:父级class",
  },
  xpath: {
    value: "完整 XPath，例如：//view[contains(text(), '确认')]",
    options: "xpath 不需要高级参数",
  },
  candidates: {
    value: "候选定位，例如：class:option|right || class:CardItem--option|CardItem--right",
    options: "timeout=2,exact=false,parent=class:父级class",
  },
  "": {
    value: "open_url 填页面路径；wait 填附加值秒数",
    options: "无",
  },
};

function refreshStepHints(node) {
  const locatorMethod = stepUsesCandidates(node)
    ? "candidates"
    : node.querySelector('[name="locator_method"]').value;
  const help = LOCATOR_HELP[locatorMethod] || LOCATOR_HELP[""];
  const locatorValue = node.querySelector('[name="locator_value"]');
  const locatorOptions = node.querySelector('[name="locator_options"]');

  locatorValue.placeholder = help.value;
  locatorValue.title = help.value;
  locatorOptions.placeholder = help.options;
  locatorOptions.title = help.options;
}

function locatorMethodOptions(selected = "") {
  const methods = (state.options.locator_methods || []).filter((method) => method !== "candidates");
  if (selected && selected !== "candidates" && !methods.includes(selected)) {
    methods.push(selected);
  }
  return methods;
}

function isCandidateStep(step = {}) {
  return (step.locator_method || "") === "candidates";
}

function stepUsesCandidates(node) {
  return Boolean(node.querySelector('[name="use_candidates"]')?.checked);
}

function setCandidateMode(node, enabled) {
  const checkbox = node.querySelector('[name="use_candidates"]');
  const locatorMethod = node.querySelector('[name="locator_method"]');
  if (checkbox) checkbox.checked = enabled;
  locatorMethod.disabled = enabled;
  if (!enabled && (!locatorMethod.value || locatorMethod.value === "candidates")) {
    locatorMethod.value = "text";
  }
  refreshStepHints(node);
}

function publicActionStepActions() {
  return state.options.step_actions || [];
}

function createPublicActionStep(step = {}) {
  const node = publicActionStepTemplate.content.firstElementChild.cloneNode(true);
  const useCandidates = isCandidateStep(step);
  node.dataset.childPublicActionId = step.child_public_action_id || "";
  fillSelect(node.querySelector('[name="step_action"]'), publicActionStepActions(), step.step_action || "click");
  fillSelect(
    node.querySelector('[name="locator_method"]'),
    locatorMethodOptions(useCandidates ? "" : step.locator_method),
    useCandidates ? "text" : step.locator_method || "text"
  );
  fillConditionTypeSelect(node.querySelector('[name="condition_type"]'), step.condition_type || "always");
  fillSelect(
    node.querySelector('[name="condition_locator_method"]'),
    locatorMethodOptions(step.condition_locator_method),
    step.condition_locator_method || ""
  );
  node.querySelector('[name="locator_value"]').value = step.locator_value || "";
  node.querySelector('[name="locator_options"]').value = step.locator_options || "";
  node.querySelector('[name="step_value"]').value = step.step_value || "";
  node.querySelector('[name="condition_locator_value"]').value = step.condition_locator_value || "";
  node.querySelector('[name="condition_options"]').value = step.condition_options || "";
  node.querySelector('[name="remark"]').value = step.remark || "";
  node.querySelector('[name="locator_method"]').addEventListener("change", () => refreshStepHints(node));
  node.querySelector('[name="use_candidates"]').addEventListener("change", (event) => {
    setCandidateMode(node, event.target.checked);
  });
  node.querySelectorAll("button[data-action]").forEach((button) => {
    button.addEventListener("click", () => handlePublicActionStepAction(node, button.dataset.action));
  });
  setCandidateMode(node, useCandidates);
  publicActionStepsEl.appendChild(node);
  refreshPublicActionStepIndexes();
}

function refreshPublicActionStepIndexes() {
  [...publicActionStepsEl.children].forEach((node, index) => {
    node.querySelector(".step-index").textContent = index + 1;
  });
  if (publicActionStepCountEl) {
    publicActionStepCountEl.textContent = String(publicActionStepsEl.children.length);
  }
}

function handlePublicActionStepAction(node, action) {
  if (action === "remove") {
    node.remove();
  }
  if (action === "up" && node.previousElementSibling) {
    publicActionStepsEl.insertBefore(node, node.previousElementSibling);
  }
  if (action === "down" && node.nextElementSibling) {
    publicActionStepsEl.insertBefore(node.nextElementSibling, node);
  }
  if (!publicActionStepsEl.children.length) {
    createPublicActionStep({ step_action: "click", locator_method: "text" });
    return;
  }
  refreshPublicActionStepIndexes();
}

function getPublicActionStepData() {
  return [...publicActionStepsEl.children].map((node, index) => ({
    step_order: index + 1,
    step_action: node.querySelector('[name="step_action"]').value,
    locator_method: stepUsesCandidates(node) ? "candidates" : node.querySelector('[name="locator_method"]').value,
    locator_value: node.querySelector('[name="locator_value"]').value.trim(),
    locator_options: node.querySelector('[name="locator_options"]').value.trim(),
    step_value: node.querySelector('[name="step_value"]').value.trim(),
    condition_type: node.querySelector('[name="condition_type"]').value,
    condition_locator_method: node.querySelector('[name="condition_locator_method"]').value,
    condition_locator_value: node.querySelector('[name="condition_locator_value"]').value.trim(),
    condition_options: node.querySelector('[name="condition_options"]').value.trim(),
    child_public_action_id: node.dataset.childPublicActionId || "",
    remark: node.querySelector('[name="remark"]').value.trim(),
  }));
}

function ensurePublicActionSteps() {
  if (!publicActionStepsEl.children.length) {
    createPublicActionStep({ step_action: "click", locator_method: "text" });
  }
}

function fillPublicActionDraftTargets() {
  const select = publicActionDraftForm.target;
  const pageOptions = state.options.page_options || [];
  select.innerHTML = "";
  for (const page of pageOptions) {
    const option = document.createElement("option");
    const pageCode = page.page_code || "";
    const pageTitle = page.page_title || "";
    option.value = pageCode;
    option.textContent = pageTitle ? `${pageTitle} - ${pageCode}` : pageCode;
    option.dataset.pageName = pageTitle;
    select.appendChild(option);
  }
}

function fillPublicActionPageFilter() {
  if (!publicActionPageFilter) return;
  const selected = publicActionPageFilter.value || "";
  const pageOptions = state.options.page_options || [];
  publicActionPageFilter.innerHTML = `<option value="">全部页面</option>`;
  for (const page of pageOptions) {
    const option = document.createElement("option");
    const pageCode = page.page_code || "";
    const pageTitle = page.page_title || "";
    option.value = pageCode;
    option.textContent = pageTitle ? `${pageTitle} - ${pageCode}` : pageCode;
    publicActionPageFilter.appendChild(option);
  }
  publicActionPageFilter.value = selected;
}

function selectedPublicActionPage() {
  const select = publicActionDraftForm.target;
  const option = select.options[select.selectedIndex];
  const pageCode = String(select.value || "").trim();
  const label = String(option?.textContent || "").split(" - ")[0].trim();
  return {
    page_code: pageCode,
    page_title: option?.dataset.pageName || label || pageCode,
  };
}

function placeholderNames(value) {
  const names = [];
  const pattern = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g;
  let match = pattern.exec(value || "");
  while (match) {
    if (!names.includes(match[1])) names.push(match[1]);
    match = pattern.exec(value || "");
  }
  return names;
}

function publicActionDraftData() {
  const data = new FormData(publicActionDraftForm);
  const page = selectedPublicActionPage();
  const actionName = String(data.get("action_name") || "").trim();
  const desc = String(data.get("desc") || "").trim();
  const aliases = String(data.get("aliases") || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const steps = getPublicActionStepData();

  if (!page.page_code || !actionName) {
    throw new Error("所属页面、公共动作名称不能为空");
  }
  if (!steps.length) {
    throw new Error("公共动作至少需要一个动作步骤");
  }
  for (const [index, step] of steps.entries()) {
    if (!step.step_action) throw new Error(`第 ${index + 1} 步缺少动作`);
    if ([
      "click",
      "optional_click",
      "click_first",
      "wait_element",
      "click_if_text",
      "random_click",
      "random_click_until_not_exists",
      "retry_click_until_not_exists",
      "input",
      "element_exists",
      "get_text",
    ].includes(step.step_action) && !step.locator_value) {
      throw new Error(`第 ${index + 1} 步缺少定位值`);
    }
    if (["exists", "not_exists"].includes(step.condition_type)) {
      const hasConditionLocator = step.condition_locator_value || step.locator_value;
      const hasConditionMethod = step.condition_locator_method || step.locator_method;
      if (!hasConditionLocator || !hasConditionMethod) {
        throw new Error(`第 ${index + 1} 步的执行条件缺少条件定位`);
      }
    }
    if (["page_is", "page_contains"].includes(step.condition_type) && !step.condition_locator_value) {
      throw new Error(`第 ${index + 1} 步的页面条件缺少条件定位值`);
    }
  }

  const paramNames = [];
  for (const step of steps) {
    for (const value of [
      step.locator_value,
      step.locator_options,
      step.step_value,
      step.condition_locator_value,
      step.condition_options,
    ]) {
      for (const name of placeholderNames(value)) {
        if (!paramNames.includes(name)) paramNames.push(name);
      }
    }
  }

  return {
    public_action_id: state.publicActionEditId,
    id: state.publicActionEditId,
    page_code: page.page_code,
    page_title: page.page_title,
    action_name: actionName,
    description: desc,
    aliases,
    params: paramNames.map((name) => ({ name, required: true })),
    steps,
    enabled: state.publicActionEditId ? state.publicActionEditEnabled : 1,
  };
}

function setPublicActionDraftData(action) {
  ensurePublicActionPageOption(action.page_code, action.page_title);
  publicActionDraftForm.target.value = action.page_code || "";
  publicActionDraftForm.action_name.value = action.action_name || "";
  publicActionDraftForm.desc.value = action.description || action.desc || "";
  publicActionDraftForm.aliases.value = (action.aliases || []).join(",");
  publicActionStepsEl.innerHTML = "";
  const steps = action.steps && action.steps.length
    ? action.steps
    : [{ step_action: "click", locator_method: "text" }];
  steps.forEach(createPublicActionStep);
  setPublicActionDraftMode(action.public_action_id || action.id, action.enabled);
}

async function loadPublicActionForEdit(publicActionId) {
  if (!publicActionId) throw new Error("public_action_id 不能为空");
  const data = await api(`/api/public_action_edit?public_action_id=${encodeURIComponent(publicActionId)}`);
  setPublicActionDraftData(data.public_action);
  switchView("publicActions");
  log(`已加载公共动作编辑: ${data.public_action.action_name || publicActionId}`);
  return data.public_action;
}

async function savePublicActionDraft() {
  const payload = publicActionDraftData();
  const isEdit = Boolean(state.publicActionEditId);
  const response = await api(isEdit ? "/api/public_action_edit" : "/api/public_action", {
    method: isEdit ? "PUT" : "POST",
    body: JSON.stringify(payload),
  });
  log(`${isEdit ? "公共动作已更新" : "公共动作已保存"}: ${response.result.action_name}`);
  const savedPublicActionId = response.result.public_action_id || state.publicActionEditId;
  await loadOptions();
  if (isEdit && savedPublicActionId) {
    await loadPublicActionForEdit(savedPublicActionId);
  }
  return response.result;
}

function renderRuntimeCases() {
  runtimeCasesEl.innerHTML = "";
  if (!state.runtimeCases.length) {
    runtimeCasesEl.innerHTML = `<div class="hint">暂无正式用例，请点击“新建”添加用例。</div>`;
    renderRuntimePagination();
    return;
  }

  for (const item of state.runtimeCases) {
    const modeText = item.case_mode === "steps"
      ? `step · ${item.steps_count || 0} 步`
      : `不支持的模式 · ${item.case_mode || ""}`;
    const isEnabled = Number(item.enabled) !== 0;
    const statusText = isEnabled ? "启用" : "禁用";
    const node = document.createElement("div");
    node.className = "runtime-item";
    node.innerHTML = `
      <div class="runtime-main">
        <span class="runtime-title">${escapeHtml(item.case_id || "")}</span>
        <span class="runtime-meta">${escapeHtml(item.title || "")}</span>
      </div>
      <div class="runtime-meta">${escapeHtml(iterationText(item))}</div>
      <div class="runtime-meta">${escapeHtml(modeText)}</div>
      <div class="runtime-meta">${escapeHtml(item.inputs || "-")}</div>
      <div class="runtime-meta">${escapeHtml(apiErrorModeText(item))}</div>
      <div class="runtime-meta runtime-api-list">${escapeHtml(ignoredApiText(item))}</div>
      <button class="case-enabled-toggle ${isEnabled ? "enabled" : "disabled"}" type="button" data-action="toggle-enabled" aria-pressed="${isEnabled ? "true" : "false"}">
        <span class="toggle-dot"></span>
        <span>${statusText}</span>
      </button>
      <div class="toolbar-actions">
        <a class="btn btn-secondary btn-sm" href="${appUrl(`/cases/edit?case_id=${encodeURIComponent(item.case_id || "")}`)}">编辑</a>
        <button class="btn btn-primary btn-sm ${isEnabled ? "" : "disabled"}" type="button" data-action="run" ${isEnabled ? "" : "disabled"}>执行</button>
      </div>
    `;
    node.querySelector('[data-action="toggle-enabled"]').addEventListener("click", () => toggleRuntimeCaseEnabled(item));
    node.querySelector('[data-action="run"]').addEventListener("click", () => {
      if (Number(item.enabled) === 0) return;
      runCase(item.case_id);
    });
    runtimeCasesEl.appendChild(node);
  }
  renderRuntimePagination();
}

function renderRuntimePagination() {
  const pagination = state.runtimePagination;
  runtimePaginationEl.textContent = `第 ${pagination.page} / ${pagination.total_pages} 页，共 ${pagination.total} 条`;
  runtimePrevBtn.disabled = pagination.page <= 1;
  runtimeNextBtn.disabled = pagination.page >= pagination.total_pages;
  runtimePrevBtn.classList.toggle("disabled", runtimePrevBtn.disabled);
  runtimeNextBtn.classList.toggle("disabled", runtimeNextBtn.disabled);
}


function renderIterationsPagination() {
  if (!iterationPaginationEl || !iterationPrevBtn || !iterationNextBtn) return;
  const pagination = state.iterationPagination;
  iterationPaginationEl.textContent = `第 ${pagination.page} / ${pagination.total_pages} 页，共 ${pagination.total} 条`;
  iterationPrevBtn.disabled = pagination.page <= 1;
  iterationNextBtn.disabled = pagination.page >= pagination.total_pages;
  iterationPrevBtn.classList.toggle("disabled", iterationPrevBtn.disabled);
  iterationNextBtn.classList.toggle("disabled", iterationNextBtn.disabled);
}

function renderRuntimeCaseDetail(caseData) {
  const steps = caseData.steps || [];
  const isEnabled = Number(caseData.enabled) !== 0;
  const stepRows = steps.length
    ? steps.map((step) => `
        <tr>
          <td>${escapeHtml(step.step_order || "")}</td>
          <td>${escapeHtml(step.public_action_id ? `公共动作 #${step.public_action_id}` : step.step_action || "")}</td>
          <td>${escapeHtml(step.locator_method || "")}</td>
          <td>${escapeHtml(step.locator_value || "")}</td>
          <td>${escapeHtml(step.locator_options || "")}</td>
          <td>${escapeHtml(step.step_value || "")}</td>
          <td>${escapeHtml(conditionText(step))}</td>
          <td>${escapeHtml(step.remark || step["备注"] || "")}</td>
        </tr>
      `).join("")
    : `<tr><td colspan="8" class="runtime-empty">该用例没有数据库步骤明细</td></tr>`;

  runtimeDetailEl.classList.remove("hidden");
  runtimeDetailEl.innerHTML = `
    <div class="runtime-detail-header">
      <div>
        <h3>${escapeHtml(caseData.case_id || "")}</h3>
        <p>${escapeHtml(caseData.title || "")}</p>
      </div>
      <div class="toolbar-actions">
        <a class="btn btn-secondary btn-sm" href="${appUrl(`/cases/edit?case_id=${encodeURIComponent(caseData.case_id || "")}`)}">编辑</a>
        <button class="btn btn-primary btn-sm ${isEnabled ? "" : "disabled"}" type="button" data-action="run" ${isEnabled ? "" : "disabled"}>执行</button>
      </div>
    </div>
    <div class="runtime-detail-meta">
      <span>迭代：${escapeHtml(iterationText(caseData))}</span>
      <span>模式：${escapeHtml(caseData.case_mode || "")}</span>
      <span>参数：${escapeHtml(caseData.inputs || "")}</span>
      <span>${escapeHtml(apiErrorPolicyText(caseData))}</span>
      <span>断言：${escapeHtml([caseData.assert_type, caseData.expect_value].filter(Boolean).join(" -> "))}</span>
    </div>
    <div class="runtime-step-table-wrap">
      <table class="runtime-step-table">
        <thead>
          <tr>
            <th>#</th>
            <th>动作</th>
            <th>定位方式</th>
            <th>定位值</th>
            <th>高级参数</th>
            <th>附加值</th>
            <th>执行条件</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>${stepRows}</tbody>
      </table>
    </div>
  `;
  runtimeDetailEl.querySelector('[data-action="run"]').addEventListener("click", () => {
    if (!isEnabled) return;
    runCase(caseData.case_id);
  });
}

async function loadRuntimeCaseDetail(caseId) {
  const data = await api(`/api/runtime_case_detail?case_id=${encodeURIComponent(caseId)}`);
  renderRuntimeCaseDetail(data.case);
}

async function loadRuntimeCases() {
  const pagination = state.runtimePagination;
  const params = new URLSearchParams({
    page: pagination.page || 1,
    page_size: runtimePageSizeEl?.value || pagination.page_size || DEFAULT_RUNTIME_PAGE_SIZE,
  });
  if (runtimeIterationFilterEl?.value) {
    params.set("iteration_id", runtimeIterationFilterEl.value);
  }
  const data = await api(`/api/runtime_cases?${params.toString()}`);
  state.runtimeCases = data.cases || [];
  state.runtimePagination = data.pagination || {
    page: 1,
    page_size: Number(runtimePageSizeEl?.value || DEFAULT_RUNTIME_PAGE_SIZE),
    total: state.runtimeCases.length,
    total_pages: 1,
  };
  renderRuntimeCases();
}

async function toggleRuntimeCaseEnabled(item) {
  const caseId = item.case_id || "";
  if (!caseId) return;

  const nextEnabled = Number(item.enabled) === 0 ? 1 : 0;
  try {
    const response = await api("/api/runtime_case_enabled", {
      method: "POST",
      body: JSON.stringify({
        case_id: caseId,
        enabled: nextEnabled,
      }),
    });
    item.enabled = response.result?.enabled ?? nextEnabled;
    renderRuntimeCases();
    log(`正式用例 ${caseId} 已${Number(item.enabled) === 0 ? "禁用" : "启用"}`);
  } catch (error) {
    log(`更新用例启用状态失败: ${error.message}`);
  }
}

async function loadRuns() {
  const data = await api("/api/run_jobs");
  state.jobs = data.jobs || [];
  state.reports = data.reports || [];
  renderRuns();
}

async function runCase(caseId = "") {
  const agentId = currentExecutionTargetId();
  const response = await api("/api/run_case", {
    method: "POST",
    body: JSON.stringify({
      case_id: caseId,
      agent_id: agentId,
    }),
  });
  log(
    `执行任务已创建: ${response.job.job_id} ${caseId || "全部用例"}，${iterationExecutionTargetText(agentId)}执行`
  );
  switchView("runs");
  startPollingRuns();
}

async function runIteration(iteration) {
  const iterationId = iteration?.iteration_id;
  if (!iterationId) throw new Error("缺少 iteration_id");
  const agentId = currentExecutionTargetId();
  const response = await api("/api/run_iteration", {
    method: "POST",
    body: JSON.stringify({
      iteration_id: iterationId,
      agent_id: agentId,
    }),
  });
  const name = iteration.iteration_name || iteration.iteration_code || iterationId;
  log(
    `迭代执行任务已创建: ${response.job.job_id} ${name}，${iterationExecutionTargetText(agentId)}执行`
  );
  switchView("runs");
  startPollingRuns();
}

function startPollingRuns() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    try {
      await loadRuns();
      const hasRunning = state.jobs.some((job) => ["queued", "running"].includes(job.status));
      if (!hasRunning) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
      }
    } catch (error) {
      log(`刷新执行记录失败: ${error.message}`);
    }
  }, 2500);
}

function statusText(status) {
  const map = {
    queued: "排队中",
    running: "执行中",
    success: "成功",
    failed: "失败",
  };
  return map[status] || status || "-";
}

function runResultText(item) {
  const summary = item.result_summary || {};
  const hasSummary = summary.total !== undefined || summary.passed !== undefined || summary.failed !== undefined;
  if (hasSummary) {
    const total = summary.total ?? 0;
    const passed = summary.passed ?? 0;
    const failed = summary.failed ?? 0;
    return `总数 ${total} / 通过 ${passed} / 失败 ${failed}`;
  }
  if (item.total !== undefined || item.passed !== undefined || item.failed !== undefined) {
    return `总数 ${item.total || 0} / 通过 ${item.passed || 0} / 失败 ${item.failed || 0}`;
  }
  if (item.returncode !== undefined && item.returncode !== null && item.returncode !== "") {
    return `returncode=${item.returncode}`;
  }
  return "-";
}

function caseText(item) {
  if (item.iteration_id) {
    const name = item.iteration_name || item.iteration_code || `#${item.iteration_id}`;
    return `迭代：${name}`;
  }
  const caseId = item.case_id || "全部用例";
  return item.title ? `${caseId} - ${item.title}` : caseId;
}

function agentText(item) {
  const assignedIp = item.assigned_agent_ip || "";
  const assignedId = item.assigned_agent_id || "";
  const actualAgent = item.agent_id || "";
  if (assignedIp && actualAgent) return `${assignedIp} / ${actualAgent}`;
  if (assignedIp) return `指定 ${assignedIp}`;
  if (assignedId && actualAgent) return `${assignedId} / ${actualAgent}`;
  if (assignedId) return `指定 ${assignedId}`;
  return actualAgent ? `中心机：${actualAgent}` : "中心机";
}

function triggerTypeText(item) {
  if ((item.trigger_type || "manual") === "schedule") {
    return item.schedule_name ? `定时：${item.schedule_name}` : "定时";
  }
  return "手动";
}

function reportCaseText(report) {
  if (report.iteration_id) {
    const name = report.iteration_name || report.iteration_code || `#${report.iteration_id}`;
    return `迭代：${name}`;
  }
  if (report.case_id) {
    return report.title ? `${report.case_id} - ${report.title}` : report.case_id;
  }
  if (String(report.job_id || "").startsWith("legacy_")) {
    return "历史导入";
  }
  return "新建用例";
}

function reportSourceText(report) {
  if (report.agent_id && report.agent_id !== "legacy") {
    return `执行机：${report.agent_id}`;
  }
  if (String(report.job_id || "").startsWith("legacy_")) {
    return "来源：本地历史报告";
  }
  return report.job_id ? `任务：${report.job_id}` : "";
}

function reportTimeText(report) {
  return report.finished_at || report.updated_at || report.started_at || "";
}

function reportEntryHtml(report) {
  const simpleUrl = report.simple_report || report.report_url || "";
  const officialUrl = report.official_report || "";
  const reportUrl = simpleUrl ? withBasePath(simpleUrl) : "";
  return `
    <a class="btn btn-link btn-sm ${reportUrl ? "" : "disabled"}" href="${reportUrl || "#"}" target="_blank">测试报告</a>
  `;
}

function renderReportRow(report) {
  return `
    <div class="report-main">
      <span class="report-title">${escapeHtml(report.name || "-")}</span>
      <span class="report-meta">${escapeHtml(reportSourceText(report))}</span>
    </div>
    <div class="report-meta">${escapeHtml(reportCaseText(report))}</div>
    <div class="report-meta">${escapeHtml(triggerTypeText(report))}</div>
    <span class="status ${escapeHtml(report.status || "")}">${escapeHtml(statusText(report.status))}</span>
    <div class="report-meta">${escapeHtml(runResultText(report))}</div>
    <div class="report-meta">${escapeHtml(reportTimeText(report))}</div>
    <div class="toolbar-actions">${reportEntryHtml(report)}</div>
  `;
}

function renderRuns() {
  runJobsEl.innerHTML = "";
  if (!state.jobs.length) {
    runJobsEl.innerHTML = `<div class="table-empty">暂无执行记录。</div>`;
  } else {
    for (const job of state.jobs) {
      const node = document.createElement("div");
      node.className = "job-item";
      node.innerHTML = `
        <div class="job-main">
          <span class="job-title">${escapeHtml(job.job_id || "-")}</span>
          <span class="job-meta">${escapeHtml(job.command_text || "")}</span>
        </div>
        <div class="job-meta">${escapeHtml(caseText(job))}</div>
        <div class="job-meta">${escapeHtml(agentText(job))}</div>
        <div class="job-meta">${escapeHtml(triggerTypeText(job))}</div>
        <span class="status ${escapeHtml(job.status || "")}">${escapeHtml(statusText(job.status))}</span>
        <div class="job-meta">${escapeHtml(runResultText(job))}</div>
        <div class="job-meta">${escapeHtml(job.started_at || job.started_at_db || job.created_at || "")}</div>
        <div class="job-meta">${escapeHtml(job.finished_at || job.finished_at_db || "")}</div>
        <div class="toolbar-actions">
          <a class="btn btn-link btn-sm ${job.report_url ? "" : "disabled"}" href="${job.report_url ? withBasePath(job.report_url) : "#"}" target="_blank">报告</a>
        </div>
        <div class="toolbar-actions">
          <button class="btn btn-secondary btn-sm" type="button" data-action="log">日志</button>
        </div>
      `;
      node.querySelector('[data-action="log"]').addEventListener("click", () => showJobLog(job));
      runJobsEl.appendChild(node);
    }
  }

  reportListEl.innerHTML = "";
  if (!state.reports.length) {
    reportListEl.innerHTML = `<div class="table-empty">暂无历史报告。</div>`;
    return;
  }
  for (const report of state.reports) {
    const node = document.createElement("div");
    node.className = "report-item";
    node.innerHTML = renderReportRow(report);
    reportListEl.appendChild(node);
  }
}

async function showJobLog(job) {
  setOutputExpanded(true);
  outputEl.textContent = "";
  if (job.job_id && !job.stdout && !job.stderr && job.has_log) {
    try {
      const detail = await api(`/api/run_record_detail?job_id=${encodeURIComponent(job.job_id)}`);
      job = { ...job, ...(detail.job || {}) };
    } catch (error) {
      log(`读取日志失败: ${error.message}`);
    }
  }
  if (job.command_text) log(`执行命令: ${job.command_text}`);
  if (job.returncode !== undefined && job.returncode !== null && job.returncode !== "") {
    log(`returncode: ${job.returncode}`);
  }
  if (job.result_summary) {
    log(
      `结果汇总: total=${job.result_summary.total}, passed=${job.result_summary.passed}, failed=${job.result_summary.failed}`
    );
    const failedCases = Array.isArray(job.result_summary.failed_cases)
      ? job.result_summary.failed_cases
      : [];
    for (const item of failedCases) {
      log(`失败用例: ${item.case_name || ""} ${item.error_type || ""} ${item.error_value || ""}`);
    }
  }
  const stdout = job.stdout || job.stdout_text || "";
  const stderr = job.stderr || job.stderr_text || "";
  if (stdout) log(stdout.trim());
  if (stderr) log(stderr.trim());
  if (!stdout && !stderr && !job.result_summary && !job.command_text) log("暂无日志输出");
}

function currentPublicActionFilters() {
  // 公共动作库页面当前的筛选条件，最终会拼到 /api/options 的 query string 上。
  const pagination = state.publicActionPagination;
  return {
    keyword: (publicActionSearch?.value || "").trim(),
    page_code: (publicActionPageFilter?.value || "").trim(),
    page: pagination.page || 1,
    page_size: publicActionPageSizeEl?.value || pagination.page_size || DEFAULT_PUBLIC_ACTION_PAGE_SIZE,
  };
}

function buildOptionsUrl(filters = {}) {
  // 公共动作库使用 /api/options 的分页能力；不传 filters 时由后端使用默认第 1 页、每页 10 条。
  const params = new URLSearchParams();
  if (filters.keyword) params.set("keyword", filters.keyword);
  if (filters.page_code) params.set("page_code", filters.page_code);
  if (filters.page) params.set("page", filters.page);
  if (filters.page_size) params.set("page_size", filters.page_size);
  const query = params.toString();
  return query ? `/api/options?${query}` : "/api/options";
}

async function loadOptions(filters = {}) {
  const data = await api(buildOptionsUrl(filters));
  state.options = data;
  state.publicActionPagination = data.public_step_actions_pagination || data.public_action_pagination || {
    page: 1,
    page_size: Number(publicActionPageSizeEl?.value || DEFAULT_PUBLIC_ACTION_PAGE_SIZE),
    total: data.public_step_actions?.length || 0,
    total_pages: 1,
  };
  if (state.options.server_version && state.options.server_version !== EXPECTED_SERVER_VERSION) {
    log(`检测到旧后端版本 ${state.options.server_version}，请重启 case_editor_server.py`);
  }
  for (const [name, message] of Object.entries(state.options.errors || {})) {
    log(`options 查询失败: ${name}: ${message}`);
  }
  fillRuntimeIterationFilter();
  fillPublicActionDraftTargets();
  fillPublicActionPageFilter();
  ensurePublicActionSteps();
  renderPublicActionLibrary();
  renderPublicActionPagination();
}

function fillRuntimeIterationFilter() {
  if (!runtimeIterationFilterEl) return;
  const selected = runtimeIterationFilterEl.value || "";
  runtimeIterationFilterEl.innerHTML = `<option value="">全部迭代</option>`;
  for (const iteration of state.options.iteration_options || []) {
    const option = document.createElement("option");
    option.value = String(iteration.iteration_id || "");
    const name = iteration.iteration_name || iteration.iteration_code || option.value;
    const code = iteration.iteration_code || "";
    option.textContent = code ? `${name} (${code})` : name;
    option.selected = option.value === selected;
    runtimeIterationFilterEl.appendChild(option);
  }
}

function reloadPublicActionLibraryWithFilters(resetPage = false) {
  if (resetPage) {
    state.publicActionPagination.page = 1;
  }
  // 搜索框输入会频繁触发，用 250ms 防抖减少无意义的接口请求。
  window.clearTimeout(state.publicActionFilterTimer);
  state.publicActionFilterTimer = window.setTimeout(async () => {
    try {
      await loadOptions(currentPublicActionFilters());
    } catch (error) {
      log(`刷新公共动作库失败: ${error.message}`);
    }
  }, 250);
}

confirmDeleteIterationBtn?.addEventListener("click", () => {
  closeDeleteIterationDialog(true);
});

cancelDeleteIterationBtn?.addEventListener("click", () => {
  closeDeleteIterationDialog(false);
});

closeDeleteIterationDialogBtn?.addEventListener("click", () => {
  closeDeleteIterationDialog(false);
});

deleteIterationDialog?.addEventListener("click", (event) => {
  if (event.target === deleteIterationDialog) {
    closeDeleteIterationDialog(false);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !deleteIterationDialog?.classList.contains("hidden")) {
    closeDeleteIterationDialog(false);
  }
});

document.querySelectorAll(".tab[data-view]").forEach((tab) => {
  tab.addEventListener("click", (event) => {
    if (tab.tagName.toLowerCase() === "a") return;
    switchView(tab.dataset.view);
  });
});

document.querySelector("#addPublicActionStepBtn").addEventListener("click", () => {
  createPublicActionStep({ step_action: "click", locator_method: "text" });
});

document.querySelector("#clearOutputBtn").addEventListener("click", () => {
  outputEl.textContent = "";
});

toggleOutputBtn?.addEventListener("click", () => {
  setOutputExpanded(outputPanel?.classList.contains("output-collapsed"));
});

document.querySelector("#refreshRuntimeBtn").addEventListener("click", async () => {
  try {
    // 刷新正式用例时恢复默认查询条件，避免继续携带上一次的迭代筛选。
    if (runtimeIterationFilterEl) {
      runtimeIterationFilterEl.value = "";
    }
    if (runtimePageSizeEl) {
      runtimePageSizeEl.value = String(DEFAULT_RUNTIME_PAGE_SIZE);
    }
    state.runtimePagination.page = 1;
    state.runtimePagination.page_size = DEFAULT_RUNTIME_PAGE_SIZE;

    runtimeDetailEl?.classList.add("hidden");
    if (runtimeDetailEl) {
      runtimeDetailEl.innerHTML = "";
    }

    await loadRuntimeCases();
    log("正式用例筛选已重置并刷新");
  } catch (error) {
    log(`刷新正式用例失败: ${error.message}`);
  }
});

refreshIterationsBtn?.addEventListener("click", async () => {
  try {
    state.iterationPagination.page = 1;
    await loadIterations();
    log("需求迭代已刷新");
  } catch (error) {
    log(`刷新需求迭代失败: ${error.message}`);
  }
});

iterationPageSizeEl?.addEventListener("change", async () => {
  state.iterationPagination.page = 1;
  state.iterationPagination.page_size = Number(
    iterationPageSizeEl.value || DEFAULT_ITERATION_PAGE_SIZE
  );
  try {
    await loadIterations();
  } catch (error) {
    log(`刷新需求迭代失败: ${error.message}`);
  }
});

iterationExecutionTargetEl?.addEventListener("change", () => {
  state.executionTargetId = iterationExecutionTargetEl.value || "";
  saveIterationExecutionTarget(state.executionTargetId);
  renderExecutionTargetHints();
});

iterationPrevBtn?.addEventListener("click", async () => {
  if (state.iterationPagination.page <= 1) return;
  state.iterationPagination.page -= 1;
  try {
    await loadIterations();
  } catch (error) {
    log(`刷新需求迭代失败: ${error.message}`);
  }
});

iterationNextBtn?.addEventListener("click", async () => {
  if (state.iterationPagination.page >= state.iterationPagination.total_pages) return;
  state.iterationPagination.page += 1;
  try {
    await loadIterations();
  } catch (error) {
    log(`刷新需求迭代失败: ${error.message}`);
  }
});

runtimePageSizeEl.addEventListener("change", async () => {
  state.runtimePagination.page = 1;
  state.runtimePagination.page_size = Number(runtimePageSizeEl.value || DEFAULT_RUNTIME_PAGE_SIZE);
  try {
    await loadRuntimeCases();
  } catch (error) {
    log(`刷新正式用例失败: ${error.message}`);
  }
});

runtimeIterationFilterEl?.addEventListener("change", async () => {
  state.runtimePagination.page = 1;
  try {
    await loadRuntimeCases();
  } catch (error) {
    log(`按迭代筛选正式用例失败: ${error.message}`);
  }
});

runtimePrevBtn.addEventListener("click", async () => {
  if (state.runtimePagination.page <= 1) return;
  state.runtimePagination.page -= 1;
  try {
    await loadRuntimeCases();
  } catch (error) {
    log(`刷新正式用例失败: ${error.message}`);
  }
});

runtimeNextBtn.addEventListener("click", async () => {
  if (state.runtimePagination.page >= state.runtimePagination.total_pages) return;
  state.runtimePagination.page += 1;
  try {
    await loadRuntimeCases();
  } catch (error) {
    log(`刷新正式用例失败: ${error.message}`);
  }
});

document.querySelector("#refreshPublicActionsBtn").addEventListener("click", async () => {
  try {
    if (publicActionSearch) publicActionSearch.value = "";
    if (publicActionPageFilter) publicActionPageFilter.value = "";
    state.publicActionPagination.page = 1;
    await loadOptions(currentPublicActionFilters());
    log("公共动作库已刷新");
  } catch (error) {
    log(`刷新公共动作库失败: ${error.message}`);
  }
});

document.querySelector("#runAllBtn").addEventListener("click", async () => {
  try {
    await runCase("");
  } catch (error) {
    log(`执行失败: ${error.message}`);
  }
});

document.querySelector("#refreshRunsBtn").addEventListener("click", async () => {
  try {
    await loadRuns();
    log("执行记录已刷新");
  } catch (error) {
    log(`刷新执行记录失败: ${error.message}`);
  }
});

publicActionSearch.addEventListener("input", () => reloadPublicActionLibraryWithFilters(true));
publicActionPageFilter.addEventListener("change", () => reloadPublicActionLibraryWithFilters(true));

publicActionPageSizeEl.addEventListener("change", async () => {
  state.publicActionPagination.page = 1;
  state.publicActionPagination.page_size = Number(publicActionPageSizeEl.value || DEFAULT_PUBLIC_ACTION_PAGE_SIZE);
  try {
    await loadOptions(currentPublicActionFilters());
  } catch (error) {
    log(`刷新公共动作库失败: ${error.message}`);
  }
});

publicActionPrevBtn.addEventListener("click", async () => {
  if (state.publicActionPagination.page <= 1) return;
  state.publicActionPagination.page -= 1;
  try {
    await loadOptions(currentPublicActionFilters());
  } catch (error) {
    log(`刷新公共动作库失败: ${error.message}`);
  }
});

publicActionNextBtn.addEventListener("click", async () => {
  if (state.publicActionPagination.page >= state.publicActionPagination.total_pages) return;
  state.publicActionPagination.page += 1;
  try {
    await loadOptions(currentPublicActionFilters());
  } catch (error) {
    log(`刷新公共动作库失败: ${error.message}`);
  }
});

document.querySelector("#savePublicActionBtn").addEventListener("click", async () => {
  try {
    await savePublicActionDraft();
  } catch (error) {
    log(`保存公共动作失败: ${error.message}`);
  }
});

if (cancelPublicActionEditBtn) {
  cancelPublicActionEditBtn.addEventListener("click", () => {
    resetPublicActionDraft();
    window.location.href = appUrl("/public-actions/new");
  });
}

(async function init() {
  try {
    applyShellMode();
    if (runtimePageSizeEl) {
      runtimePageSizeEl.value = String(DEFAULT_RUNTIME_PAGE_SIZE);
    }
    if (iterationPageSizeEl) {
      iterationPageSizeEl.value = String(DEFAULT_ITERATION_PAGE_SIZE);
    }
    await loadOptions();
    await loadExecutionAgents();
    await loadRuntimeCases();
    await loadRuns();

    const params = new URLSearchParams(window.location.search);
    const selectedCaseId = params.get("case_id");
    const publicActionEditId = params.get("public_action_id") || params.get("id");
    const view = params.get("view") || routeView();
    if (selectedCaseId) await loadRuntimeCaseDetail(selectedCaseId);
    if (["runtime", "publicActions", "iterations", "runs"].includes(view)) switchView(view);
    else syncRouteMode();
    if (currentPath() === "/public-actions/edit" && publicActionEditId) {
      await loadPublicActionForEdit(publicActionEditId);
    }

    log("编辑器已就绪");
  } catch (error) {
    log(`初始化失败: ${error.message}`);
  }
})();
