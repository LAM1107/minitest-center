"""Minitest 管理页面与 API 服务。

职责分为三部分：提供 HTML 静态页面、把 HTTP 请求转成数据库读写、
以及把执行任务投递给中心机或远程执行机。具体页面操作始终由
StepExecutor 读取数据库步骤后完成。
"""

import json
import locale
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from framework.utils.mysql_case_repository import (
    MySqlCaseRepository,
    parse_inputs_text,
    public_action_page_options,
)


REPORTS_DIR = PROJECT_ROOT / "reports"
STATIC_DIR = PROJECT_ROOT / "tools" / "case_editor"
RUN_JOBS = {}
RUN_JOBS_LOCK = threading.Lock()
SERVER_VERSION = "case-editor-20260722-center-runtime-v23"
# 反向代理将服务挂在 /minitest 等子路径时使用；空值表示根路径部署。
URL_PREFIX = ""


def normalize_url_prefix(value):
    """Normalize optional mount prefix, for example '/minitest'."""
    value = str(value or "").strip().replace("\\", "/")
    if not value or value == "/":
        return ""
    if not value.startswith("/"):
        value = f"/{value}"
    return value.rstrip("/")


def strip_configured_prefix(path):
    if not URL_PREFIX:
        return path
    if path == URL_PREFIX:
        return "/"
    if path.startswith(f"{URL_PREFIX}/"):
        return path[len(URL_PREFIX):] or "/"
    return path


def strip_detected_prefix(path):
    """Allow reverse-proxy prefixes such as /minitest/cases without code edits."""
    if path in {
        "/",
        "/cases",
        "/cases/",
        "/cases/new",
        "/cases/edit",
        "/iterations",
        "/iterations/",
        "/iterations/new",
        "/iterations/edit",
    }:
        return path
    if path.startswith(("/api/", "/reports/", "/public-actions", "/iterations")):
        return path

    for marker in ("/api/", "/reports/", "/cases", "/public-actions", "/iterations"):
        index = path.find(marker)
        if index > 0:
            return path[index:]
    return path


def request_path(path):
    path = urlparse(path).path if "://" in str(path) else str(path or "/")
    if not path.startswith("/"):
        path = f"/{path}"
    return strip_detected_prefix(strip_configured_prefix(path)) or "/"


def decode_process_output(raw_output):
    """Decode subprocess bytes without corrupting Windows Chinese console output."""
    if raw_output in (None, b""):
        return ""
    if isinstance(raw_output, str):
        return raw_output

    candidates = [
        "utf-8-sig",
        locale.getpreferredencoding(False),
        "gbk",
        "cp936",
        "mbcs",
    ]
    seen = set()
    for encoding in candidates:
        if not encoding or encoding.lower() in seen:
            continue
        seen.add(encoding.lower())
        try:
            return raw_output.decode(encoding)
        except UnicodeDecodeError:
            continue
        except LookupError:
            continue

    return raw_output.decode("utf-8", errors="replace")


def positive_int(value, default, maximum=200):
    try:
        number = int(value or default)
    except (TypeError, ValueError):
        number = default
    number = max(number, 1)
    if maximum:
        number = min(number, maximum)
    return number


def truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def case_repository():
    """按请求创建仓储对象，连接在具体仓储方法结束后自动关闭。"""
    return MySqlCaseRepository()


