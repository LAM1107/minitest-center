"""MySQL 数据访问层。

这里仅负责把页面/API 数据读写到数据库；不包含小程序页面操作。
执行动作的解释逻辑在 ``step_executor.py``，这样数据存储与执行能力保持分离。
"""

import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


TRUTHY = {"1", "true", "yes", "y", "on", "mysql", "db"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK_INPUT_KEYS = {"ignore_error", "allowed_errors"}
API_ERROR_CHECK_MODES = {"normal", "allow_list"}
ITERATION_STATUSES = {"planning", "active", "completed", "archived"}


def load_project_env():
    """从项目根目录的 .env 注入未设置的环境变量。

    .env 只存在于部署机或开发机，不能提交到 Git。已有系统环境变量优先，
    方便 Docker、systemd 或 CI 直接注入数据库密码。
    """
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


load_project_env()

def is_mysql_storage_enabled():
    return os.environ.get("MINITEST_STORAGE", "").strip().lower() in TRUTHY


def _clean(value):
    return "" if value is None else str(value).strip()


def public_action_page_options():
    return MySqlCaseRepository().list_public_action_pages()


def public_action_page_title(page_code):
    return MySqlCaseRepository().get_public_action_page_title(page_code)


def normalize_public_operation(operation):
    operation = _clean(operation or "click")
    return "element_exists" if operation == "exists" else operation


def _json_dumps(value):
    return json.dumps(value or [], ensure_ascii=False)


def _json_loads(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _enabled_flag(value, default=1):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    return 0 if str(value).strip().lower() in {"0", "false", "no", "n", "off"} else 1


def _trigger_type(value):
    value = _clean(value or "manual").lower()
    return value if value in {"manual", "schedule"} else "manual"


def _schedule_id_or_none(value):
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _optional_id(value, field_name="id"):
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if number <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return number


def _case_id_list(value):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        values = (
            value.replace("\r", "\n")
            .replace("|", "\n")
            .replace(",", "\n")
            .split("\n")
        )
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]

    result = []
    seen = set()
    for item in values:
        case_id = _clean(item)
        if not case_id or case_id in seen:
            continue
        seen.add(case_id)
        result.append(case_id)
    return result


def _date_text_or_none(value, field_name):
    value = _clean(value)
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def _positive_int(value, default, maximum=200):
    try:
        number = int(value or default)
    except (TypeError, ValueError):
        number = default
    number = max(number, 1)
    if maximum:
        number = min(number, maximum)
    return number


def _json_dumps_or_none(value):
    if value in (None, ""):
        return None
    return json.dumps(value, ensure_ascii=False)


def _datetime_text(value):
    if value in (None, ""):
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _int_value(value, default=0):
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _float_value_or_none(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _report_html_from_job(job):
    html = job.get("simple_report_html") or job.get("report_html")
    if html:
        return str(html)

    candidates = []
    for key in ("simple_report_path", "report_html_path"):
        value = _clean(job.get(key))
        if value:
            candidates.append(Path(value))

    report_dir = _clean(job.get("report_dir"))
    if report_dir:
        candidates.append(Path(report_dir) / "simple_report.html")

    for path in candidates:
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return ""


def _driver():
    try:
        import pymysql

        return "pymysql", pymysql
    except ImportError:
        pass

    try:
        import mysql.connector

        return "mysql_connector", mysql.connector
    except ImportError as exc:
        raise RuntimeError(
            "MySQL driver is missing. Install one of: pip install pymysql, "
            "or pip install mysql-connector-python"
        ) from exc


def _validate_mysql_config(config):
    if config.get("password") == "your_mysql_password":
        raise RuntimeError(
            "MINITEST_DB_PASSWORD is still the placeholder value. "
            "Please update D:\\project\\minitest\\.env with your real MySQL password, "
            "then restart tools\\case_editor_server.py."
        )


def _split_csv_inputs(inputs):
    if not inputs:
        return {}
    text = str(inputs).strip()
    if not text:
        return {}
    if text.startswith("{"):
        return json.loads(text)

    result = {}
    for item in text.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if key:
            result[key] = value.strip().strip("'\"")
    return result


def _format_csv_inputs(params):
    return ",".join(f"{key}={value}" for key, value in params.items() if _clean(key))


def _business_inputs_text(inputs):
    params = {
        str(key): "" if value is None else str(value)
        for key, value in _split_csv_inputs(inputs).items()
        if str(key) not in FRAMEWORK_INPUT_KEYS
    }
    return _format_csv_inputs(params)


def split_allowed_errors(value):
    value = _clean(value)
    if not value:
        return []

    errors = []
    for part in value.replace("\n", "|").replace(",", "|").split("|"):
        part = part.strip().strip("'\"")
        if part and part not in errors:
            errors.append(part)
    return errors


def normalize_allowed_errors(value):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        loaded = _json_loads(value, None)
        if loaded is not None:
            return normalize_allowed_errors(loaded)
        return split_allowed_errors(value)
    if isinstance(value, dict):
        return normalize_allowed_errors(list(value.values()))
    if isinstance(value, (list, tuple, set)):
        errors = []
        for item in value:
            for part in split_allowed_errors(item):
                if part not in errors:
                    errors.append(part)
        return errors
    return split_allowed_errors(value)


def resolve_api_error_policy(case_data):
    legacy_params = _split_csv_inputs(case_data.get("inputs") or case_data.get("params") or "")
    explicit_allowed = normalize_allowed_errors(case_data.get("allowed_errors"))
    legacy_allowed = split_allowed_errors(legacy_params.get("allowed_errors"))
    allowed_errors = explicit_allowed or legacy_allowed

    mode = _clean(case_data.get("api_error_check_mode")).lower()
    if legacy_allowed and not explicit_allowed:
        mode = "allow_list"
    elif mode not in API_ERROR_CHECK_MODES:
        mode = "allow_list" if allowed_errors else "normal"

    if mode == "normal":
        allowed_errors = []

    return mode, allowed_errors


class MySqlCaseRepository:
    """Minitest 数据库仓储：集中管理用例、步骤、报告及执行记录的读写。"""

    def __init__(self, config=None):
        self.config = config or self.config_from_env()

    @staticmethod
    def config_from_env():
        return {
            "host": os.environ.get("MINITEST_DB_HOST", "127.0.0.1"),
            "port": int(os.environ.get("MINITEST_DB_PORT", "3306")),
            "user": os.environ.get("MINITEST_DB_USER", "root"),
            "password": os.environ.get("MINITEST_DB_PASSWORD", ""),
            "database": os.environ.get("MINITEST_DB_NAME", "minitest"),
        }

    @contextmanager
    def connect(self):
        """提供一次数据库事务；正常结束提交，任意异常自动回滚。"""
        _validate_mysql_config(self.config)
        driver_name, module = _driver()
        if driver_name == "pymysql":
            conn = module.connect(
                host=self.config["host"],
                port=self.config["port"],
                user=self.config["user"],
                password=self.config["password"],
                database=self.config["database"],
                charset="utf8mb4",
                cursorclass=module.cursors.DictCursor,
                autocommit=False,
            )
            cursor = conn.cursor()
        else:
            conn = module.connect(
                host=self.config["host"],
                port=self.config["port"],
                user=self.config["user"],
                password=self.config["password"],
                database=self.config["database"],
                charset="utf8mb4",
                use_unicode=True,
            )
            cursor = conn.cursor(dictionary=True)

        try:
            # 调用方在 with 块中可以连续执行多条 SQL，最终统一提交。
            yield conn, cursor
            conn.commit()
        except Exception:
            # 公共动作/用例步骤保存是多表操作，失败时不能留下半份数据。
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

    def list_iterations(
        self,
        page=None,
        page_size=None,
        include_deleted=False,
        with_pagination=False,
    ):
        use_pagination = page is not None or page_size is not None or with_pagination
        if use_pagination:
            page = _positive_int(page, 1)
            page_size = _positive_int(page_size, 10, maximum=200)
            offset = (page - 1) * page_size

        where_sql = "" if include_deleted else "WHERE deleted_at IS NULL"
        with self.connect() as (_, cursor):
            total = 0
            if use_pagination:
                cursor.execute(
                    f"SELECT COUNT(*) AS total FROM mt_iteration {where_sql}"
                )
                total = _int_value((cursor.fetchone() or {}).get("total"))

            limit_clause = "LIMIT %s OFFSET %s" if use_pagination else ""
            cursor.execute(
                f"""
                SELECT id AS iteration_id, iteration_code, iteration_name,
                       status, start_date, end_date, description,
                       created_at, updated_at, deleted_at,
                       (
                         SELECT COUNT(*)
                         FROM mt_cases c
                         WHERE c.iteration_id = mt_iteration.id
                       ) AS case_count
                FROM mt_iteration
                {where_sql}
                ORDER BY
                    FIELD(status, 'active', 'planning', 'completed', 'archived'),
                    COALESCE(start_date, '1000-01-01') DESC,
                    id DESC
                {limit_clause}
                """,
                (page_size, offset) if use_pagination else (),
            )
            rows = list(cursor.fetchall())

        for row in rows:
            for field in ("start_date", "end_date", "created_at", "updated_at", "deleted_at"):
                row[field] = _datetime_text(row.get(field))

        if not use_pagination:
            return rows

        total_pages = (total + page_size - 1) // page_size if total else 1
        return {
            "iterations": rows,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            }
        }

    def get_iteration(self, iteration_id, include_deleted=False):
        iteration_id = _optional_id(iteration_id, "iteration_id")
        where_deleted = "" if include_deleted else "AND deleted_at IS NULL"
        with self.connect() as (_, cursor):
            cursor.execute(
                f"""
                SELECT id AS iteration_id, iteration_code, iteration_name,
                       status, start_date, end_date, description,
                       created_at, updated_at, deleted_at
                FROM mt_iteration
                WHERE id = %s {where_deleted}
                """,
                (iteration_id,),
            )
            row = cursor.fetchone()
            if row:
                cursor.execute(
                    """
                    SELECT case_id
                    FROM mt_cases
                    WHERE iteration_id = %s
                    ORDER BY sort_order ASC, id ASC
                    """,
                    (iteration_id,),
                )
                row["case_ids"] = [
                    _clean(case.get("case_id"))
                    for case in cursor.fetchall()
                    if _clean(case.get("case_id"))
                ]

        if not row:
            raise ValueError(f"iteration not found: {iteration_id}")
        for field in ("start_date", "end_date", "created_at", "updated_at", "deleted_at"):
            row[field] = _datetime_text(row.get(field))
        return row

    def upsert_iteration(self, iteration_data):
        iteration_id = _optional_id(iteration_data.get("iteration_id"), "iteration_id")
        iteration_code = _clean(iteration_data.get("iteration_code"))
        iteration_name = _clean(iteration_data.get("iteration_name"))
        status = _clean(iteration_data.get("status") or "planning").lower()
        has_case_ids = "case_ids" in iteration_data
        case_ids = _case_id_list(iteration_data.get("case_ids")) if has_case_ids else []
        if not iteration_code:
            raise ValueError("iteration_code is required")
        if not iteration_name:
            raise ValueError("iteration_name is required")
        if status not in ITERATION_STATUSES:
            raise ValueError(
                "status must be one of: planning, active, completed, archived"
            )

        start_date = _date_text_or_none(iteration_data.get("start_date"), "start_date")
        end_date = _date_text_or_none(iteration_data.get("end_date"), "end_date")
        if start_date and end_date and start_date > end_date:
            raise ValueError("end_date must not be earlier than start_date")

        with self.connect() as (_, cursor):
            if iteration_id:
                cursor.execute(
                    "SELECT id FROM mt_iteration WHERE id = %s",
                    (iteration_id,),
                )
                if not cursor.fetchone():
                    raise ValueError(f"iteration not found: {iteration_id}")
                cursor.execute(
                    """
                    UPDATE mt_iteration
                    SET iteration_code = %s,
                        iteration_name = %s,
                        status = %s,
                        start_date = %s,
                        end_date = %s,
                        description = %s,
                        deleted_at = NULL
                    WHERE id = %s
                    """,
                    (
                        iteration_code,
                        iteration_name,
                        status,
                        start_date,
                        end_date,
                        _clean(iteration_data.get("description")) or None,
                        iteration_id,
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO mt_iteration (
                        iteration_code, iteration_name, status,
                        start_date, end_date, description
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        iteration_code,
                        iteration_name,
                        status,
                        start_date,
                        end_date,
                        _clean(iteration_data.get("description")) or None,
                    ),
                )
                iteration_id = int(cursor.lastrowid)

            if has_case_ids:
                if case_ids:
                    placeholders = ", ".join(["%s"] * len(case_ids))
                    cursor.execute(
                        f"""
                        SELECT case_id
                        FROM mt_cases
                        WHERE case_id IN ({placeholders})
                        """,
                        case_ids,
                    )
                    existing_case_ids = {
                        _clean(row.get("case_id")) for row in cursor.fetchall()
                    }
                    missing_case_ids = [
                        case_id for case_id in case_ids if case_id not in existing_case_ids
                    ]
                    if missing_case_ids:
                        raise ValueError(
                            f"case not found: {', '.join(missing_case_ids)}"
                        )

                    cursor.execute(
                        f"""
                        UPDATE mt_cases
                        SET iteration_id = NULL
                        WHERE iteration_id = %s
                          AND case_id NOT IN ({placeholders})
                        """,
                        (iteration_id, *case_ids),
                    )
                    cursor.execute(
                        f"""
                        UPDATE mt_cases
                        SET iteration_id = %s
                        WHERE case_id IN ({placeholders})
                        """,
                        (iteration_id, *case_ids),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE mt_cases
                        SET iteration_id = NULL
                        WHERE iteration_id = %s
                        """,
                        (iteration_id,),
                    )

        return self.get_iteration(iteration_id, include_deleted=True)

    def list_editor_cases(self):
        cases = self.list_test_cases(include_disabled=True)
        editor_cases = []
        for case in cases:
            if case.get("case_mode") != "steps":
                continue
            item = dict(case)
            item["case_mode"] = "generate"
            item["params"] = item.get("inputs", "")
            item["assert_value"] = item.get("expect_value", "")
            editor_cases.append(item)
        return editor_cases

    def list_runtime_cases(self):
        rows = self.list_test_cases(include_disabled=True)
        runtime_cases = []
        for row in rows:
            runtime_cases.append(self._runtime_case_summary(row, len(row.get("steps") or [])))
        return runtime_cases

    def list_runtime_cases_page(self, page=1, page_size=10, iteration_id=None):
        page = max(int(page or 1), 1)
        page_size = min(max(int(page_size or 10), 1), 200)
        offset = (page - 1) * page_size
        iteration_id = _optional_id(iteration_id, "iteration_id")
        where_sql = "WHERE c.iteration_id = %s" if iteration_id else ""
        query_params = [iteration_id] if iteration_id else []

        with self.connect() as (_, cursor):
            cursor.execute(
                f"SELECT COUNT(*) AS total FROM mt_cases c {where_sql}",
                query_params,
            )
            total = int((cursor.fetchone() or {}).get("total") or 0)
            cursor.execute(
                f"""
                SELECT c.case_id, c.title, c.case_mode, c.flow_group_hint, c.action,
                       c.inputs, c.api_error_check_mode, c.allowed_errors,
                       c.assert_type, c.expect_value, c.enabled, c.sort_order,
                       c.iteration_id, i.iteration_code, i.iteration_name,
                       (
                         SELECT COUNT(*)
                         FROM mt_case_steps s
                         WHERE s.case_id = c.case_id AND s.enabled = 1
                       ) AS steps_count
                FROM mt_cases c
                LEFT JOIN mt_iteration i ON i.id = c.iteration_id
                {where_sql}
                ORDER BY c.sort_order ASC, c.id ASC
                LIMIT %s OFFSET %s
                """,
                (*query_params, page_size, offset),
            )
            rows = list(cursor.fetchall())

        cases = [
            self._runtime_case_summary(row, int(row.get("steps_count") or 0))
            for row in rows
        ]
        total_pages = (total + page_size - 1) // page_size if total else 1
        return {
            "cases": cases,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            },
        }

    def _runtime_case_summary(self, row, steps_count=0):

        return {
            "case_id": row["case_id"],
            "title": row.get("title", ""),
            "inputs": row.get("inputs", ""),
            "api_error_check_mode": resolve_api_error_policy(row)[0],
            "allowed_errors": resolve_api_error_policy(row)[1],
            "assert_type": row.get("assert_type", ""),
            "expect_value": row.get("expect_value", ""),
            "case_mode": row.get("case_mode", ""),
            "steps_count": steps_count,
            "enabled": row.get("enabled", 1),
            "iteration_id": row.get("iteration_id"),
            "iteration_code": row.get("iteration_code", ""),
            "iteration_name": row.get("iteration_name", ""),
        }

    def list_public_action_pages(self, include_disabled=False):
        where = "" if include_disabled else "WHERE enabled = 1"
        with self.connect() as (_, cursor):
            cursor.execute(
                f"""
                SELECT id, page_code, page_title, description,
                       enabled, sort_order
                FROM mt_public_action_pages
                {where}
                ORDER BY sort_order ASC, id ASC, page_code ASC
                """
            )
            return list(cursor.fetchall())

    def get_public_action_page_title(self, page_code):
        page_code = _clean(page_code)
        if not page_code:
            return ""

        with self.connect() as (_, cursor):
            cursor.execute(
                """
                SELECT page_title
                FROM mt_public_action_pages
                WHERE page_code = %s AND enabled = 1
                """,
                (page_code,),
            )
            row = cursor.fetchone()

        return _clean((row or {}).get("page_title")) or page_code

    def upsert_public_action_page(self, page_data):
        page_code = _clean(page_data.get("page_code"))
        page_title = _clean(page_data.get("page_title"))
        if not page_code:
            raise ValueError("page_code is required")
        if not page_title:
            raise ValueError("page_title is required")

        enabled = _enabled_flag(page_data.get("enabled"))
        sort_order = int(page_data.get("sort_order") or 0)
        with self.connect() as (_, cursor):
            cursor.execute(
                """
                INSERT INTO mt_public_action_pages (
                    page_code, page_title, description, enabled, sort_order
                ) VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    page_title = VALUES(page_title),
                    description = VALUES(description),
                    enabled = VALUES(enabled),
                    sort_order = VALUES(sort_order)
                """,
                (
                    page_code,
                    page_title,
                    _clean(page_data.get("description")),
                    enabled,
                    sort_order,
                ),
            )

        return {
            "page_code": page_code,
            "page_title": page_title,
            "storage": "mysql",
            "enabled": enabled,
            "sort_order": sort_order,
        }

    def list_public_actions(
        self,
        include_disabled=False,
        keyword=None,
        page_code=None,
        page_name=None,
        page=None,
        page_size=None,
        with_pagination=False,
    ):
        """查询公共动作列表，供 HTML 公共动作库和用例步骤下拉框使用。"""
        page_code = _clean(page_code or page_name)
        keyword = _clean(keyword)
        conditions = []
        params = []
        use_pagination = page is not None or page_size is not None or with_pagination
        if use_pagination:
            page = _positive_int(page, 1)
            page_size = _positive_int(page_size, 10)
            offset = (page - 1) * page_size

        # 默认只展示启用的公共动作；编辑详情页需要查禁用数据时再显式放开。
        if not include_disabled:
            conditions.append("a.enabled = 1")

        # 页面筛选来自 HTML 的“所属页面”下拉，例如 front / mine / backpack。
        if page_code:
            conditions.append("a.page_code = %s")
            params.append(page_code)

        if keyword:
            kw = f"%{keyword}%"
            step_enabled_where = "" if include_disabled else "AND s_kw.enabled = 1"
            # 搜索不只查公共动作主表，也查步骤表里的定位方式、定位值和备注。
            # 这样输入“我的”“close-icon”“goods_name”都能找到对应公共动作。
            conditions.append(
                f"""
                (
                    a.action_name LIKE %s
                    OR a.description LIKE %s
                    OR CAST(a.params_json AS CHAR) LIKE %s
                    OR CAST(a.aliases_json AS CHAR) LIKE %s
                    OR a.page_code LIKE %s
                    OR COALESCE(NULLIF(p.page_title, ''), NULLIF(a.page_title, ''), '') LIKE %s
                    OR EXISTS (
                        SELECT 1
                        FROM mt_public_action_steps s_kw
                        WHERE s_kw.public_action_id = a.id
                          {step_enabled_where}
                          AND (
                              s_kw.step_action LIKE %s
                              OR s_kw.locator_method LIKE %s
                              OR s_kw.locator_value LIKE %s
                              OR s_kw.locator_options LIKE %s
                              OR s_kw.step_value LIKE %s
                              OR s_kw.remark LIKE %s
                          )
                    )
                )
                """
            )
            # 上面的 SQL 一共有 12 个 LIKE 占位符，统一绑定同一个模糊搜索值。
            params.extend([kw] * 12)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        limit_clause = "LIMIT %s OFFSET %s" if use_pagination else ""
        with self.connect() as (_, cursor):
            total = 0
            if use_pagination:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS total
                    FROM mt_public_actions a
                    LEFT JOIN mt_public_action_pages p
                      ON p.page_code = a.page_code AND p.enabled = 1
                    {where}
                    """,
                    params,
                )
                total = int((cursor.fetchone() or {}).get("total") or 0)


            # 主表只保存“公共动作是什么”；步骤明细下面再按 action_id 批量查。
            cursor.execute(
                f"""
                SELECT a.id,
                       a.page_code,
                       COALESCE(NULLIF(p.page_title, ''), NULLIF(a.page_title, ''), a.page_code) AS page_title,
                       a.action_name,
                       a.description,
                       a.params_json,
                       a.aliases_json,
                       a.enabled,
                       a.sort_order
                FROM mt_public_actions a
                LEFT JOIN mt_public_action_pages p
                  ON p.page_code = a.page_code AND p.enabled = 1
                {where}
                ORDER BY COALESCE(p.sort_order, 999999) ASC,
                         a.page_code ASC,
                         a.sort_order ASC,
                         a.id ASC
                         {limit_clause}
                """,
                params + ([page_size, offset] if use_pagination else []),
            )
            actions = list(cursor.fetchall())

            if not actions:
                if with_pagination:
                    return {
                        "actions": [],
                        "pagination": {
                            "page": page,
                            "page_size": page_size,
                            "limit": page_size,
                            "offset": offset,
                            "total": total,
                            "total_pages": (total + page_size - 1) // page_size if total else 1,
                        },
                    }
                return []

            action_ids = [item["id"] for item in actions]
            placeholders = ", ".join(["%s"] * len(action_ids))
            # 一次性查出所有公共动作的步骤，避免列表里每条动作都单独查一次数据库。
            cursor.execute(
                f"""
                SELECT public_action_id, step_order, step_action, locator_method,
                       locator_value, locator_options, step_value,
                       condition_type, condition_locator_method,
                       condition_locator_value, condition_options,
                       child_public_action_id, remark, enabled
                FROM mt_public_action_steps
                WHERE public_action_id IN ({placeholders}) AND enabled = 1
                ORDER BY public_action_id ASC, step_order ASC
                """,
                action_ids,
            )
            steps_by_action = {}
            for step in cursor.fetchall():
                steps_by_action.setdefault(step["public_action_id"], []).append(step)

        result = []
        total_pages = (total + page_size - 1) // page_size if use_pagination and total else 1

        for row in actions:
            steps = steps_by_action.get(row["id"], [])
            desc = row.get("description") or row.get("action_name") or ""

            result.append(
                {
                    "id": row.get("id"),
                    "public_action_id": row.get("id"),
                    "action": str(row.get("id")),
                    "target": row.get("page_code", ""),
                    "method": row.get("action_name", ""),
                    "page_code": row.get("page_code", ""),
                    "page_title": row.get("page_title", ""),
                    "params": _json_loads(row.get("params_json"), []),
                    "aliases": _json_loads(row.get("aliases_json"), []),
                    "desc": desc,
                    "title": row.get("action_name", ""),
                    "steps": steps,
                    "first_step": steps[0] if steps else {},
                    "source_file": f"database/{row.get('page_code') or 'common'}",
                    "source_name": row.get("page_title") or "mt_public_actions",
                    "source_group": row.get("page_title") or row.get("page_code") or "数据库公共动作",
                    "enabled": row.get("enabled", 1),
                }
            )

        if with_pagination:
            return {
                "actions": result,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "limit": page_size,
                    "offset": offset,
                    "total": total,
                    "total_pages": total_pages,
                },
            }
        return result


    def delete_iteration(self, iteration_id):
        iteration_id = _clean(iteration_id)
        if not iteration_id:
            raise ValueError("iteration_id is required")

        with self.connect() as (_, cursor):
            cursor.execute(
                "UPDATE mt_iteration SET deleted_at = NOW() WHERE id = %s",
                (int(iteration_id),),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Iteration not found: {iteration_id}")
            cursor.execute(
                """UPDATE mt_cases SET iteration_id = NULL WHERE iteration_id = %s""",
                (int(iteration_id),),
            )
            affected_cases = cursor.rowcount
        return {
            "code": 0,
            "msg": "success",
            "iteration_id": iteration_id,
            "affected_cases": affected_cases,
        }

    def upsert_public_action(self, action_data):
        action_id = _clean(action_data.get("id") or action_data.get("public_action_id"))
        page_code = _clean(
            action_data.get("page_code")
            or action_data.get("page_key")
            or action_data.get("target")
        )
        page_title = _clean(
            action_data.get("page_title")
            or self.get_public_action_page_title(page_code)
        )
        action_name = _clean(
            action_data.get("action_name")
            or action_data.get("title")
            or action_data.get("desc")
        )

        if not page_code:
            raise ValueError("page_code is required")
        if not action_name:
            raise ValueError("action_name is required")

        params_json = _json_dumps(action_data.get("params") or [])
        aliases_json = _json_dumps(action_data.get("aliases") or [])
        steps = action_data.get("steps") or []
        if not steps:
            raise ValueError("At least one public action step is required")

        with self.connect() as (_, cursor):
            if action_id:
                cursor.execute(
                    """
                    UPDATE mt_public_actions
                    SET page_code = %s,
                        page_title = %s,
                        action_name = %s,
                        description = %s,
                        params_json = %s,
                        aliases_json = %s,
                        enabled = %s
                    WHERE id = %s
                    """,
                    (
                        page_code,
                        page_title,
                        action_name,
                        _clean(action_data.get("description") or action_data.get("desc")),
                        params_json,
                        aliases_json,
                        _enabled_flag(action_data.get("enabled")),
                        int(action_id),
                    ),
                )
                public_action_id = int(action_id)
            else:
                cursor.execute(
                    """
                    INSERT INTO mt_public_actions (
                        page_code, page_title, action_name, description,
                        params_json, aliases_json, enabled
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        page_title = VALUES(page_title),
                        description = VALUES(description),
                        params_json = VALUES(params_json),
                        aliases_json = VALUES(aliases_json),
                        enabled = VALUES(enabled),
                        id = LAST_INSERT_ID(id)
                    """,
                    (
                        page_code,
                        page_title,
                        action_name,
                        _clean(action_data.get("description") or action_data.get("desc")),
                        params_json,
                        aliases_json,
                        _enabled_flag(action_data.get("enabled")),
                    ),
                )
                public_action_id = cursor.lastrowid

            cursor.execute(
                "DELETE FROM mt_public_action_steps WHERE public_action_id = %s",
                (public_action_id,),
            )
            for index, step in enumerate(steps, 1):
                child_action_id = _clean(
                    step.get("child_public_action_id")
                    or step.get("public_action_id")
                    or step.get("child_action_id")
                )
                cursor.execute(
                    """
                    INSERT INTO mt_public_action_steps (
                        public_action_id, step_order, step_action, locator_method,
                        locator_value, locator_options, step_value,
                        condition_type, condition_locator_method,
                        condition_locator_value, condition_options,
                        child_public_action_id, remark, enabled
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                    """,
                    (
                        public_action_id,
                        int(step.get("step_order") or index),
                        normalize_public_operation(step.get("step_action") or "click"),
                        _clean(step.get("locator_method")),
                        _clean(step.get("locator_value")),
                        _clean(step.get("locator_options")),
                        _clean(step.get("step_value")),
                        _clean(step.get("condition_type") or "always"),
                        _clean(step.get("condition_locator_method")),
                        _clean(step.get("condition_locator_value")),
                        _clean(step.get("condition_options")),
                        int(child_action_id) if child_action_id else None,
                        _clean(step.get("remark") or step.get("备注")),
                    ),
                )

        return {
            "public_action_id": public_action_id,
            "id": public_action_id,
            "page_code": page_code,
            "page_title": page_title,
            "action_name": action_name,
            "storage": "mysql",
            "steps": len(steps),
        }

    def clear_public_actions(self):
        with self.connect() as (_, cursor):
            cursor.execute("DELETE FROM mt_public_action_steps")
            deleted_steps = cursor.rowcount
            cursor.execute("DELETE FROM mt_public_actions")
            deleted_actions = cursor.rowcount
        return {
            "deleted_actions": deleted_actions,
            "deleted_steps": deleted_steps,
        }

    def import_public_actions_from_code(self, actions):
        synced = 0
        for item in actions:
            page_code = _clean(item.get("page_code") or item.get("page_key") or item.get("target"))
            action_name = _clean(item.get("action_name") or item.get("title") or item.get("desc") or item.get("method"))
            if not page_code or not action_name:
                continue

            operation = normalize_public_operation(item.get("operation") or "click")
            steps = item.get("steps") or [
                {
                    "step_action": operation,
                    "locator_method": _clean(item.get("locator_method")),
                    "locator_value": _clean(item.get("locator_value")),
                    "locator_options": _clean(item.get("locator_options")),
                    "step_value": _clean(item.get("step_value")),
                }
            ]
            self.upsert_public_action(
                {
                    "page_code": page_code,
                    "page_title": _clean(item.get("page_title") or item.get("page_name")) or self.get_public_action_page_title(page_code),
                    "action_name": action_name,
                    "description": _clean(item.get("description") or item.get("desc")),
                    "params": item.get("params") or [],
                    "aliases": item.get("aliases") or [],
                    "enabled": item.get("enabled", 1),
                    "steps": steps,
                }
            )
            synced += 1
        return {"synced": synced}

    def get_public_action(self, public_action_id):
        public_action_id = _clean(public_action_id)
        if not public_action_id:
            raise ValueError("public_action_id is required")

        with self.connect() as (_, cursor):
            cursor.execute(
                """
                SELECT id, page_code, page_title, action_name, description,
                       params_json, aliases_json, enabled
                FROM mt_public_actions
                WHERE id = %s AND enabled = 1
                """,
                (int(public_action_id),),
            )
            action = cursor.fetchone()
            if not action:
                raise ValueError(f"Public action not found or disabled: {public_action_id}")

            cursor.execute(
                """
                SELECT step_order, step_action, locator_method, locator_value,
                       locator_options, step_value,
                       condition_type, condition_locator_method,
                       condition_locator_value, condition_options,
                       child_public_action_id,
                       remark, enabled
                FROM mt_public_action_steps
                WHERE public_action_id = %s AND enabled = 1
                ORDER BY step_order ASC
                """,
                (int(public_action_id),),
            )
            steps = []
            for step in cursor.fetchall():
                step["public_action_id"] = step.get("child_public_action_id") or ""
                step["public_action"] = step.get("child_public_action_id") or ""
                step["备注"] = step.get("remark", "")
                steps.append(step)

        action["params"] = _json_loads(action.get("params_json"), [])
        action["aliases"] = _json_loads(action.get("aliases_json"), [])
        action["steps"] = steps
        return action

    def get_public_action_detail(self, public_action_id, include_disabled=True):
        public_action_id = _clean(public_action_id)
        if not public_action_id:
            raise ValueError("public_action_id is required")

        action_where = "WHERE a.id = %s" if include_disabled else "WHERE a.id = %s AND a.enabled = 1"
        step_where = "WHERE public_action_id = %s" if include_disabled else "WHERE public_action_id = %s AND enabled = 1"
        with self.connect() as (_, cursor):
            cursor.execute(
                f"""
                SELECT a.id,
                       a.page_code,
                       COALESCE(NULLIF(p.page_title, ''), NULLIF(a.page_title, ''), a.page_code) AS page_title,
                       a.action_name,
                       a.description,
                       a.params_json,
                       a.aliases_json,
                       a.enabled,
                       a.sort_order
                FROM mt_public_actions a
                LEFT JOIN mt_public_action_pages p
                  ON p.page_code = a.page_code AND p.enabled = 1
                {action_where}
                """,
                (int(public_action_id),),
            )
            action = cursor.fetchone()
            if not action:
                raise ValueError(f"Public action not found: {public_action_id}")

            cursor.execute(
                f"""
                SELECT id, public_action_id, step_order, step_action, locator_method,
                       locator_value, locator_options, step_value,
                       condition_type, condition_locator_method,
                       condition_locator_value, condition_options,
                       child_public_action_id, remark, enabled
                FROM mt_public_action_steps
                {step_where}
                ORDER BY step_order ASC
                """,
                (int(public_action_id),),
            )
            steps = []
            for step in cursor.fetchall():
                step["remark"] = step.get("remark", "")
                steps.append(step)

        action["public_action_id"] = action.get("id")
        action["params"] = _json_loads(action.get("params_json"), [])
        action["aliases"] = _json_loads(action.get("aliases_json"), [])
        action["desc"] = action.get("description") or ""
        action["steps"] = steps
        return action

    def find_public_action_id(self, action_name_or_alias, page_code=None, include_disabled=False):
        target = _clean(action_name_or_alias)
        page_code = _clean(page_code)
        if not target:
            return None

        for action in self.list_public_actions(include_disabled=include_disabled):
            if page_code and _clean(action.get("page_code")) != page_code:
                continue
            names = [
                _clean(action.get("action_name")),
                _clean(action.get("title")),
                _clean(action.get("desc")),
                _clean(action.get("action")),
            ]
            names.extend(_clean(alias) for alias in action.get("aliases") or [])
            if target in names:
                if not include_disabled and not _enabled_flag(action.get("enabled")):
                    continue
                return action.get("public_action_id") or action.get("id")
        return None

    @staticmethod
    def _ensure_iteration_reference(cursor, iteration_id):
        if iteration_id is None:
            return
        cursor.execute(
            """
            SELECT id
            FROM mt_iteration
            WHERE id = %s AND deleted_at IS NULL
            """,
            (iteration_id,),
        )
        if not cursor.fetchone():
            raise ValueError(f"iteration not found or deleted: {iteration_id}")

    def list_test_cases(
        self,
        case_id=None,
        iteration_id=None,
        include_disabled=False,
    ):
        where = []
        params = []
        if case_id:
            where.append("c.case_id = %s")
            params.append(case_id)
        iteration_id = _optional_id(iteration_id, "iteration_id")
        if iteration_id:
            where.append("c.iteration_id = %s")
            params.append(iteration_id)
        if not include_disabled:
            where.append("c.enabled = 1")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"""
            SELECT c.case_id, c.title, c.case_mode, c.flow_group_hint,
                   c.action, c.inputs, c.api_error_check_mode, c.allowed_errors,
                   c.assert_type, c.expect_value, c.enabled, c.sort_order,
                   c.iteration_id, i.iteration_code, i.iteration_name
            FROM mt_cases c
            LEFT JOIN mt_iteration i ON i.id = c.iteration_id
            {where_sql}
            ORDER BY c.sort_order ASC, c.id ASC
        """
        with self.connect() as (_, cursor):
            cursor.execute(sql, params)
            cases = list(cursor.fetchall())

            for case in cases:
                case["steps"] = []
                if case.get("case_mode") != "steps":
                    continue
                cursor.execute(
                    """
                    SELECT step_order, step_action, locator_method, locator_value,
                           locator_options, step_value,
                           condition_type, condition_locator_method,
                           condition_locator_value, condition_options,
                           public_action_id, remark, enabled
                    FROM mt_case_steps
                    WHERE case_id = %s AND enabled = 1
                    ORDER BY step_order ASC
                    """,
                    (case["case_id"],),
                )
                steps = []
                for step in cursor.fetchall():
                    step["public_action"] = step.get("public_action_id") or ""
                    step["public_action_key"] = step.get("public_action_id") or ""
                    step["备注"] = step.get("remark", "")
                    steps.append(step)
                case["steps"] = steps
        return cases

    def get_case(self, case_id):
        cases = self.list_test_cases(case_id=case_id, include_disabled=False)
        if not cases:
            raise ValueError(f"DB case not found or disabled: {case_id}")
        return cases[0]

    def get_case_detail(self, case_id, include_disabled=True):
        cases = self.list_test_cases(case_id=case_id, include_disabled=include_disabled)
        if not cases:
            raise ValueError(f"DB case not found: {case_id}")
        case = cases[0]
        case["params"] = case.get("inputs", "")
        case["api_error_check_mode"], case["allowed_errors"] = resolve_api_error_policy(case)
        case["assert_value"] = case.get("expect_value", "")
        case["steps_count"] = len(case.get("steps") or [])
        for index, step in enumerate(case.get("steps") or [], 1):
            step["step_order"] = step.get("step_order") or index
            step["remark"] = step.get("remark") or step.get("备注") or ""
            step["备注"] = step.get("备注") or step.get("remark") or ""
        return case

    def upsert_step_case(self, case_data):
        case_id = _clean(case_data.get("case_id"))
        title = _clean(case_data.get("title"))
        iteration_id = _optional_id(case_data.get("iteration_id"), "iteration_id")
        if not case_id:
            raise ValueError("case_id is required")
        if not title:
            raise ValueError("title is required")

        steps = case_data.get("steps") or []
        if not steps:
            raise ValueError("At least one step is required")

        flow_group_hint = _clean(case_data.get("flow_group_hint"))
        enabled_value = case_data.get("enabled")
        enabled = None if enabled_value in (None, "") else _enabled_flag(enabled_value)
        inputs = _business_inputs_text(case_data.get("params") or case_data.get("inputs"))
        api_error_check_mode, allowed_errors = resolve_api_error_policy(
            {**case_data, "inputs": case_data.get("params") or case_data.get("inputs")}
        )
        with self.connect() as (_, cursor):
            self._ensure_iteration_reference(cursor, iteration_id)
            if enabled is None:
                cursor.execute(
                    "SELECT enabled FROM mt_cases WHERE case_id = %s",
                    (case_id,),
                )
                existing_case = cursor.fetchone()
                enabled = _enabled_flag(
                    existing_case.get("enabled") if existing_case else 1
                )
            cursor.execute(
                """
                INSERT INTO mt_cases (
                    iteration_id, case_id, title, case_mode,
                    flow_group_hint, action, inputs,
                    api_error_check_mode, allowed_errors,
                    assert_type, expect_value, enabled
                ) VALUES (%s, %s, %s, 'steps', %s, '', %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    iteration_id = VALUES(iteration_id),
                    title = VALUES(title),
                    case_mode = 'steps',
                    flow_group_hint = VALUES(flow_group_hint),
                    action = '',
                    inputs = VALUES(inputs),
                    api_error_check_mode = VALUES(api_error_check_mode),
                    allowed_errors = VALUES(allowed_errors),
                    assert_type = VALUES(assert_type),
                    expect_value = VALUES(expect_value),
                    enabled = VALUES(enabled)
                """,
                (
                    iteration_id,
                    case_id,
                    title,
                    flow_group_hint,
                    inputs,
                    api_error_check_mode,
                    _json_dumps_or_none(allowed_errors),
                    _clean(case_data.get("assert_type")),
                    _clean(case_data.get("assert_value") or case_data.get("expect_value")),
                    enabled,
                ),
            )
            cursor.execute("DELETE FROM mt_case_steps WHERE case_id = %s", (case_id,))
            for index, step in enumerate(steps, 1):
                public_action_id = _clean(
                    step.get("public_action_id")
                    or step.get("public_action")
                    or step.get("public_action_key")
                )
                cursor.execute(
                    """
                    INSERT INTO mt_case_steps (
                        case_id, step_order, step_action, locator_method,
                        locator_value, locator_options, step_value, public_action_id,
                        condition_type, condition_locator_method,
                        condition_locator_value, condition_options,
                        remark, enabled
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                    """,
                    (
                        case_id,
                        int(step.get("step_order") or index),
                        normalize_public_operation(step.get("step_action")),
                        _clean(step.get("locator_method")),
                        _clean(step.get("locator_value")),
                        _clean(step.get("locator_options")),
                        _clean(step.get("step_value")),
                        int(public_action_id) if public_action_id else None,
                        _clean(step.get("condition_type") or "always"),
                        _clean(step.get("condition_locator_method")),
                        _clean(step.get("condition_locator_value")),
                        _clean(step.get("condition_options")),
                        _clean(step.get("remark") or step.get("备注")),
                    ),
                )
        return {
            "case_id": case_id,
            "flow_group_hint": flow_group_hint,
            "storage": "mysql",
            "steps": len(steps),
            "enabled": enabled,
            "iteration_id": iteration_id,
            "inputs": inputs,
            "api_error_check_mode": api_error_check_mode,
            "allowed_errors": allowed_errors,
        }

    def upsert_action_case(self, case_data):
        case_id = _clean(case_data.get("case_id"))
        title = _clean(case_data.get("title"))
        action = _clean(case_data.get("action"))
        iteration_id = _optional_id(case_data.get("iteration_id"), "iteration_id")
        if not case_id:
            raise ValueError("case_id is required")
        if not title:
            raise ValueError("title is required")
        if not action:
            raise ValueError("action is required")

        inputs = _business_inputs_text(case_data.get("inputs"))
        enabled_value = case_data.get("enabled")
        enabled = None if enabled_value in (None, "") else _enabled_flag(enabled_value)
        api_error_check_mode, allowed_errors = resolve_api_error_policy(case_data)
        with self.connect() as (_, cursor):
            self._ensure_iteration_reference(cursor, iteration_id)
            if enabled is None:
                cursor.execute(
                    "SELECT enabled FROM mt_cases WHERE case_id = %s",
                    (case_id,),
                )
                existing_case = cursor.fetchone()
                enabled = _enabled_flag(
                    existing_case.get("enabled") if existing_case else 1
                )
            cursor.execute(
                """
                INSERT INTO mt_cases (
                    iteration_id, case_id, title, case_mode,
                    flow_group_hint, action, inputs,
                    api_error_check_mode, allowed_errors,
                    assert_type, expect_value, enabled
                ) VALUES (%s, %s, %s, 'action', '', %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    iteration_id = VALUES(iteration_id),
                    title = VALUES(title),
                    case_mode = 'action',
                    action = VALUES(action),
                    inputs = VALUES(inputs),
                    api_error_check_mode = VALUES(api_error_check_mode),
                    allowed_errors = VALUES(allowed_errors),
                    assert_type = VALUES(assert_type),
                    expect_value = VALUES(expect_value),
                    enabled = VALUES(enabled)
                """,
                (
                    iteration_id,
                    case_id,
                    title,
                    action,
                    inputs,
                    api_error_check_mode,
                    _json_dumps_or_none(allowed_errors),
                    _clean(case_data.get("assert_type")),
                    _clean(case_data.get("expect_value") or case_data.get("assert_value")),
                    enabled,
                ),
            )
            cursor.execute("DELETE FROM mt_case_steps WHERE case_id = %s", (case_id,))
        return {
            "case_id": case_id,
            "action": action,
            "inputs": inputs,
            "api_error_check_mode": api_error_check_mode,
            "allowed_errors": allowed_errors,
            "enabled": enabled,
            "iteration_id": iteration_id,
            "storage": "mysql",
        }

    def set_case_enabled(self, case_id, enabled):
        case_id = _clean(case_id)
        if not case_id:
            raise ValueError("case_id is required")

        enabled = _enabled_flag(enabled, default=1)
        with self.connect() as (_, cursor):
            cursor.execute(
                "SELECT case_id FROM mt_cases WHERE case_id = %s",
                (case_id,),
            )
            if not cursor.fetchone():
                raise ValueError(f"DB case not found: {case_id}")

            cursor.execute(
                "UPDATE mt_cases SET enabled = %s WHERE case_id = %s",
                (enabled, case_id),
            )

        return {
            "case_id": case_id,
            "enabled": enabled,
        }

    def upsert_agent(self, agent_data):
        agent_id = _clean(agent_data.get("agent_id"))
        if not agent_id:
            raise ValueError("agent_id is required")

        status = _clean(agent_data.get("status") or "online")
        if status not in {"online", "offline", "running"}:
            status = "online"

        agent_ip = _clean(agent_data.get("agent_ip") or agent_data.get("ip"))
        current_job_id = _clean(agent_data.get("current_job_id") or agent_data.get("job_id"))
        enabled = _enabled_flag(agent_data.get("enabled"), default=1)

        with self.connect() as (_, cursor):
            cursor.execute(
                """
                INSERT INTO mt_agents (
                    agent_id, agent_name, agent_ip, status,
                    current_job_id, enabled, last_heartbeat_at
                ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    agent_name = VALUES(agent_name),
                    agent_ip = VALUES(agent_ip),
                    status = VALUES(status),
                    current_job_id = VALUES(current_job_id),
                    enabled = VALUES(enabled),
                    last_heartbeat_at = NOW()
                """,
                (
                    agent_id,
                    _clean(agent_data.get("agent_name") or agent_data.get("name")) or agent_id,
                    agent_ip,
                    status,
                    current_job_id,
                    enabled,
                ),
            )

        return {
            "agent_id": agent_id,
            "agent_ip": agent_ip,
            "status": status,
            "current_job_id": current_job_id,
            "enabled": enabled,
        }

    def list_agents(self):
        with self.connect() as (_, cursor):
            cursor.execute(
                """
                SELECT id, agent_id, agent_name, agent_ip, status,
                       current_job_id, enabled, last_heartbeat_at,
                       created_at, updated_at
                FROM mt_agents
                ORDER BY last_heartbeat_at DESC, updated_at DESC, id DESC
                """
            )
            rows = list(cursor.fetchall())

        return [
            {
                "id": row.get("id"),
                "agent_id": _clean(row.get("agent_id")),
                "agent_name": _clean(row.get("agent_name")),
                "agent_ip": _clean(row.get("agent_ip")),
                "status": _clean(row.get("status")),
                "current_job_id": _clean(row.get("current_job_id")),
                "enabled": row.get("enabled", 1),
                "last_heartbeat_at": _datetime_text(row.get("last_heartbeat_at")),
                "created_at": _datetime_text(row.get("created_at")),
                "updated_at": _datetime_text(row.get("updated_at")),
            }
            for row in rows
        ]

    def claim_next_job(self, agent_id, agent_ip=""):
        agent_id = _clean(agent_id)
        agent_ip = _clean(agent_ip)
        if not agent_id:
            raise ValueError("agent_id is required")

        with self.connect() as (_, cursor):
            cursor.execute(
                """
                SELECT enabled
                FROM mt_agents
                WHERE agent_id = %s
                FOR UPDATE
                """,
                (agent_id,),
            )
            agent = cursor.fetchone()
            if not agent:
                cursor.execute(
                    """
                    INSERT INTO mt_agents (
                        agent_id, agent_name, agent_ip, status,
                        current_job_id, enabled, last_heartbeat_at
                    ) VALUES (%s, %s, %s, 'online', '', 1, NOW())
                    """,
                    (agent_id, agent_id, agent_ip),
                )
                agent = {"enabled": 1}

            if not _enabled_flag(agent.get("enabled")):
                cursor.execute(
                    """
                    UPDATE mt_agents
                    SET status = 'offline',
                        current_job_id = '',
                        agent_ip = %s,
                        last_heartbeat_at = NOW()
                    WHERE agent_id = %s
                    """,
                    (agent_ip, agent_id),
                )
                return None

            cursor.execute(
                """
                SELECT r.id, r.job_id, r.case_id, c.title,
                       r.iteration_id, i.iteration_code, i.iteration_name,
                       r.status, r.assigned_agent_id, r.assigned_agent_ip,
                       r.trigger_type, r.schedule_id,
                       r.agent_id, r.command_text, r.created_at
                FROM mt_run_records r
                LEFT JOIN mt_cases c
                  ON c.case_id = r.case_id
                LEFT JOIN mt_iteration i
                  ON i.id = r.iteration_id
                WHERE r.status = 'queued'
                  AND (r.assigned_agent_ip = '' OR r.assigned_agent_ip = %s)
                  AND (r.assigned_agent_id = '' OR r.assigned_agent_id = %s)
                ORDER BY r.created_at ASC, r.id ASC
                LIMIT 1
                FOR UPDATE
                """,
                (agent_ip, agent_id),
            )
            job = cursor.fetchone()
            if not job:
                cursor.execute(
                    """
                    UPDATE mt_agents
                    SET status = 'online',
                        current_job_id = '',
                        agent_ip = %s,
                        last_heartbeat_at = NOW()
                    WHERE agent_id = %s
                    """,
                    (agent_ip, agent_id),
                )
                return None

            cursor.execute(
                """
                UPDATE mt_run_records
                SET status = 'running',
                    agent_id = %s,
                    started_at = COALESCE(started_at, NOW())
                WHERE id = %s
                """,
                (agent_id, job["id"]),
            )
            cursor.execute(
                """
                UPDATE mt_agents
                SET status = 'running',
                    current_job_id = %s,
                    agent_ip = %s,
                    last_heartbeat_at = NOW()
                WHERE agent_id = %s
                """,
                (job["job_id"], agent_ip, agent_id),
            )

        job["status"] = "running"
        job["agent_id"] = agent_id
        job["agent_ip"] = agent_ip
        job["title"] = _clean(job.get("title"))
        job["created_at"] = _datetime_text(job.get("created_at"))
        return job

    def finish_agent_job(self, agent_id, job_id="", status="online"):
        agent_id = _clean(agent_id)
        if not agent_id:
            return {}

        status = _clean(status or "online")
        if status not in {"online", "offline", "running"}:
            status = "online"

        with self.connect() as (_, cursor):
            cursor.execute(
                """
                UPDATE mt_agents
                SET status = %s,
                    current_job_id = '',
                    last_heartbeat_at = NOW()
                WHERE agent_id = %s
                """,
                (status, agent_id),
            )

        return {
            "agent_id": agent_id,
            "job_id": _clean(job_id),
            "status": status,
        }

    def insert_run_record(self, job):
        summary = job.get("result_summary")
        status = _clean(job.get("status"))
        trigger_type = _trigger_type(job.get("trigger_type"))
        schedule_id = _schedule_id_or_none(job.get("schedule_id"))
        iteration_id = _optional_id(job.get("iteration_id"), "iteration_id")
        if schedule_id:
            trigger_type = "schedule"
        finished_at = job.get("finished_at_db")
        if status in {"success", "failed"} and not finished_at:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self.connect() as (_, cursor):
            cursor.execute(
                """
                INSERT INTO mt_run_records (
                    job_id, case_id, iteration_id, status,
                    trigger_type, schedule_id,
                    assigned_agent_id, assigned_agent_ip, agent_id,
                    command_text, returncode, report_url,
                    report_dir, result_summary, stdout_text, stderr_text, started_at, finished_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    iteration_id = VALUES(iteration_id),
                    status = VALUES(status),
                    trigger_type = VALUES(trigger_type),
                    schedule_id = VALUES(schedule_id),
                    assigned_agent_id = VALUES(assigned_agent_id),
                    assigned_agent_ip = VALUES(assigned_agent_ip),
                    agent_id = VALUES(agent_id),
                    command_text = VALUES(command_text),
                    returncode = VALUES(returncode),
                    report_url = VALUES(report_url),
                    report_dir = VALUES(report_dir),
                    result_summary = VALUES(result_summary),
                    stdout_text = VALUES(stdout_text),
                    stderr_text = VALUES(stderr_text),
                    started_at = COALESCE(mt_run_records.started_at, VALUES(started_at)),
                    finished_at = VALUES(finished_at)
                """,
                (
                    _clean(job.get("job_id")),
                    _clean(job.get("case_id")),
                    iteration_id,
                    status,
                    trigger_type,
                    schedule_id,
                    _clean(job.get("assigned_agent_id")),
                    _clean(job.get("assigned_agent_ip")),
                    _clean(job.get("agent_id")),
                    _clean(job.get("command_text")),
                    job.get("returncode"),
                    _clean(job.get("report_url")),
                    _clean(job.get("report_dir")),
                    _json_dumps_or_none(summary),
                    job.get("stdout", ""),
                    job.get("stderr", ""),
                    job.get("started_at_db"),
                    finished_at,
                ),
            )

    def list_run_records(self, limit=50):
        limit = _positive_int(limit, 50, maximum=200)
        with self.connect() as (_, cursor):
            cursor.execute(
                """
                SELECT r.id, r.job_id, r.case_id, c.title,
                       r.iteration_id, i.iteration_code, i.iteration_name,
                       r.status, r.command_text, r.returncode,
                       r.trigger_type, r.schedule_id, s.schedule_name,
                       r.assigned_agent_id, r.assigned_agent_ip, r.agent_id,
                       r.report_url, r.report_dir, r.result_summary,
                       rp.simple_report_size AS report_html_size,
                       CHAR_LENGTH(r.stdout_text) AS stdout_size,
                       CHAR_LENGTH(r.stderr_text) AS stderr_size,
                       r.started_at, r.finished_at, r.created_at, r.updated_at
                FROM mt_run_records r
                LEFT JOIN mt_cases c
                  ON c.case_id = r.case_id
                LEFT JOIN mt_iteration i
                  ON i.id = r.iteration_id
                LEFT JOIN mt_schedules s
                  ON s.id = r.schedule_id
                LEFT JOIN mt_reports rp
                  ON rp.job_id = r.job_id
                ORDER BY COALESCE(r.finished_at, r.updated_at, r.created_at) DESC, r.id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = list(cursor.fetchall())

        records = []
        for row in rows:
            summary = _json_loads(row.get("result_summary"), {})
            job_id = _clean(row.get("job_id"))
            has_report_html = _int_value(row.get("report_html_size")) > 0
            db_report_url = f"/reports/db/{job_id}.html" if has_report_html else ""
            records.append(
                {
                    "id": row.get("id"),
                    "job_id": job_id,
                    "case_id": _clean(row.get("case_id")),
                    "title": _clean(row.get("title")),
                    "iteration_id": row.get("iteration_id"),
                    "iteration_code": _clean(row.get("iteration_code")),
                    "iteration_name": _clean(row.get("iteration_name")),
                    "status": _clean(row.get("status")),
                    "trigger_type": _trigger_type(row.get("trigger_type")),
                    "schedule_id": row.get("schedule_id"),
                    "schedule_name": _clean(row.get("schedule_name")),
                    "command_text": _clean(row.get("command_text")),
                    "returncode": row.get("returncode"),
                    "assigned_agent_id": _clean(row.get("assigned_agent_id")),
                    "assigned_agent_ip": _clean(row.get("assigned_agent_ip")),
                    "agent_id": _clean(row.get("agent_id")),
                    "report_url": db_report_url or _clean(row.get("report_url")),
                    "file_report_url": _clean(row.get("report_url")),
                    "db_report_url": db_report_url,
                    "has_report_html": has_report_html,
                    "report_dir": _clean(row.get("report_dir")),
                    "result_summary": summary,
                    "stdout_size": _int_value(row.get("stdout_size")),
                    "stderr_size": _int_value(row.get("stderr_size")),
                    "has_log": bool(_int_value(row.get("stdout_size")) or _int_value(row.get("stderr_size"))),
                    "started_at": _datetime_text(row.get("started_at")),
                    "finished_at": _datetime_text(row.get("finished_at")),
                    "created_at": _datetime_text(row.get("created_at")),
                    "updated_at": _datetime_text(row.get("updated_at")),
                }
            )
        return records

    def get_run_record_detail(self, job_id):
        job_id = _clean(job_id)
        if not job_id:
            raise ValueError("job_id is required")

        with self.connect() as (_, cursor):
            cursor.execute(
                """
                SELECT r.id, r.job_id, r.case_id, c.title,
                       r.iteration_id, i.iteration_code, i.iteration_name,
                       r.status, r.command_text, r.returncode,
                       r.trigger_type, r.schedule_id, s.schedule_name,
                       r.assigned_agent_id, r.assigned_agent_ip, r.agent_id,
                       r.report_url, r.report_dir, r.result_summary,
                       rp.simple_report_size AS report_html_size,
                       r.stdout_text, r.stderr_text,
                       r.started_at, r.finished_at, r.created_at, r.updated_at
                FROM mt_run_records r
                LEFT JOIN mt_cases c
                  ON c.case_id = r.case_id
                LEFT JOIN mt_iteration i
                  ON i.id = r.iteration_id
                LEFT JOIN mt_schedules s
                  ON s.id = r.schedule_id
                LEFT JOIN mt_reports rp
                  ON rp.job_id = r.job_id
                WHERE r.job_id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()

        if not row:
            raise ValueError(f"Run record not found: {job_id}")

        summary = _json_loads(row.get("result_summary"), {})
        has_report_html = _int_value(row.get("report_html_size")) > 0
        db_report_url = f"/reports/db/{job_id}.html" if has_report_html else ""
        return {
            "id": row.get("id"),
            "job_id": _clean(row.get("job_id")),
            "case_id": _clean(row.get("case_id")),
            "title": _clean(row.get("title")),
            "iteration_id": row.get("iteration_id"),
            "iteration_code": _clean(row.get("iteration_code")),
            "iteration_name": _clean(row.get("iteration_name")),
            "status": _clean(row.get("status")),
            "trigger_type": _trigger_type(row.get("trigger_type")),
            "schedule_id": row.get("schedule_id"),
            "schedule_name": _clean(row.get("schedule_name")),
            "command_text": _clean(row.get("command_text")),
            "returncode": row.get("returncode"),
            "assigned_agent_id": _clean(row.get("assigned_agent_id")),
            "assigned_agent_ip": _clean(row.get("assigned_agent_ip")),
            "agent_id": _clean(row.get("agent_id")),
            "report_url": db_report_url or _clean(row.get("report_url")),
            "file_report_url": _clean(row.get("report_url")),
            "db_report_url": db_report_url,
            "has_report_html": has_report_html,
            "report_dir": _clean(row.get("report_dir")),
            "result_summary": summary,
            "stdout": row.get("stdout_text") or "",
            "stderr": row.get("stderr_text") or "",
            "stdout_text": row.get("stdout_text") or "",
            "stderr_text": row.get("stderr_text") or "",
            "started_at": _datetime_text(row.get("started_at")),
            "finished_at": _datetime_text(row.get("finished_at")),
            "created_at": _datetime_text(row.get("created_at")),
            "updated_at": _datetime_text(row.get("updated_at")),
        }

    def insert_report_record(self, job):
        summary = job.get("result_summary") or {}
        failed_cases = summary.get("failed_cases") if isinstance(summary, dict) else []
        total = _int_value(summary.get("total") if isinstance(summary, dict) else 0)
        passed = _int_value(summary.get("passed") if isinstance(summary, dict) else 0)
        failed = _int_value(summary.get("failed") if isinstance(summary, dict) else 0)
        skipped = _int_value(summary.get("skipped") if isinstance(summary, dict) else 0)
        if not failed and failed_cases:
            failed = len(failed_cases)
        simple_report_html = _report_html_from_job(job)
        simple_report_size = len(simple_report_html.encode("utf-8")) if simple_report_html else 0
        trigger_type = _trigger_type(job.get("trigger_type"))
        schedule_id = _schedule_id_or_none(job.get("schedule_id"))
        iteration_id = _optional_id(job.get("iteration_id"), "iteration_id")
        if schedule_id:
            trigger_type = "schedule"

        with self.connect() as (_, cursor):
            cursor.execute(
                """
                INSERT INTO mt_reports (
                    job_id, case_id, iteration_id, agent_id, report_name, status,
                    trigger_type, schedule_id,
                    total, passed, failed, skipped, duration_seconds,
                    report_url, simple_report_url, simple_report_html, simple_report_size,
                    official_report_url,
                    report_dir, output_dir, result_summary, started_at, finished_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s,
                    %s, %s, %s, %s, %s
                )
                ON DUPLICATE KEY UPDATE
                    case_id = VALUES(case_id),
                    iteration_id = VALUES(iteration_id),
                    agent_id = VALUES(agent_id),
                    report_name = VALUES(report_name),
                    status = VALUES(status),
                    trigger_type = VALUES(trigger_type),
                    schedule_id = VALUES(schedule_id),
                    total = VALUES(total),
                    passed = VALUES(passed),
                    failed = VALUES(failed),
                    skipped = VALUES(skipped),
                    duration_seconds = VALUES(duration_seconds),
                    report_url = VALUES(report_url),
                    simple_report_url = VALUES(simple_report_url),
                    simple_report_html = VALUES(simple_report_html),
                    simple_report_size = VALUES(simple_report_size),
                    official_report_url = VALUES(official_report_url),
                    report_dir = VALUES(report_dir),
                    output_dir = VALUES(output_dir),
                    result_summary = VALUES(result_summary),
                    started_at = VALUES(started_at),
                    finished_at = VALUES(finished_at)
                """,
                (
                    _clean(job.get("job_id")),
                    _clean(job.get("case_id")),
                    iteration_id,
                    _clean(job.get("agent_id")),
                    _clean(job.get("report_name")),
                    _clean(job.get("status") or "success"),
                    trigger_type,
                    schedule_id,
                    total,
                    passed,
                    failed,
                    skipped,
                    _float_value_or_none(job.get("duration_seconds")),
                    _clean(job.get("report_url")),
                    _clean(job.get("simple_report_url")),
                    simple_report_html or None,
                    simple_report_size,
                    _clean(job.get("official_report_url")),
                    _clean(job.get("report_dir")),
                    _clean(job.get("output_dir")),
                    _json_dumps_or_none(summary),
                    job.get("started_at_db"),
                    job.get("finished_at_db") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )

    def list_report_records(self, limit=50, page=None, page_size=None, with_pagination=False):
        use_pagination = page is not None or page_size is not None or with_pagination
        if use_pagination:
            page = _positive_int(page, 1)
            page_size = _positive_int(page_size, 10, maximum=200)
            offset = (page - 1) * page_size
        else:
            limit = _positive_int(limit, 50, maximum=200)

        with self.connect() as (_, cursor):
            total = 0
            if use_pagination:
                cursor.execute("SELECT COUNT(*) AS total FROM mt_reports")
                total = _int_value((cursor.fetchone() or {}).get("total"))

            cursor.execute(
                f"""
                SELECT r.id, r.job_id, r.case_id,
                       r.iteration_id, i.iteration_code, i.iteration_name,
                       r.agent_id, r.report_name, r.status,
                       r.trigger_type, r.schedule_id, s.schedule_name,
                       r.total, r.passed, r.failed, r.skipped, r.duration_seconds,
                       r.report_url, r.simple_report_url, r.official_report_url,
                       r.report_dir, r.output_dir, r.result_summary, r.simple_report_size,
                       r.started_at, r.finished_at, r.created_at, r.updated_at
                FROM mt_reports r
                LEFT JOIN mt_iteration i
                  ON i.id = r.iteration_id
                LEFT JOIN mt_schedules s
                  ON s.id = r.schedule_id
                ORDER BY COALESCE(r.finished_at, r.updated_at, r.created_at) DESC, r.id DESC
                {"LIMIT %s OFFSET %s" if use_pagination else "LIMIT %s"}
                """,
                (page_size, offset) if use_pagination else (limit,),
            )
            rows = list(cursor.fetchall())

        reports = []
        for row in rows:
            updated_at = row.get("finished_at") or row.get("updated_at") or row.get("created_at")
            report_name = _clean(row.get("report_name")) or _clean(row.get("job_id"))
            summary = _json_loads(row.get("result_summary"), {})
            job_id = _clean(row.get("job_id"))
            has_report_html = _int_value(row.get("simple_report_size")) > 0
            db_report_url = f"/reports/db/{job_id}.html" if has_report_html else ""
            reports.append(
                {
                    "id": row.get("id"),
                    "job_id": job_id,
                    "case_id": _clean(row.get("case_id")),
                    "iteration_id": row.get("iteration_id"),
                    "iteration_code": _clean(row.get("iteration_code")),
                    "iteration_name": _clean(row.get("iteration_name")),
                    "agent_id": _clean(row.get("agent_id")),
                    "name": report_name,
                    "status": _clean(row.get("status")),
                    "trigger_type": _trigger_type(row.get("trigger_type")),
                    "schedule_id": row.get("schedule_id"),
                    "schedule_name": _clean(row.get("schedule_name")),
                    "updated_at": _datetime_text(updated_at),
                    "started_at": _datetime_text(row.get("started_at")),
                    "finished_at": _datetime_text(row.get("finished_at")),
                    "duration_seconds": _float_value_or_none(row.get("duration_seconds")),
                    "total": _int_value(row.get("total")),
                    "passed": _int_value(row.get("passed")),
                    "failed": _int_value(row.get("failed")),
                    "skipped": _int_value(row.get("skipped")),
                    "report_url": db_report_url or _clean(row.get("report_url")),
                    "simple_report": db_report_url or _clean(row.get("simple_report_url")),
                    "file_report_url": _clean(row.get("report_url")),
                    "file_simple_report": _clean(row.get("simple_report_url")),
                    "db_report_url": db_report_url,
                    "has_report_html": has_report_html,
                    "simple_report_size": _int_value(row.get("simple_report_size")),
                    "official_report": _clean(row.get("official_report_url")),
                    "report_dir": _clean(row.get("report_dir")),
                    "output_dir": _clean(row.get("output_dir")),
                    "result_summary": summary,
                }
            )
        if not use_pagination:
            return reports

        return {
            "reports": reports,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "limit": page_size,
                "offset": offset,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size if total else 1,
            },
        }

    def get_report_html(self, job_id):
        job_id = _clean(job_id)
        if not job_id:
            raise ValueError("job_id is required")

        with self.connect() as (_, cursor):
            cursor.execute(
                """
                SELECT job_id, report_name, simple_report_html, simple_report_size
                FROM mt_reports
                WHERE job_id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()

        if not row:
            raise ValueError(f"Report not found: {job_id}")
        if not row.get("simple_report_html"):
            raise ValueError(f"Report HTML not stored: {job_id}")

        return {
            "job_id": _clean(row.get("job_id")),
            "report_name": _clean(row.get("report_name")),
            "html": row.get("simple_report_html") or "",
            "simple_report_size": _int_value(row.get("simple_report_size")),
        }


def read_db_test_data():
    case_id = os.environ.get("MINITEST_CASE_ID", "").strip() or None
    iteration_id = os.environ.get("MINITEST_ITERATION_ID", "").strip() or None
    try:
        return MySqlCaseRepository().list_test_cases(
            case_id=case_id,
            iteration_id=iteration_id,
        )
    except Exception as exc:
        print(f"Read MySQL cases failed: {exc}")
        return []


def parse_inputs_text(inputs):
    return {
        str(k): "" if v is None else str(v)
        for k, v in _split_csv_inputs(inputs).items()
        if str(k) not in FRAMEWORK_INPUT_KEYS
    }
