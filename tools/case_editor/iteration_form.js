const ROUTE_MARKERS = ["/cases", "/public-actions", "/iterations", "/api", "/reports"];
const APP_BASE_PATH = normalizeBasePath(window.__MINITEST_BASE_PATH__ || inferBasePath());
const EMBED_MODE = new URLSearchParams(window.location.search).get("embed") === "1";

// selectedCaseIds 保存当前表单勾选的正式用例；保存迭代时会提交为 case_ids 数组。
const state = {
  reusableCases: [],
  selectedCaseIds: new Set(),
  iterationId: "",
};

const form = document.querySelector("#iterationEditorForm");
const titleEl = document.querySelector("#iterationEditorTitle");
const messageEl = document.querySelector("#iterationFormMessage");
const caseListEl = document.querySelector("#iterationCaseList");
const caseSearchInput = document.querySelector("#caseSearchInput");
const selectedCaseCountEl = document.querySelector("#selectedCaseCount");
const saveButton = document.querySelector("#saveIterationBtn");

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

async function api(path, options = {}) {
  // 保持和其他编辑页一致：后端 ok=false 或 HTTP 非 2xx 都转换成前端错误消息。
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
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setMessage(message = "", type = "") {
  messageEl.textContent = message;
  messageEl.className = `form-message ${type}`.trim();
}

function currentIterationText(item) {
  if (!item.iteration_id) return "未分配";
  const name = item.iteration_name || item.iteration_code || `#${item.iteration_id}`;
  if (String(item.iteration_id) === String(state.iterationId)) return `${name}（当前）`;
  return name;
}

function filteredCases() {
  const keyword = String(caseSearchInput.value || "").trim().toLowerCase();
  if (!keyword) return state.reusableCases;
  return state.reusableCases.filter((item) => {
    const haystack = [
      item.case_id,
      item.title,
      item.target,
      item.iteration_code,
      item.iteration_name,
    ].join(" ").toLowerCase();
    return haystack.includes(keyword);
  });
}

function updateSelectedCount() {
  selectedCaseCountEl.textContent = `已选 ${state.selectedCaseIds.size} 项`;
}

function renderCases() {
  const cases = filteredCases();
  caseListEl.innerHTML = "";
  if (!cases.length) {
    caseListEl.innerHTML = `<div class="iteration-case-empty">没有匹配的正式用例。</div>`;
    updateSelectedCount();
    return;
  }

  for (const item of cases) {
    const caseId = String(item.case_id || "");
    const selected = state.selectedCaseIds.has(caseId);
    const belongsElsewhere =
      item.iteration_id &&
      String(item.iteration_id) !== String(state.iterationId);
    const node = document.createElement("label");
    node.className = `iteration-case-item${selected ? " selected" : ""}${belongsElsewhere ? " assigned-elsewhere" : ""}`;
    node.innerHTML = `
      <div>
        <input type="checkbox" value="${escapeHtml(caseId)}" ${selected ? "checked" : ""}>
      </div>
      <div class="iteration-case-id">${escapeHtml(caseId)}</div>
      <div>
        <div class="iteration-case-title">${escapeHtml(item.title || "-")}</div>
        <div class="iteration-case-meta">${escapeHtml(item.target || "")}</div>
      </div>
      <div class="iteration-case-meta">${escapeHtml(currentIterationText(item))}</div>
      <div>
        <span class="case-enabled-state ${Number(item.enabled) === 0 ? "disabled" : "enabled"}">
          ${Number(item.enabled) === 0 ? "已禁用" : "已启用"}
        </span>
      </div>
      <div class="iteration-case-meta">${escapeHtml(item.steps_count ?? 0)}</div>
    `;
    const checkbox = node.querySelector('input[type="checkbox"]');
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selectedCaseIds.add(caseId);
      else state.selectedCaseIds.delete(caseId);
      node.classList.toggle("selected", checkbox.checked);
      updateSelectedCount();
    });
    caseListEl.appendChild(node);
  }
  updateSelectedCount();
}

function fillIteration(iteration) {
  state.iterationId = String(iteration.iteration_id || "");
  form.iteration_id.value = state.iterationId;
  form.iteration_code.value = iteration.iteration_code || "";
  form.iteration_name.value = iteration.iteration_name || "";
  form.status.value = iteration.status || "planning";
  form.start_date.value = iteration.start_date || "";
  form.end_date.value = iteration.end_date || "";
  form.description.value = iteration.description || "";
  state.selectedCaseIds = new Set((iteration.case_ids || []).map(String));
  titleEl.textContent = "编辑迭代";
  document.title = `编辑迭代 - ${iteration.iteration_name || iteration.iteration_code || state.iterationId}`;
}

function buildPayload() {
  // FormData 负责读取 HTML name 属性；额外的多选用例来自 state.selectedCaseIds。
  const data = new FormData(form);
  const payload = Object.fromEntries(data.entries());
  payload.iteration_code = String(payload.iteration_code || "").trim();
  payload.iteration_name = String(payload.iteration_name || "").trim();
  payload.description = String(payload.description || "").trim();
  payload.case_ids = [...state.selectedCaseIds];
  if (!payload.iteration_id) delete payload.iteration_id;
  if (!payload.iteration_code) throw new Error("请填写迭代编码");
  if (!payload.iteration_name) throw new Error("请填写迭代名称");
  if (payload.start_date && payload.end_date && payload.start_date > payload.end_date) {
    throw new Error("结束日期不能早于开始日期");
  }
  return payload;
}

async function saveIteration(event) {
  event.preventDefault();
  saveButton.disabled = true;
  setMessage("正在保存...");
  try {
    const response = await api("/api/iterations", {
      method: "POST",
      body: JSON.stringify(buildPayload()),
    });
    const result = response.result || {};
    setMessage(`保存成功，已关联 ${result.case_ids?.length || 0} 条用例。`, "success");
    window.setTimeout(() => {
      window.location.href = appUrl("/iterations");
    }, 350);
  } catch (error) {
    setMessage(`保存失败：${error.message}`, "error");
  } finally {
    saveButton.disabled = false;
  }
}

async function init() {
  applyShellMode();
  const params = new URLSearchParams(window.location.search);
  const iterationId = params.get("iteration_id") || params.get("id") || "";

  try {
    const options = await api("/api/reusable_cases");
    state.reusableCases = options.reusable_cases || [];

    if (iterationId) {
      const detail = await api(`/api/iteration_detail?iteration_id=${encodeURIComponent(iterationId)}`);
      fillIteration(detail.iteration || {});
    }
    renderCases();
  } catch (error) {
    setMessage(`页面初始化失败：${error.message}`, "error");
  }
}

caseSearchInput.addEventListener("input", renderCases);
document.querySelector("#selectVisibleCasesBtn").addEventListener("click", () => {
  for (const item of filteredCases()) {
    if (item.case_id) state.selectedCaseIds.add(String(item.case_id));
  }
  renderCases();
});
document.querySelector("#clearSelectedCasesBtn").addEventListener("click", () => {
  state.selectedCaseIds.clear();
  renderCases();
});
form.addEventListener("submit", saveIteration);

init();