def remote_agents_enabled():
    return os.environ.get("MINITEST_ENABLE_REMOTE_AGENTS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def center_execution_enabled():
    """中心服务是否允许直接启动本机 Minium。

    生产中心服务通常只负责派发任务，设为 false 后必须指定 Windows 执行机，
    避免 Linux 服务误执行本地 run.py。
    """
    return truthy(os.environ.get("MINITEST_ENABLE_CENTER_EXECUTION", "true"))


def read_runtime_cases_all():
    return case_repository().list_runtime_cases()


def read_runtime_cases(page=1, page_size=10, iteration_id=None):
    return case_repository().list_runtime_cases_page(
        page=page,
        page_size=page_size,
        iteration_id=iteration_id,
    )


def read_runtime_case_detail(case_id):
    case_id = str(case_id or "").strip()
    if not case_id:
        raise ValueError("case_id is required")
    return case_repository().get_case_detail(case_id, include_disabled=True)


def write_runtime_case(case_data):
    return clone_runtime_case_steps(case_data)


def edit_runtime_case(case_data):
    return case_repository().upsert_step_case(case_data)


def param_names_from_inputs(inputs):
    return [{"name": name} for name in parse_inputs_text(inputs).keys()]


def list_reusable_cases():
    """Return all DB cases that can be reused as step templates."""
    cases = []
    seen = set()
    for row in read_runtime_cases_all():
        action = str(row.get("case_id") or "").strip()
        if not action or action in seen:
            continue

        seen.add(action)
        cases.append(
            {
                "case_id": action,
                "source_case_id": action,
                "title": row.get("title") or action,
                "target": row.get("flow_group_hint") or "db_steps",
                "method": action,
                "params": param_names_from_inputs(row.get("inputs", "")),
                "desc": row.get("title") or action,
                "steps_count": row.get("steps_count", 0),
                "enabled": row.get("enabled", 1),
                "iteration_id": row.get("iteration_id"),
                "iteration_code": row.get("iteration_code", ""),
                "iteration_name": row.get("iteration_name", ""),
                "source_name": "mt_cases",
                "source_group": "数据库用例",
            }
        )

    cases.sort(key=lambda item: item["case_id"])
    return cases


def clone_runtime_case_steps(case_data):
    source_case_id = str(case_data.get("source_case_id") or "").strip()
    if not source_case_id:
        raise ValueError("source_case_id is required")

    source_case = read_runtime_case_detail(source_case_id)
    source_steps = source_case.get("steps") or []
    if not source_steps:
        raise ValueError(f"source case has no steps: {source_case_id}")

    cloned_steps = []
    for step in source_steps:
        cloned_steps.append(
            {
                "step_order": step.get("step_order"),
                "public_action": step.get("public_action_id")
                or step.get("public_action")
                or step.get("public_action_key")
                or "",
                "step_action": step.get("step_action", ""),
                "locator_method": step.get("locator_method", ""),
                "locator_value": step.get("locator_value", ""),
                "locator_options": step.get("locator_options", ""),
                "step_value": step.get("step_value", ""),
                "condition_type": step.get("condition_type", "always"),
                "condition_locator_method": step.get("condition_locator_method", ""),
                "condition_locator_value": step.get("condition_locator_value", ""),
                "condition_options": step.get("condition_options", ""),
                "remark": step.get("remark") or step.get("备注") or "",
            }
        )

    result = edit_runtime_case(
        {
            "case_id": case_data.get("case_id"),
            "title": case_data.get("title"),
            "iteration_id": case_data.get("iteration_id")
            if case_data.get("iteration_id") not in (None, "")
            else source_case.get("iteration_id"),
            "flow_group_hint": case_data.get("flow_group_hint")
            or source_case.get("flow_group_hint", ""),
            "params": case_data.get("params") or case_data.get("inputs", ""),
            "api_error_check_mode": case_data.get("api_error_check_mode")
            or source_case.get("api_error_check_mode", "normal"),
            "allowed_errors": case_data.get("allowed_errors")
            if case_data.get("allowed_errors") is not None
            else source_case.get("allowed_errors", []),
            "assert_type": case_data.get("assert_type", ""),
            "assert_value": case_data.get("assert_value")
            or case_data.get("expect_value", ""),
            "steps": cloned_steps,
        }
    )
    result["source_case_id"] = source_case_id
    return result


def list_public_step_actions_for_options(keyword="", page_code="", page=1, page_size=10):
    """给 /api/options 使用的公共动作查询入口，支持页面和关键字筛选。"""
    return case_repository().list_public_actions(
        keyword=keyword if keyword else None,
        page_code=page_code if page_code else None,
        page=page,
        page_size=page_size,
        with_pagination=True,
    )


def run_pipeline(case_id):
    return {
        "returncode": 0,
        "stdout": "Database storage mode: case saved to mt_cases / mt_case_steps. No Python flow generation is needed.",
        "stderr": "",
    }


def latest_report_link():
    latest = REPORTS_DIR / "latest"
    simple = latest / "simple_report.html"
    official = latest / "final_report" / "index.html"
    if simple.exists():
        return "/reports/latest/simple_report.html"
    if official.exists():
        return "/reports/latest/final_report/index.html"
    return ""


def report_info_from_dir(path):
    simple = path / "simple_report.html"
    official = path / "final_report" / "index.html"
    simple_url = f"/reports/{path.name}/simple_report.html" if simple.exists() else ""
    official_url = f"/reports/{path.name}/final_report/index.html" if official.exists() else ""
    updated_at = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    output_dir = path / "outputs"
    summary = read_output_summary(output_dir) or {}
    total = int(summary.get("total") or 0)
    passed = int(summary.get("passed") or 0)
    failed = int(summary.get("failed") or 0)
    return {
        "job_id": f"legacy_{path.name}",
        "case_id": "",
        "agent_id": "legacy",
        "name": path.name,
        "status": "failed" if failed else "success" if total else "",
        "updated_at": updated_at,
        "started_at": updated_at,
        "finished_at": updated_at,
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": int(summary.get("skipped") or 0),
        "simple_report": simple_url,
        "simple_report_path": str(simple) if simple.exists() else "",
        "official_report": official_url,
        "official_report_path": str(official) if official.exists() else "",
        "report_url": simple_url or official_url,
        "report_dir": str(path),
        "output_dir": str(output_dir) if output_dir.exists() else "",
        "result_summary": summary,
    }


def latest_archived_report(since_timestamp=None):
    if not REPORTS_DIR.exists():
        return {}

    report_dirs = [
        path
        for path in REPORTS_DIR.iterdir()
        if path.is_dir() and path.name.startswith("report_")
    ]
    if since_timestamp is not None:
        recent_dirs = [
            path
            for path in report_dirs
            if path.stat().st_mtime >= since_timestamp - 5
        ]
        if not recent_dirs:
            return {}
        report_dirs = recent_dirs

    if not report_dirs:
        return {}
    return report_info_from_dir(max(report_dirs, key=lambda path: path.stat().st_mtime))


def latest_output_dir(since_timestamp=None):
    outputs_dir = PROJECT_ROOT / "outputs"
    if not outputs_dir.exists():
        return None

    dirs = [
        path
        for path in outputs_dir.iterdir()
        if path.is_dir() and path.name.isdigit()
    ]
    if since_timestamp is not None:
        recent_dirs = [
            path
            for path in dirs
            if path.stat().st_mtime >= since_timestamp - 2
        ]
        if recent_dirs:
            dirs = recent_dirs

    if not dirs:
        return None
    return max(dirs, key=lambda path: path.stat().st_mtime)


def read_output_summary(output_dir):
    if not output_dir or not output_dir.exists():
        return None

    result_files = list(output_dir.glob("*/*/result.json"))
    if not result_files:
        return None

    total = 0
    passed = 0
    failed_cases = []
    for result_file in result_files:
        try:
            with open(result_file, "r", encoding="utf-8") as file:
                result = json.load(file)
        except Exception:
            continue

        total += 1
        if result.get("success"):
            passed += 1
        else:
            failed_cases.append(
                {
                    "case_name": result.get("case_name", ""),
                    "error_type": result.get("error_type", ""),
                    "error_value": result.get("error_value", ""),
                }
            )

    if total == 0:
        return None

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "failed_cases": failed_cases,
    }


