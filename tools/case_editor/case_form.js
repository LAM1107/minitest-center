// 用例编辑页的临时状态。保存时会由 getFormData() 组装为 JSON 提交给后端。
const state = {
  options: {
    step_actions: [],
    locator_methods: [],
    assert_types: [],
    reusable_cases: [],
    public_step_actions: [],
    iteration_options: [],
  },
  caseId: "",
  isEdit: false,
  executionAgents: [],
  centerExecutionEnabled: true,
};

const EXPECTED_SERVER_VERSION = "case-editor-20260723-center-runtime-v24";
const EXECUTION_TARGET_STORAGE_KEY = "minitest.execution_target";
const LEGACY_EXECUTION_TARGET_STORAGE_KEY = "minitest.iteration_execution_target";
const ROUTE_MARKERS = ["/cases", "/public-actions", "/api", "/reports"];
const APP_BASE_PATH = normalizeBasePath(window.__MINITEST_BASE_PATH__ || inferBasePath());
const EMBED_MODE = new URLSearchParams(window.location.search).get("embed") === "1";
const CONDITION_TYPES = [
  { value: "always", label: "总是执行" },
  { value: "exists", label: "元素存在才执行" },
  { value: "not_exists", label: "元素不存在才执行" },
  { value: "page_is", label: "当前页面等于" },
  { value: "page_contains", label: "当前页面包含" },
];
const API_ERROR_CHECK_MODES = [
  { value: "normal", label: "正常检查" },
  { value: "allow_list", label: "只允许白名单报错" },
];

const form = document.querySelector("#caseForm");
const stepsEl = document.querySelector("#steps");
const outputEl = document.querySelector("#output");
const template = document.querySelector("#stepTemplate");
const caseStepCountEl = document.querySelector("#caseStepCount");
const runtimeEditorTitle = document.querySelector("#runtimeEditorTitle");
const formNav = document.querySelector("#caseFormNav");
const normalizedHint = document.querySelector("#normalizedHint");
const flowPreview = document.querySelector("#flowPreview");
const reuseActionHint = document.querySelector("#reuseActionHint");
const reuseActionDropdown = document.querySelector("#reuseActionDropdown");
const saveBtn = document.querySelector("#saveBtn");
const runBtn = document.querySelector("#runBtn");
const executionTargetHint = document.querySelector("#caseFormExecutionTargetHint");

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

function currentPath() {
  return stripBasePath(window.location.pathname).replace(/\/+$/, "") || "/";
}

function withBasePath(path) {
  path = String(path || "");
  if (!path || path.startsWith("#") || /^[a-z][a-z0-9+.-]*:/i.test(path)) return path;
  if (!path.startsWith("/")) return path;
  if (APP_BASE_PATH && (path === APP_BASE_PATH || path.startsWith(`${APP_BASE_PATH}/`))) return path;
  return `${APP_BASE_PATH}${path}` || path;
}