def read_archived_latest_summary(started_at=None):
    latest_outputs = REPORTS_DIR / "latest" / "outputs"
    if not latest_outputs.exists():
        return None

    if started_at is not None:
        result_files = list(latest_outputs.glob("*/*/result.json"))
        has_recent_result = any(
            result_file.stat().st_mtime >= started_at - 5
            for result_file in result_files
        )
        if not has_recent_result:
            return None

    return read_output_summary(latest_outputs)


def infer_run_status(returncode, started_at):
    if returncode != 0:
        return "failed", None

    summary = read_archived_latest_summary(started_at)
    if not summary:
        summary = read_output_summary(latest_output_dir(started_at))

    if summary and summary["failed"] > 0:
        return "failed", summary
    if summary:
        return "success", summary
    return "success", None


def list_reports():
    try:
        reports = case_repository().list_report_records(limit=50)
        if reports:
            return reports
    except Exception as exc:
        print(f"[WARN] Failed to read MySQL reports, fallback to files: {exc}")

    return list_report_files()


def list_report_files():
    if not REPORTS_DIR.exists():
        return []

    reports = []
    for path in REPORTS_DIR.iterdir():
        if not path.is_dir() or not path.name.startswith("report_"):
            continue
        reports.append(report_info_from_dir(path))
    reports.sort(key=lambda item: item["updated_at"], reverse=True)
    return reports


def list_run_records():
    memory_jobs = list_jobs()
    try:
        records = case_repository().list_run_records(limit=50)
    except Exception as exc:
        print(f"[WARN] Failed to read MySQL run records, fallback to memory jobs: {exc}")
        return memory_jobs

    existing_job_ids = {record.get("job_id") for record in records}
    for job in memory_jobs:
        if job.get("job_id") not in existing_job_ids:
            records.insert(0, job)
    return records[:50]


def create_job(
    case_id="",
    title="",
    iteration_id=None,
    iteration_code="",
    iteration_name="",
    assigned_agent_ip="",
    assigned_agent_id="",
    trigger_type="manual",
    schedule_id=None,
):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = int(time.time() * 1000) % 1000
    job_id = f"job_{timestamp}_{suffix:03d}"
    assigned_agent_ip = str(assigned_agent_ip or "").strip()
    assigned_agent_id = str(assigned_agent_id or "").strip()
    trigger_type = str(trigger_type or "manual").strip().lower()
    if trigger_type not in {"manual", "schedule"}:
        trigger_type = "manual"
    if schedule_id not in (None, ""):
        trigger_type = "schedule"
    job = {
        "job_id": job_id,
        "case_id": case_id,
        "title": title,
        "iteration_id": iteration_id,
        "iteration_code": iteration_code,
        "iteration_name": iteration_name,
        "status": "queued",
        "trigger_type": trigger_type,
        "schedule_id": schedule_id,
        "assigned_agent_id": assigned_agent_id,
        "assigned_agent_ip": assigned_agent_ip,
        "agent_id": "",
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "report_url": "",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with RUN_JOBS_LOCK:
        RUN_JOBS[job_id] = job
    return job


def update_job(job_id, **updates):
    updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with RUN_JOBS_LOCK:
        RUN_JOBS[job_id].update(updates)
        return dict(RUN_JOBS[job_id])


def run_test_job(job_id, case_id="", iteration_id=None):
    started_at_db = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    agent_id = (
        os.environ.get("MINITEST_AGENT_ID")
        or os.environ.get("COMPUTERNAME")
        or os.environ.get("HOSTNAME")
        or "local"
    )
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    env.pop("MINITEST_CASE_ID", None)
    env.pop("MINITEST_ITERATION_ID", None)
    if case_id:
        env["MINITEST_CASE_ID"] = case_id
    elif iteration_id:
        env["MINITEST_ITERATION_ID"] = str(iteration_id)

    test_module = "cases.test_db_framework"
    command = [sys.executable, str(PROJECT_ROOT / "run.py"), test_module]
    update_job(
        job_id,
        status="running",
        started_at_db=started_at_db,
        agent_id=agent_id,
        command_text=" ".join(str(part) for part in command),
    )
    try:
        case_repository().insert_run_record(RUN_JOBS[job_id])
    except Exception as exc:
        print(f"[WARN] Failed to write running MySQL run record: {exc}")

    started_at = time.time()
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
    )
    stdout_text = decode_process_output(completed.stdout)
    stderr_text = decode_process_output(completed.stderr)
    status, summary = infer_run_status(completed.returncode, started_at)
    archived_report = latest_archived_report(started_at)
    latest_output = latest_output_dir(started_at)
    report_url = archived_report.get("report_url") or latest_report_link()
    finished_at_db = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    update_job(
        job_id,
        status=status,
        command_text=" ".join(str(part) for part in command),
        returncode=completed.returncode,
        stdout=stdout_text,
        stderr=stderr_text,
        result_summary=summary,
        report_url=report_url,
        report_name=archived_report.get("name", ""),
        simple_report_url=archived_report.get("simple_report", ""),
        simple_report_path=archived_report.get("simple_report_path", ""),
        official_report_url=archived_report.get("official_report", ""),
        official_report_path=archived_report.get("official_report_path", ""),
        report_dir=archived_report.get("report_dir", ""),
        output_dir=str(latest_output) if latest_output else "",
        duration_seconds=round(time.time() - started_at, 3),
        finished_at_db=finished_at_db,
    )
    try:
        case_repository().insert_run_record(RUN_JOBS[job_id])
    except Exception as exc:
        print(f"[WARN] Failed to write MySQL run record: {exc}")
    try:
        case_repository().insert_report_record(RUN_JOBS[job_id])
    except Exception as exc:
        print(f"[WARN] Failed to write MySQL report record: {exc}")