function appUrl(path) {
  // 生成站内跳转 URL，并保留嵌入后台时的 embed=1 参数。
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

// 保存/执行接口报错（如未选择执行机）用浮层提示，避免错误只停留在 Network 面板。
function showToast(message, type = "error") {
  const toast = document.createElement("div");
  toast.className = `app-toast app-toast-${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.classList.add("app-toast-show"), 10);
  setTimeout(() => {
    toast.classList.remove("app-toast-show");
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function currentExecutionTargetId() {
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

function executionTargetText(agentId) {
  if (!agentId) return state.centerExecutionEnabled ? "中心机" : "请选择执行机";
  const agent = state.executionAgents.find((item) => item.agent_id === agentId);
  return agent?.agent_name || agentId;
}

function renderExecutionTargetHint() {
  if (!executionTargetHint) return;
  const agentId = currentExecutionTargetId();
  executionTargetHint.textContent = `当前执行位置：${executionTargetText(agentId)}`;
  executionTargetHint.title = agentId
    ? `当前任务会派发给执行机 ${agentId}`
    : state.centerExecutionEnabled
      ? "当前任务由中心机执行"
      : "中心机执行已禁用，请到需求迭代页选择执行机";
}

async function loadExecutionTarget() {
  const agentId = currentExecutionTargetId();
  try {
    const data = await api("/api/agents");
    state.centerExecutionEnabled = data.center_execution_enabled !== false;
    state.executionAgents = data.remote_agents_enabled ? data.agents || [] : [];
    const exists = !agentId || state.executionAgents.some(
      (item) => item.agent_id === agentId && Number(item.enabled) !== 0
    );
    if (!exists) {
      // 执行机被禁用或远程执行关闭后，避免下次保存并执行仍提交失效的 agent_id。
      window.localStorage.removeItem(EXECUTION_TARGET_STORAGE_KEY);
      window.localStorage.removeItem(LEGACY_EXECUTION_TARGET_STORAGE_KEY);
    }
  } catch (_) {
    // 查询执行机名称失败时仍保留原选择，服务端会在提交时给出明确错误。
  }
  renderExecutionTargetHint();
}

async function api(path, options = {}) {
  // 统一处理保存、读取详情和执行接口的 HTTP 错误。
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

function fillApiErrorModeSelect(select, selected = "normal") {
  select.innerHTML = API_ERROR_CHECK_MODES
    .map((item) => `<option value="${item.value}" ${item.value === selected ? "selected" : ""}>${item.label}</option>`)
    .join("");
}

function fillIterationSelect(select, selected = "") {
  const selectedValue = String(selected || "");
  select.innerHTML = `<option value="">未分配迭代</option>`;
  for (const iteration of state.options.iteration_options || []) {
    const option = document.createElement("option");
    option.value = String(iteration.iteration_id || "");
    const name = iteration.iteration_name || iteration.iteration_code || option.value;
    const code = iteration.iteration_code || "";
    option.textContent = code ? `${name} (${code})` : name;
    option.selected = option.value === selectedValue;
    select.appendChild(option);
  }
}

function allowedErrorsText(value) {
  if (!value) return "";
  if (Array.isArray(value)) return value.filter(Boolean).join("|");
  return String(value);
}

function allowedErrorsArray(value) {
  return String(value || "")
    .replaceAll("\n", "|")
    .replaceAll(",", "|")
    .split("|")
    .map((item) => item.trim())
    .filter(Boolean);
}

function hasLegacyApiPolicyParams(value) {
  return /(^|[,{]\s*)(ignore_error|allowed_errors)\s*[=:]/.test(String(value || ""));
}

function normalizeFlowHint(value) {
  return (value || "")
    .trim()
    .replaceAll("\\", "/")
    .split("/")
    .map((part) =>
      part
        .trim()
        .toLowerCase()
        .replace(/[^0-9a-z_\u4e00-\u9fff]+/g, "_")
        .replace(/^_+|_+$/g, "")
    )
    .filter(Boolean)
    .join("/");
}

function splitFlowHint(value) {
  const normalized = normalizeFlowHint(value);
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length <= 1) {
    return { dir: "", module: parts[0] || "" };
  }
  return {
    dir: parts.slice(0, -1).join("/"),
    module: parts[parts.length - 1],
  };
}

function ensureFlowDirOption(dir) {
  if (!dir) return;
  const exists = [...form.flow_group_dir.options].some((option) => option.value === dir);
  if (exists) return;

  const option = document.createElement("option");
  option.value = dir;
  option.textContent = `自定义：${dir}`;
  form.flow_group_dir.appendChild(option);
}

function buildFlowHint() {
  const dir = normalizeFlowHint(form.flow_group_dir.value);
  const module = splitFlowHint(form.flow_module.value).module;
  return [dir, module].filter(Boolean).join("/");
}

function flowPreviewText(flowHint) {
  const { dir, module } = splitFlowHint(flowHint);
  if (!module) return "";

  const flowPath = dir
    ? `framework/flows/${dir}/${module}_flow.py`
    : `framework/flows/${module}_flow.py`;
  return `兼容字段：${flowPath}；数据库执行不会生成 flow 文件`;
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

function currentMode() {
  return form.case_mode.value || "generate";
}

function isReuseMode() {
  return currentMode() === "reuse";
}

function actionParamNames(item) {
  return (item.params || []).map((param) => param.name);
}

function actionDisplayName(item) {
  return (item.action_name || item.title || item.desc || "").trim() || item.action || `#${item.id}`;
}

function reusableCases() {
  return state.options.reusable_cases || [];
}

function reusableCaseId(item = {}) {
  return String(item.source_case_id || item.case_id || "");
}

function publicActionId(item = {}) {
  return String(item.public_action_id || item.id || item.action || "");
}

function firstPublicActionStep(item = {}) {
  const steps = item.steps || [];
  return steps[0] || item.first_step || {};
}

function normalizePublicOperation(operation) {
  return operation === "exists" ? "element_exists" : operation;
}

function publicOperationFromStepAction(stepAction) {
  return normalizePublicOperation(stepAction);
}

function publicStepActionOptionText(item) {
  const params = actionParamNames(item);
  const paramsText = params.length ? ` ｜ 参数：${params.join(", ")}` : "";
  const firstStep = firstPublicActionStep(item);
  const locatorText = firstStep.locator_value
    ? ` ｜ ${firstStep.locator_method}:${firstStep.locator_value}`
    : "";
  const pageText = item.page_title ? `${item.page_title} / ` : "";
  return `${pageText}${actionDisplayName(item)}${locatorText}${paramsText}`;
}

function groupBySource(actions) {
  const groups = [];
  const groupMap = new Map();
  for (const item of actions) {
    const key = item.page_code || item.source_file || item.target || "未分组";
    if (!groupMap.has(key)) {
      const group = {
        label: item.page_title || item.source_group || item.source_name || item.target || key,
        items: [],
      };
      groupMap.set(key, group);
      groups.push(group);
    }
    groupMap.get(key).items.push(item);
  }
  return groups;
}

function selectedPublicStepAction(actionValue) {
  return (state.options.public_step_actions || []).find(
    (item) => publicActionId(item) === String(actionValue || "")
  );
}

function matchingPublicStepAction(step = {}) {
  const selectedAction = step.public_action || step.public_action_key || step.public_action_id;
  if (selectedAction) return selectedPublicStepAction(selectedAction);

  const operation = publicOperationFromStepAction(step.step_action || "");
  return (state.options.public_step_actions || []).find((item) => {
    const steps = item.steps || [];
    if (steps.length !== 1) return false;
    const firstStep = steps[0];
    return (
      normalizePublicOperation(firstStep.step_action) === operation &&
      firstStep.locator_method === (step.locator_method || "") &&
      firstStep.locator_value === (step.locator_value || "")
    );
  });
}

function fillPublicStepActionSelect(select, selected = "") {
  const actions = state.options.public_step_actions || [];
  select.innerHTML = "";

  if (!actions.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent =
      state.options.server_version && state.options.server_version !== EXPECTED_SERVER_VERSION
        ? "请重启后端"
        : "暂无公共动作";
    select.appendChild(option);
    select.disabled = true;
    return;
  }

  select.disabled = false;
  select.innerHTML = '<option value="">手写步骤</option>';
  for (const group of groupBySource(actions)) {
    const optgroup = document.createElement("optgroup");
    optgroup.label = group.label;
    for (const item of group.items) {
      const option = document.createElement("option");
      option.value = publicActionId(item);
      option.textContent = publicStepActionOptionText(item);
      if (publicActionId(item) === String(selected || "")) option.selected = true;
      optgroup.appendChild(option);
    }
    select.appendChild(optgroup);
  }
}

function applyPublicStepAction(node, item) {
  if (!item) return;

  const firstStep = firstPublicActionStep(item);
  node.querySelector('[name="step_action"]').value = firstStep.step_action || "click";
  const useCandidates = isCandidateStep(firstStep);
  if (!useCandidates) {
    node.querySelector('[name="locator_method"]').value = firstStep.locator_method || "";
  }
  node.querySelector('[name="locator_value"]').value = firstStep.locator_value || "";
  node.querySelector('[name="locator_options"]').value = firstStep.locator_options || "";
  setCandidateMode(node, useCandidates);

  const paramNames = actionParamNames(item);
  const paramsHint = paramNames.length ? `；params: ${paramNames.map((name) => `${name}=xxx`).join(",")}` : "";
  node.querySelector('[name="备注"]').value = `公共动作：${actionDisplayName(item)} ｜ id=${publicActionId(item)}${paramsHint}`;
}

function reusableCaseOptionText(item) {
  const params = actionParamNames(item);
  const paramsText = params.length ? ` ｜ 参数：${params.join(", ")}` : "";
  const caseId = reusableCaseId(item);
  const displayName = actionDisplayName(item);
  const stepsText = item.steps_count ? ` ｜ ${item.steps_count} 步` : "";
  return displayName === caseId
    ? `${caseId}${stepsText}${paramsText}`
    : `${displayName} ｜ ${caseId}${stepsText}${paramsText}`;
}

function selectedReuseDisplayText() {
  const selectedCase = selectedReusableCase();
  return selectedCase ? reusableCaseOptionText(selectedCase) : "";
}

function reuseActionKeyword() {
  const raw = (form.reuse_action_display?.value || "").trim();
  if (raw && raw === selectedReuseDisplayText()) return "";
  return raw.toLowerCase();
}

function filteredReusableCases() {
  const keyword = reuseActionKeyword();
  const actions = reusableCases();
  if (!keyword) return actions;

  return actions.filter((item) => {
    const searchable = [
      reusableCaseId(item),
      item.desc,
      item.title,
      item.target,
      item.method,
      ...actionParamNames(item),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return searchable.includes(keyword);
  });
}

function fillReuseActionSelect(selected = "") {
  const allActions = reusableCases();
  const actions = filteredReusableCases();
  reuseActionDropdown.innerHTML = "";
  form.reuse_action.value = selected || form.reuse_action.value || "";

  if (!allActions.length) {
    reuseActionDropdown.innerHTML = `<div class="reuse-action-empty">${
      state.options.server_version && state.options.server_version !== EXPECTED_SERVER_VERSION
        ? "未加载到用例，请重启 case_editor_server.py"
        : "暂无可复用用例"
    }</div>`;
    reuseActionDropdown.classList.remove("hidden");
    return;
  }

  if (!actions.length) {
    reuseActionDropdown.innerHTML = '<div class="reuse-action-empty">没有匹配的用例</div>';
    reuseActionDropdown.classList.remove("hidden");
    return;
  }

  for (const item of actions.slice(0, 50)) {
    const caseId = reusableCaseId(item);
    const paramNames = actionParamNames(item);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "reuse-action-option";
    button.dataset.caseId = caseId;
    if (caseId === form.reuse_action.value) button.classList.add("active");
    button.innerHTML = `
      <strong>${escapeHtml(actionDisplayName(item))}</strong>
      <span>${escapeHtml(caseId)}${item.steps_count ? ` ｜ ${escapeHtml(item.steps_count)} 步` : ""}${paramNames.length ? ` ｜ 参数：${escapeHtml(paramNames.join(", "))}` : ""}</span>
    `;
    reuseActionDropdown.appendChild(button);
  }
  if (actions.length > 50) {
    const more = document.createElement("div");
    more.className = "reuse-action-empty";
    more.textContent = `还有 ${actions.length - 50} 条结果，请继续输入关键词缩小范围`;
    reuseActionDropdown.appendChild(more);
  }
  reuseActionDropdown.classList.remove("hidden");
}

function selectedReusableCase() {
  return reusableCases().find((item) => reusableCaseId(item) === form.reuse_action.value);
}

function hideReuseActionDropdown() {
  reuseActionDropdown?.classList.add("hidden");
}

function setReuseActionSelection(itemOrCaseId, showDisplay = true) {
  const caseId = typeof itemOrCaseId === "string" ? itemOrCaseId : reusableCaseId(itemOrCaseId);
  const item = typeof itemOrCaseId === "string"
    ? reusableCases().find((candidate) => reusableCaseId(candidate) === caseId)
    : itemOrCaseId;

  form.reuse_action.value = caseId || "";
  if (showDisplay) {
    form.reuse_action_display.value = item ? reusableCaseOptionText(item) : caseId || "";
  }
  renderReuseCaseHint();
}

function resolveReuseActionFromInput() {
  if (form.reuse_action.value) return;
  const raw = (form.reuse_action_display?.value || "").trim();
  if (!raw) return;

  const matched = reusableCases().find((item) => {
    return [
      reusableCaseId(item),
      reusableCaseOptionText(item),
      actionDisplayName(item),
    ].includes(raw);
  });
  if (matched) setReuseActionSelection(matched);
}

function renderReuseCaseHint() {
  const actions = reusableCases();
  if (!actions.length) {
    reuseActionHint.textContent = "没有读取到可复用用例。";
    form.params.placeholder = "请输入用例所需参数";
    return;
  }

  const selectedCase = selectedReusableCase();
  if (!selectedCase) {
    reuseActionHint.textContent = "选择已有用例后，会复制它的步骤；这里只需要填写新用例 params 和最终断言。";
    form.params.placeholder = "请输入用例所需参数";
    return;
  }

  const paramNames = actionParamNames(selectedCase);
  const paramsHint = paramNames.length
    ? `建议 params：${paramNames.map((name) => `${name}=xxx`).join(",")}`
    : "该用例没有记录业务参数";
  form.params.placeholder = paramNames.length
    ? paramNames.map((name) => `${name}=xxx`).join(",")
    : "当前用例没有参数，可留空";
  reuseActionHint.textContent = [
    `已选择：${actionDisplayName(selectedCase)}`,
    `来源用例：${reusableCaseId(selectedCase)}`,
    selectedCase.steps_count ? `步骤数：${selectedCase.steps_count}` : "",
    paramsHint,
  ].filter(Boolean).join("；");
}

function syncMode() {
  const reuse = isReuseMode();
  document.querySelectorAll(".generation-only").forEach((node) => {
    node.classList.toggle("hidden", reuse);
  });
  document.querySelectorAll(".reuse-only").forEach((node) => {
    node.classList.toggle("hidden", !reuse);
  });
  saveBtn.textContent = "保存";
  runBtn.textContent = "保存并执行";
  if (reuse) {
    normalizedHint.textContent = "";
  } else {
    updateNormalizedHint();
  }
  renderReuseCaseHint();
}

function emptyCase() {
  return {
    case_mode: "generate",
    case_id: "",
    title: "",
    iteration_id: "",
    flow_group_hint: "",
    reuse_action: "",
    params: "",
    api_error_check_mode: "normal",
    allowed_errors: [],
    assert_type: "",
    assert_value: "",
    steps: [
      { step_action: "click", locator_method: "text", locator_value: "", locator_options: "", step_value: "", "备注": "" },
    ],
  };
}

function normalizeRuntimeCaseForForm(caseData) {
  return {
    ...caseData,
    case_mode: "generate",
    reuse_action: caseData.source_case_id || "",
    params: caseData.params || caseData.inputs || "",
    api_error_check_mode: caseData.api_error_check_mode || "normal",
    allowed_errors: caseData.allowed_errors || [],
    assert_value: caseData.assert_value || caseData.expect_value || "",
    steps: (caseData.steps || []).map((step) => ({
      public_action: step.public_action || step.public_action_id || "",
      step_action: step.step_action || "click",
      locator_method: step.locator_method || "",
      locator_value: step.locator_value || "",
      locator_options: step.locator_options || "",
      step_value: step.step_value || "",
      condition_type: step.condition_type || "always",
      condition_locator_method: step.condition_locator_method || "",
      condition_locator_value: step.condition_locator_value || "",
      condition_options: step.condition_options || "",
      "备注": step["备注"] || step.remark || "",
    })),
  };
}

function setForm(caseData) {
  form.case_mode.value = caseData.case_mode || "generate";
  form.case_id.value = caseData.case_id || "";
  form.title.value = caseData.title || "";
  fillIterationSelect(form.iteration_id, caseData.iteration_id || "");
  const flowHint = splitFlowHint(caseData.flow_group_hint || "");
  ensureFlowDirOption(flowHint.dir);
  form.flow_group_dir.value = flowHint.dir;
  form.flow_module.value = flowHint.module;
  setReuseActionSelection(caseData.reuse_action || "");
  hideReuseActionDropdown();
  form.params.value = caseData.params || "";
  fillApiErrorModeSelect(form.api_error_check_mode, caseData.api_error_check_mode || "normal");
  form.allowed_errors.value = allowedErrorsText(caseData.allowed_errors);
  fillSelect(form.assert_type, ["", ...state.options.assert_types], caseData.assert_type || "");
  form.assert_value.value = caseData.assert_value || "";

  stepsEl.innerHTML = "";
  const steps = caseData.steps?.length ? caseData.steps : emptyCase().steps;
  steps.forEach(createStep);
  updateNormalizedHint();
  syncMode();
}

function createStep(step = {}) {
  const node = template.content.firstElementChild.cloneNode(true);
  const matchedPublicAction = matchingPublicStepAction(step);
  const useCandidates = isCandidateStep(step);
  fillPublicStepActionSelect(node.querySelector('[name="public_action"]'), publicActionId(matchedPublicAction) || "");
  fillSelect(node.querySelector('[name="step_action"]'), state.options.step_actions, step.step_action || "click");
  fillSelect(
    node.querySelector('[name="locator_method"]'),
    locatorMethodOptions(useCandidates ? "" : step.locator_method),
    useCandidates ? "text" : step.locator_method || ""
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
  node.querySelector('[name="备注"]').value = step["备注"] || "";
  node.querySelector('[name="locator_method"]').addEventListener("change", () => {
    node.querySelector('[name="public_action"]').value = "";
    refreshStepHints(node);
  });
  node.querySelector('[name="use_candidates"]').addEventListener("change", (event) => {
    node.querySelector('[name="public_action"]').value = "";
    setCandidateMode(node, event.target.checked);
  });
  ["locator_value", "locator_options"].forEach((fieldName) => {
    node.querySelector(`[name="${fieldName}"]`).addEventListener("input", () => {
      node.querySelector('[name="public_action"]').value = "";
    });
  });
  node.querySelector('[name="public_action"]').addEventListener("change", (event) => {
    applyPublicStepAction(node, selectedPublicStepAction(event.target.value));
  });
  node.querySelectorAll("button[data-action]").forEach((button) => {
    button.addEventListener("click", () => handleStepAction(node, button.dataset.action));
  });
  setCandidateMode(node, useCandidates);
  stepsEl.appendChild(node);
  refreshStepIndexes();
}

function refreshStepIndexes() {
  [...stepsEl.children].forEach((node, index) => {
    node.querySelector(".step-index").textContent = index + 1;
  });
  if (caseStepCountEl) {
    caseStepCountEl.textContent = String(stepsEl.children.length);
  }
}

function handleStepAction(node, action) {
  if (action === "remove") {
    node.remove();
  }
  if (action === "up" && node.previousElementSibling) {
    stepsEl.insertBefore(node, node.previousElementSibling);
  }
  if (action === "down" && node.nextElementSibling) {
    stepsEl.insertBefore(node.nextElementSibling, node);
  }
  if (!stepsEl.children.length) {
    createStep({ step_action: "click", locator_method: "text" });
    return;
  }
  refreshStepIndexes();
}

function getVisibleStepData() {
  return [...stepsEl.children].map((node) => ({
    public_action: node.querySelector('[name="public_action"]').value.trim(),
    step_action: node.querySelector('[name="step_action"]').value,
    locator_method: stepUsesCandidates(node) ? "candidates" : node.querySelector('[name="locator_method"]').value,
    locator_value: node.querySelector('[name="locator_value"]').value.trim(),
    locator_options: node.querySelector('[name="locator_options"]').value.trim(),
    step_value: node.querySelector('[name="step_value"]').value.trim(),
    condition_type: node.querySelector('[name="condition_type"]').value,
    condition_locator_method: node.querySelector('[name="condition_locator_method"]').value,
    condition_locator_value: node.querySelector('[name="condition_locator_value"]').value.trim(),
    condition_options: node.querySelector('[name="condition_options"]').value.trim(),
    "备注": node.querySelector('[name="备注"]').value.trim(),
  }));
}

function getFormData() {
  return {
    case_id: form.case_id.value.trim(),
    title: form.title.value.trim(),
    iteration_id: form.iteration_id.value,
    flow_group_hint: buildFlowHint(),
    params: form.params.value.trim(),
    api_error_check_mode: form.api_error_check_mode.value || "normal",
    allowed_errors: allowedErrorsArray(form.allowed_errors.value),
    assert_type: form.assert_type.value,
    assert_value: form.assert_value.value.trim(),
    steps: getVisibleStepData(),
  };
}

function getRuntimeCaseData() {
  resolveReuseActionFromInput();
  return {
    case_id: form.case_id.value.trim(),
    title: form.title.value.trim(),
    iteration_id: form.iteration_id.value,
    source_case_id: form.reuse_action.value.trim(),
    flow_group_hint: buildFlowHint(),
    inputs: form.params.value.trim(),
    params: form.params.value.trim(),
    api_error_check_mode: form.api_error_check_mode.value || "normal",
    allowed_errors: allowedErrorsArray(form.allowed_errors.value),
    assert_type: form.assert_type.value,
    expect_value: form.assert_value.value.trim(),
    assert_value: form.assert_value.value.trim(),
  };
}

function validateCase(data) {
  if (!data.case_id) return "case_id 不能为空";
  if (!data.title) return "title 不能为空";
  if (!data.steps.length) return "至少需要一个业务步骤";
  if (hasLegacyApiPolicyParams(data.params)) return "params 不要填写 ignore_error/allowed_errors，请使用接口错误模式和允许报错接口";
  if (data.assert_type && !data.assert_value) return "填写 assert_type 后必须填写 assert_value";
  if (data.api_error_check_mode === "allow_list" && !data.allowed_errors.length) {
    return "接口错误模式为白名单时，必须填写允许报错接口";
  }
  for (const [index, step] of data.steps.entries()) {
    if (["exists", "not_exists"].includes(step.condition_type)) {
      const hasConditionLocator = step.condition_locator_value || step.locator_value;
      const hasConditionMethod = step.condition_locator_method || step.locator_method;
      if (!hasConditionLocator || !hasConditionMethod) {
        return `第 ${index + 1} 步的执行条件缺少条件定位`;
      }
    }
    if (["page_is", "page_contains"].includes(step.condition_type) && !step.condition_locator_value) {
      return `第 ${index + 1} 步的页面条件缺少条件定位值`;
    }
    if (step.public_action) continue;
    if (!step.step_action) return `第 ${index + 1} 步缺少 step_action`;
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
      return `第 ${index + 1} 步缺少 locator_value`;
    }
  }
  return "";
}

function validateRuntimeCase(data) {
  if (!data.case_id) return "case_id 不能为空";
  if (!data.title) return "title 不能为空";
  if (!data.source_case_id) return "请选择已有用例";
  if (hasLegacyApiPolicyParams(data.params)) return "params 不要填写 ignore_error/allowed_errors，请使用接口错误模式和允许报错接口";
  if (data.assert_type && !data.expect_value) return "填写 assert_type 后必须填写 assert_value";
  if (data.api_error_check_mode === "allow_list" && !data.allowed_errors.length) {
    return "接口错误模式为白名单时，必须填写允许报错接口";
  }
  return "";
}

async function saveStepCase() {
  const data = getFormData();
  const error = validateCase(data);
  if (error) throw new Error(error);
  const saved = await api("/api/runtime_case_edit", {
    method: "POST",
    body: JSON.stringify(data),
  });
  log(`正式用例已保存: ${saved.result.case_id}`);
  return saved.result;
}

async function saveReusedCase() {
  const data = getRuntimeCaseData();
  const error = validateRuntimeCase(data);
  if (error) throw new Error(error);
  const saved = await api("/api/runtime_case", {
    method: "POST",
    body: JSON.stringify(data),
  });
  log(`正式用例保存成功: ${saved.result.case_id}, 来源用例=${saved.result.source_case_id}`);
  return saved.result;
}

async function saveCurrentCase() {
  return isReuseMode() ? saveReusedCase() : saveStepCase();
}

async function runCase(caseId = "") {
  const agentId = currentExecutionTargetId();
  try {
    const response = await api("/api/run_case", {
      method: "POST",
      body: JSON.stringify({
        case_id: caseId,
        agent_id: agentId,
      }),
    });
    log(`执行任务已创建: ${response.job.job_id} ${caseId || "全部用例"}，${executionTargetText(agentId)}执行`);
    return response.job;
  } catch (error) {
    log(`执行任务创建失败: ${error.message}`);
    showToast(`执行任务创建失败：${error.message}`, "error");
    return null;
  }
}

async function saveAndRun() {
  const saved = await saveCurrentCase();
  const job = await runCase(saved.case_id);
  if (!job) return;
  window.location.href = appUrl(`/cases?view=runs&case_id=${encodeURIComponent(saved.case_id)}`);
}

function updateNormalizedHint() {
  const raw = [form.flow_group_dir.value, form.flow_module.value].filter(Boolean).join("/");
  const normalized = buildFlowHint();
  normalizedHint.textContent = raw && raw !== normalized ? `将规范化为 ${normalized}` : "";
  flowPreview.textContent = flowPreviewText(normalized);
}

async function loadOptions() {
  // Fixed vocabularies and database-backed dropdown data use separate APIs.
  // The form still loads them together, but one slow list no longer delays /api/options.
  const [base, pages, iterations, reusableCases, publicActions] = await Promise.all([
    api("/api/options"),
    api("/api/public_action_pages"),
    api("/api/iteration_options"),
    api("/api/reusable_cases"),
    api("/api/public_actions?page=1&page_size=200"),
  ]);
  state.options = {
    ...base,
    page_options: pages.page_options || [],
    iteration_options: iterations.iteration_options || [],
    reusable_cases: reusableCases.reusable_cases || [],
    public_step_actions: publicActions.actions || [],
  };
  if (state.options.server_version && state.options.server_version !== EXPECTED_SERVER_VERSION) {
    log(`检测到旧后端版本 ${state.options.server_version}，请重启 case_editor_server.py`);
  }
  // options 接口会尽量返回可用数据；局部失败信息放在 errors 里，展示到页面日志方便排查。
  for (const [name, message] of Object.entries(state.options.errors || {})) {
    log(`options 查询失败: ${name}: ${message}`);
  }
}

async function loadCaseForEdit(caseId) {
  const data = await api(`/api/runtime_case_detail?case_id=${encodeURIComponent(caseId)}`);
  setForm(normalizeRuntimeCaseForForm(data.case));
  runtimeEditorTitle.textContent = "编辑正式用例";
  formNav.textContent = "编辑用例";
  formNav.href = appUrl(`/cases/edit?case_id=${encodeURIComponent(caseId)}`);
  document.title = `编辑用例 - ${caseId}`;
  log(`已加载正式用例: ${caseId}`);
}

function initPageState() {
  const params = new URLSearchParams(window.location.search);
  state.caseId = params.get("case_id") || "";
  state.isEdit = currentPath() === "/cases/edit";
  runtimeEditorTitle.textContent = state.isEdit ? "编辑正式用例" : "新建正式用例";
  formNav.textContent = state.isEdit ? "编辑用例" : "新建用例";
}

document.querySelector("#addStepBtn").addEventListener("click", () => {
  createStep({ step_action: "click", locator_method: "text" });
});

document.querySelector("#clearOutputBtn").addEventListener("click", () => {
  outputEl.textContent = "";
});

runBtn.addEventListener("click", async () => {
  try {
    await saveAndRun();
  } catch (error) {
    log(`错误: ${error.message}`);
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const saved = await saveCurrentCase();
    window.location.href = appUrl(`/cases?case_id=${encodeURIComponent(saved.case_id)}`);
  } catch (error) {
    log(`错误: ${error.message}`);
  }
});

form.querySelectorAll('[name="case_mode"]').forEach((radio) => {
  radio.addEventListener("change", syncMode);
});

form.reuse_action_display.addEventListener("input", () => {
  form.reuse_action.value = "";
  fillReuseActionSelect("");
  renderReuseCaseHint();
});
form.reuse_action_display.addEventListener("focus", () => {
  fillReuseActionSelect(form.reuse_action.value);
});
form.reuse_action_display.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    hideReuseActionDropdown();
    return;
  }
  if (event.key === "Enter" && !reuseActionDropdown.classList.contains("hidden")) {
    const firstOption = reuseActionDropdown.querySelector(".reuse-action-option");
    if (firstOption) {
      event.preventDefault();
      firstOption.click();
    }
  }
});
reuseActionDropdown.addEventListener("mousedown", (event) => {
  event.preventDefault();
});
reuseActionDropdown.addEventListener("click", (event) => {
  const option = event.target.closest(".reuse-action-option");
  if (!option) return;
  const item = reusableCases().find((candidate) => reusableCaseId(candidate) === option.dataset.caseId);
  if (item) {
    setReuseActionSelection(item);
    hideReuseActionDropdown();
  }
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".reuse-combobox")) hideReuseActionDropdown();
});
form.flow_group_dir.addEventListener("change", updateNormalizedHint);
form.flow_module.addEventListener("input", updateNormalizedHint);

(async function init() {
  try {
    applyShellMode();
    initPageState();
    await loadOptions();
    await loadExecutionTarget();
    if (state.isEdit) {
      if (!state.caseId) throw new Error("编辑页面缺少 case_id");
      await loadCaseForEdit(state.caseId);
    } else {
      setForm(emptyCase());
    }
    log("表单已就绪");
  } catch (error) {
    log(`初始化失败: ${error.message}`);
  }
})();