def start_test_run(
    case_id="",
    iteration_id=None,
    assigned_agent_ip="",
    assigned_agent_id="",
    trigger_type="manual",
    schedule_id=None,
):
    title = ""
    iteration_code = ""
    iteration_name = ""
    if iteration_id not in (None, ""):
        iteration = case_repository().get_iteration(iteration_id)
        iteration_id = iteration["iteration_id"]
        iteration_code = str(iteration.get("iteration_code") or "")
        iteration_name = str(iteration.get("iteration_name") or "")
        title = iteration_name
        enabled_cases = case_repository().list_test_cases(iteration_id=iteration_id)
        if not enabled_cases:
            raise ValueError("该迭代没有已启用的正式用例，无法执行")

    if case_id:
        for case in read_runtime_cases_all():
            if str(case.get("case_id", "")).strip() == str(case_id).strip():
                title = str(case.get("title", "") or "")
                break

    assigned_agent_ip = str(assigned_agent_ip or "").strip()
    assigned_agent_id = str(assigned_agent_id or "").strip()
    job = create_job(
        case_id=case_id,
        title=title,
        iteration_id=iteration_id,
        iteration_code=iteration_code,
        iteration_name=iteration_name,
        assigned_agent_ip=assigned_agent_ip,
        assigned_agent_id=assigned_agent_id,
        trigger_type=trigger_type,
        schedule_id=schedule_id,
    )
    if assigned_agent_ip or assigned_agent_id:
        target = assigned_agent_ip or assigned_agent_id
        job["command_text"] = f"等待执行机领取: {target}"
        try:
            case_repository().insert_run_record(job)
        except Exception as exc:
            with RUN_JOBS_LOCK:
                RUN_JOBS.pop(job["job_id"], None)
            raise RuntimeError(f"创建远程执行任务失败: {exc}") from exc
        return job

    thread = threading.Thread(
        target=run_test_job,
        args=(job["job_id"], case_id, iteration_id),
        daemon=True,
    )
    thread.start()
    return job


def list_jobs():
    with RUN_JOBS_LOCK:
        jobs = list(RUN_JOBS.values())
    jobs.sort(key=lambda item: item["created_at"], reverse=True)
    return jobs[:50]


def normalize_agent_ip(value, fallback=""):
    value = str(value or "").strip()
    return value or str(fallback or "").strip()


class CaseEditorHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def translate_path(self, path):
        """把前端路由、静态资源和报告 URL 映射到项目内的真实文件。"""
        parsed = urlparse(path)
        normalized_path = request_path(parsed.path)
        static_asset = STATIC_DIR / Path(normalized_path).name
        if static_asset.is_file() and Path(normalized_path).name in {
            "app.js",
            "case_form.js",
            "iteration_form.js",
            "style.css",
        }:
            return str(static_asset)
        if normalized_path in {"/", "/cases", "/cases/", "/iterations", "/iterations/"}:
            return str(STATIC_DIR / "index.html")
        if normalized_path in {"/cases/new", "/cases/edit"}:
            return str(STATIC_DIR / "case_form.html")
        if normalized_path in {"/iterations/new", "/iterations/edit"}:
            return str(STATIC_DIR / "iteration_form.html")
        if normalized_path in {
            "/public-actions",
            "/public-actions/",
            "/public-actions/new",
            "/public-actions/new/",
            "/public-actions/edit",
            "/public-actions/edit/",
        }:
            return str(STATIC_DIR / "index.html")
        if normalized_path.startswith("/reports/"):
            relative = normalized_path[len("/reports/"):].lstrip("/")
            target = (REPORTS_DIR / relative).resolve()
            reports_root = REPORTS_DIR.resolve()
            if target == reports_root or reports_root in target.parents:
                return str(target)
            return str(reports_root)
        return super().translate_path(normalized_path)

    def end_headers(self):
        # 同域部署不需要 CORS。只有明确配置可信来源时才发送跨域响应头，
        # 避免生产环境默认向任意网站开放管理 API。
        cors_origin = os.environ.get("MINITEST_CORS_ORIGIN", "").strip()
        if cors_origin:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_html(self, html, status=200):
        data = str(html or "").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        # GET 只提供查询接口、报告 HTML 与前端静态资源。
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        normalized_path = request_path(parsed.path)
        if normalized_path.startswith("/reports/db/") and normalized_path.endswith(".html"):
            try:
                job_id = unquote(Path(normalized_path).name[:-5])
                report = case_repository().get_report_html(job_id)
                return self.send_html(report["html"])
            except Exception as exc:
                return self.send_html(
                    f"<h1>Report not found</h1><pre>{str(exc)}</pre>",
                    status=404,
                )
        if normalized_path == "/api/runtime_cases":
            try:
                page = query.get("page", ["1"])[0]
                page_size = query.get("page_size", ["10"])[0]
                iteration_id = query.get("iteration_id", [""])[0]
                return self.send_json(
                    read_runtime_cases(
                        page=page,
                        page_size=page_size,
                        iteration_id=iteration_id or None,
                    )
                )
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, 500)
        if normalized_path == "/api/runtime_case_detail":
            try:
                case_id = query.get("case_id", [""])[0]
                return self.send_json({"case": read_runtime_case_detail(case_id)})
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, 500)
        if normalized_path == "/api/public_action_edit":
            try:
                public_action_id = query.get("public_action_id", query.get("id", [""]))[0]
                public_action = case_repository().get_public_action_detail(public_action_id, include_disabled=True)
                return self.send_json({"public_action": public_action})
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, 500)
        if normalized_path == "/api/run_record_detail":
            try:
                job_id = query.get("job_id", [""])[0]
                return self.send_json({"job": case_repository().get_run_record_detail(job_id)})
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, 500)
        if normalized_path == "/api/run_jobs":
            return self.send_json({"jobs": list_run_records(), "reports": list_reports()})
        if normalized_path == "/api/agents":
            try:
                return self.send_json(
                    {
                        "agents": case_repository().list_agents(),
                        # 前端据此决定是否展示远程执行机；关闭时只能选择中心机。
                        "remote_agents_enabled": remote_agents_enabled(),
                        # 远程执行专用中心服务会隐藏“中心机”选项。
                        "center_execution_enabled": center_execution_enabled(),
                    }
                )
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, 500)
        if normalized_path == "/api/iterations":
            try:
                page = query.get("page", ["1"])[0]
                page_size = query.get("page_size", ["10"])[0]
                include_deleted = truthy(query.get("include_deleted", ["0"])[0])
                return self.send_json(
                    case_repository().list_iterations(
                        page=page,
                        page_size=page_size,
                        include_deleted=include_deleted,
                        with_pagination=True,
                    )
                )
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, 500)
        if normalized_path == "/api/iteration_detail":
            try:
                iteration_id = query.get("iteration_id", query.get("id", [""]))[0]
                return self.send_json(
                    {
                        "iteration": case_repository().get_iteration(
                            iteration_id,
                            include_deleted=True,
                        )
                    }
                )
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, 500)
        if normalized_path == "/api/reports":
            try:
                page = positive_int(query.get("page", ["1"])[0], 1)
                page_size = positive_int(query.get("page_size", ["10"])[0], 10)
                return self.send_json(
                    case_repository().list_report_records(
                        page=page,
                        page_size=page_size,
                        with_pagination=True,
                    )
                )
            except Exception as exc:
                reports = list_report_files()
                return self.send_json(
                    {
                        "reports": reports,
                        "pagination": {
                            "page": 1,
                            "page_size": len(reports),
                            "limit": len(reports),
                            "offset": 0,
                            "total": len(reports),
                            "total_pages": 1,
                        },
                        "error": str(exc),
                    }
                )
        if normalized_path == "/api/options":
            # options 是前端的“基础配置接口”：
            # 1. 用例编辑页用它填充步骤动作、定位方式、公共动作下拉
            # 2. 公共动作库用它加载公共动作列表，也可带 keyword/page_code 做筛选
            keyword = query.get("keyword", [""])[0]
            page_code = query.get("page_code", [""])[0]
            page = positive_int(query.get("page", ["1"])[0], 1)
            page_size = positive_int(query.get("page_size", ["10"])[0], 10)
            option_errors = {}
            public_step_actions_pagination = {
                "page": page,
                "page_size": page_size,
                "limit": page_size,
                "offset": (page - 1) * page_size,
                "total": 0,
                "total_pages": 1,
            }
            try:
                public_action_result = list_public_step_actions_for_options(
                    keyword=keyword,
                    page_code=page_code,
                    page=page,
                    page_size=page_size,
                )
                public_actions = public_action_result.get("actions", [])
                public_step_actions_pagination = public_action_result.get(
                    "pagination",
                    public_step_actions_pagination,
                )
            except Exception as exc:
                public_actions = []
                # 不让一个局部查询失败拖垮整个 options 接口，但把错误返回给前端日志。
                option_errors["public_step_actions"] = str(exc)
            try:
                page_options = public_action_page_options()
            except Exception as exc:
                page_options = []
                # 页面枚举失败时，前端仍可展示其他 options，错误会显示在日志里。
                option_errors["page_options"] = str(exc)
            try:
                # 编辑用例时需要完整迭代下拉，不能跟随公共动作列表分页。
                iteration_options = case_repository().list_iterations()
            except Exception as exc:
                iteration_options = []
                option_errors["iteration_options"] = str(exc)
            reusable_cases = list_reusable_cases()
            return self.send_json(
                {
                    "server_version": SERVER_VERSION,
                    "storage": "mysql",
                    "step_actions": [
                        "open_url",
                        "click",
                        "optional_click",
                        "click_first",
                        "wait_element",
                        "click_if_text",
                        "random_click",
                        "random_click_until_not_exists",
                        "retry_click_until_not_exists",
                        "input",
                        "wait",
                        "element_exists",
                        "get_text",
                        "exist_page",
                    ],
                    "locator_methods": ["", "text", "class", "class_text", "src", "xpath"],
                    "assert_types": ["element_exists", "exist_page"],
                    "page_options": page_options,
                    "iteration_options": iteration_options,
                    "reusable_cases": reusable_cases,
                    # page_options 是页面枚举；public_step_actions_pagination 才是公共动作列表的分页/limit 信息。
                    "public_step_actions_pagination": public_step_actions_pagination,
                    # 兼容旧前端字段名，后续可以删掉。
                    "public_action_pagination": public_step_actions_pagination,
                    "public_step_actions": public_actions,
                    "errors": option_errors,
                }
            )
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        normalized_path = request_path(parsed.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        # 前端 JSON.stringify(data) 发送的请求体会在这里还原为 Python 字典。
        payload = json.loads(raw or "{}")

        try:
            if normalized_path == "/api/runtime_case":
                result = write_runtime_case(payload)
                return self.send_json({"ok": True, "result": result})
            if normalized_path == "/api/runtime_case_edit":
                result = edit_runtime_case(payload)
                return self.send_json({"ok": True, "result": result})
            if normalized_path == "/api/runtime_case_enabled":
                result = case_repository().set_case_enabled(
                    payload.get("case_id"),
                    payload.get("enabled"),
                )
                return self.send_json({"ok": True, "result": result})
            if normalized_path == "/api/public_action":
                result = case_repository().upsert_public_action(payload)
                return self.send_json({"ok": True, "result": result})
            if normalized_path == "/api/public_action_page":
                result = case_repository().upsert_public_action_page(payload)
                return self.send_json({"ok": True, "result": result})
            if normalized_path == "/api/iterations":
                result = case_repository().upsert_iteration(payload)
                return self.send_json({"ok": True, "result": result})
            if normalized_path == "/api/pipeline":
                case_id = str(payload.get("case_id", "")).strip()
                if not case_id:
                    return self.send_json({"ok": False, "error": "case_id is required"}, 400)
                result = run_pipeline(case_id)
                return self.send_json({"ok": result["returncode"] == 0, "result": result})
            if normalized_path == "/api/run_case":
                case_id = str(payload.get("case_id", "")).strip()
                assigned_agent_ip = ""
                assigned_agent_id = ""
                requested_agent_id = payload.get("agent_id") or payload.get("assigned_agent_id")
                requested_agent_ip = payload.get("agent_ip") or payload.get("assigned_agent_ip")
                if (requested_agent_id or requested_agent_ip) and not remote_agents_enabled():
                    return self.send_json(
                        {"ok": False, "error": "远程执行机未启用，请在中心服务 .env 设置 MINITEST_ENABLE_REMOTE_AGENTS=true"},
                        400,
                    )
                if not (requested_agent_id or requested_agent_ip) and not center_execution_enabled():
                    return self.send_json(
                        {"ok": False, "error": "中心机执行已禁用，请选择一台远程执行机"},
                        400,
                    )
                if remote_agents_enabled():
                    assigned_agent_ip = requested_agent_ip
                    assigned_agent_id = requested_agent_id
                job = start_test_run(
                    case_id,
                    assigned_agent_ip=assigned_agent_ip,
                    assigned_agent_id=assigned_agent_id,
                    trigger_type="manual",
                )
                return self.send_json({"ok": True, "job": job})
            if normalized_path == "/api/run_iteration":
                iteration_id = payload.get("iteration_id")
                assigned_agent_ip = ""
                assigned_agent_id = ""
                requested_agent_id = payload.get("agent_id") or payload.get("assigned_agent_id")
                requested_agent_ip = payload.get("agent_ip") or payload.get("assigned_agent_ip")
                if (requested_agent_id or requested_agent_ip) and not remote_agents_enabled():
                    return self.send_json(
                        {"ok": False, "error": "远程执行机未启用，请在中心服务 .env 设置 MINITEST_ENABLE_REMOTE_AGENTS=true"},
                        400,
                    )
                if not (requested_agent_id or requested_agent_ip) and not center_execution_enabled():
                    return self.send_json(
                        {"ok": False, "error": "中心机执行已禁用，请选择一台远程执行机"},
                        400,
                    )
                if remote_agents_enabled():
                    assigned_agent_ip = requested_agent_ip
                    assigned_agent_id = requested_agent_id
                job = start_test_run(
                    iteration_id=iteration_id,
                    assigned_agent_ip=assigned_agent_ip,
                    assigned_agent_id=assigned_agent_id,
                    trigger_type="manual",
                )
                return self.send_json({"ok": True, "job": job})
            if normalized_path == "/api/iteration/delete":
                iteration_id = payload.get("iteration_id")
                result = case_repository().delete_iteration(iteration_id)
                return self.send_json(
                    {
                        "ok": True,
                    "result": result,
                    }
                    )
            if normalized_path == "/api/agent/heartbeat":
                agent_id = str(payload.get("agent_id") or "").strip()
                if not agent_id:
                    return self.send_json({"ok": False, "error": "agent_id is required"}, 400)
                payload["agent_ip"] = normalize_agent_ip(
                    payload.get("agent_ip") or payload.get("ip"),
                    self.client_address[0],
                )
                result = case_repository().upsert_agent(payload)
                return self.send_json({"ok": True, "agent": result})
            if normalized_path == "/api/agent/claim":
                agent_id = str(payload.get("agent_id") or "").strip()
                if not agent_id:
                    return self.send_json({"ok": False, "error": "agent_id is required"}, 400)
                agent_ip = normalize_agent_ip(
                    payload.get("agent_ip") or payload.get("ip"),
                    self.client_address[0],
                )
                case_repository().upsert_agent(
                    {
                        "agent_id": agent_id,
                        "agent_name": payload.get("agent_name") or payload.get("name") or agent_id,
                        "agent_ip": agent_ip,
                        "status": "online",
                    }
                )
                job = case_repository().claim_next_job(agent_id=agent_id, agent_ip=agent_ip)
                return self.send_json({"ok": True, "job": job})
            if normalized_path == "/api/agent/report":
                job = payload.get("job") if isinstance(payload.get("job"), dict) else payload
                job_id = str(job.get("job_id") or "").strip()
                if not job_id:
                    return self.send_json({"ok": False, "error": "job_id is required"}, 400)
                agent_id = str(job.get("agent_id") or payload.get("agent_id") or "").strip()
                if agent_id:
                    job["agent_id"] = agent_id
                job["assigned_agent_ip"] = str(
                    job.get("assigned_agent_ip") or payload.get("assigned_agent_ip") or ""
                ).strip()
                job["assigned_agent_id"] = str(
                    job.get("assigned_agent_id") or payload.get("assigned_agent_id") or ""
                ).strip()
                case_repository().insert_run_record(job)
                if str(job.get("status") or "").strip() in {"success", "failed"}:
                    case_repository().insert_report_record(job)
                    if agent_id:
                        case_repository().finish_agent_job(agent_id, job_id, status="online")
                with RUN_JOBS_LOCK:
                    if job_id in RUN_JOBS:
                        RUN_JOBS[job_id].update(job)
                return self.send_json({"ok": True, "job": job})
        except Exception as exc:
            return self.send_json({"ok": False, "error": str(exc)}, 500)

        return self.send_json({"ok": False, "error": "Not found"}, 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        normalized_path = request_path(parsed.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        # PUT 目前用于编辑公共动作，保持与新增 POST 的语义区分。
        payload = json.loads(raw or "{}")

        try:
            if normalized_path == "/api/public_action_edit":
                public_action_id = str(
                    payload.get("public_action_id") or payload.get("id") or ""
                ).strip()
                if not public_action_id:
                    return self.send_json({"ok": False, "error": "public_action_id is required"}, 400)
                payload["public_action_id"] = public_action_id
                result = case_repository().upsert_public_action(payload)
                return self.send_json({"ok": True, "result": result})
        except Exception as exc:
            return self.send_json({"ok": False, "error": str(exc)}, 500)

        return self.send_json({"ok": False, "error": "Not found"}, 404)


def main():
    global URL_PREFIX
    import argparse

    parser = argparse.ArgumentParser(description="Run local HTML case editor.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--url-prefix",
        default=os.environ.get("MINITEST_URL_PREFIX", ""),
        help="Optional mount prefix, for example /minitest.",
    )
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    URL_PREFIX = normalize_url_prefix(args.url_prefix)

    # 仅启动管理站，不会在这里启动小程序开发者工具。
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), CaseEditorHandler)
    url = f"http://{args.host}:{args.port}{URL_PREFIX or ''}/cases"
    print(f"Case editor: {url}")
    if URL_PREFIX:
        print(f"URL prefix: {URL_PREFIX}")
    print("Press Ctrl+C to stop.")
    if not args.no_open:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
