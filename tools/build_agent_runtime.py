"""Build a Windows execution-agent runtime ZIP from the full Minitest source tree."""

import argparse
import hashlib
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = PROJECT_ROOT.parent / "minitest"
INSTALLATION_GUIDE = PROJECT_ROOT / "docs" / "execution_agent_zip_installation_guide.md"

RUNTIME_FILES = (
    "agent.env.example",
    "config.example.json",
    "requirements.txt",
    "run.py",
    "generate_simple_report.py",
    "cases/__init__.py",
    "cases/test_db_framework.py",
    "framework/__init__.py",
    "framework/base/__init__.py",
    "framework/base/base_page.py",
    "framework/pages/__init__.py",
    "framework/pages/front_page.py",
    "framework/pages/mine_page.py",
    "framework/pages/reward_page.py",
    "framework/pages/backpack_page.py",
    "framework/utils/__init__.py",
    "framework/utils/public_action.py",
    "framework/utils/action_executor.py",
    "framework/utils/mysql_case_repository.py",
    "framework/utils/report_manager.py",
    "framework/utils/run_artifacts.py",
    "framework/utils/step_executor.py",
    "tools/minitest_agent.py",
)

INSTALL_SCRIPT = r'''# Windows execution-agent installer.
# This file is written with a UTF-8 BOM for Windows PowerShell 5.1 compatibility.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$ErrorMessage
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage (exit code: $LASTEXITCODE)"
    }
}

foreach ($requiredFile in @(
    "agent.env.example",
    "config.example.json",
    "requirements.txt"
)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "安装包不完整，缺少文件：$requiredFile"
    }
}

$pythonExe = $null
$pythonPrefix = @()
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue

if ($pythonCommand) {
    & $pythonCommand.Source --version
    if ($LASTEXITCODE -eq 0) {
        $pythonExe = $pythonCommand.Source
    }
}

if (-not $pythonExe) {
    $pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        & $pythonLauncher.Source -3.12 --version
        if ($LASTEXITCODE -eq 0) {
            $pythonExe = $pythonLauncher.Source
            $pythonPrefix = @("-3.12")
        }
    }
}

if (-not $pythonExe) {
    throw "未找到可用的 Python 3.12。请安装 Python 3.12，并勾选 Add Python to PATH。"
}

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath "agent.env.example" -Destination ".env"
    Write-Host "已创建 .env，请填写中心地址、执行机名称和数据库连接信息。" -ForegroundColor Yellow
}

if (-not (Test-Path -LiteralPath "config.json")) {
    Copy-Item -LiteralPath "config.example.json" -Destination "config.json"
    Write-Host "已创建 config.json，请填写本机小程序和微信开发者工具路径。" -ForegroundColor Yellow
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    $venvArguments = @($pythonPrefix) + @("-m", "venv", ".venv")
    Invoke-CheckedCommand `
        -FilePath $pythonExe `
        -Arguments $venvArguments `
        -ErrorMessage "创建 Python 虚拟环境失败"
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "虚拟环境创建后仍未找到：$venvPython"
}

$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
Invoke-CheckedCommand `
    -FilePath $venvPython `
    -Arguments @("-m", "pip", "install", "--upgrade", "pip") `
    -ErrorMessage "升级 pip 失败，请检查网络或代理"

Invoke-CheckedCommand `
    -FilePath $venvPython `
    -Arguments @("-m", "pip", "install", "-r", "requirements.txt") `
    -ErrorMessage "安装 requirements.txt 依赖失败"

Write-Host ""
Write-Host "安装完成。" -ForegroundColor Green
Write-Host "下一步：" -ForegroundColor Cyan
Write-Host "1. 编辑 .env。"
Write-Host "2. 编辑 config.json。"
Write-Host "3. 双击 start_agent.cmd 启动执行机。"
'''

START_SCRIPT = r'''@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

if not exist ".env" (
  echo Missing .env. Run install_agent.ps1 and fill in the configuration first.
  pause
  exit /b 1
)

if not exist "config.json" (
  echo Missing config.json. Run install_agent.ps1 and fill in the local Developer Tools paths first.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Missing Python virtual environment. Run install_agent.ps1 first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" tools\minitest_agent.py
pause
'''

PACKAGE_README = """# Minitest Windows 执行机

本目录是精简执行机运行包，不包含中心管理页面、微信开发者工具、小程序项目、
本机配置、数据库密码、历史报告或截图。

## 首次安装

在 Windows PowerShell 中执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\\install_agent.ps1
```

安装脚本兼容 Windows PowerShell 5.1 和 PowerShell 7。

安装后填写：

- `.env`：中心地址、Agent ID、Agent 名称和 MySQL 连接。
- `config.json`：本机小程序目录和微信开发者工具 `cli.bat`。

然后双击 `start_agent.cmd`。

完整安装、本地联调和常见问题请查看 `INSTALLATION_GUIDE.md`。

## 与本机中心服务一起运行

中心服务可以监听 `127.0.0.1:8765`。Agent 不监听端口，只主动轮询中心服务，
因此不需要配置 `8766`。

同机运行时：

```env
MINITEST_AGENT_SERVER=http://127.0.0.1:8765
```

## 本机私密文件

不要提交或共享 `.env`、`config.json`、`outputs/`、`reports/`、`final_report/`
以及截图、日志和数据库密码。
"""

DEVTOOLS_FOREGROUND_HELPER = r'''"""Keep WeChat DevTools in the foreground for Minium IDE automation."""

import ctypes
import os
import threading
from ctypes import wintypes


def _window_candidates():
    if os.name != "nt":
        return []

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    enum_windows_proc = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        wintypes.HWND,
        wintypes.LPARAM,
    )
    candidates = []
    process_query_limited_information = 0x1000

    def process_name(process_id):
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            process_id,
        )
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(
                handle,
                0,
                buffer,
                ctypes.byref(size),
            ):
                return buffer.value.rsplit("\\", 1)[-1].lower()
            return ""
        finally:
            kernel32.CloseHandle(handle)

    def callback(hwnd, _lparam):
        process_id = wintypes.DWORD()
        thread_id = user32.GetWindowThreadProcessId(
            hwnd,
            ctypes.byref(process_id),
        )
        if not thread_id:
            return True

        title_length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
        title = title_buffer.value.lower()
        name = process_name(process_id.value)
        is_primary_devtools_process = name in {
            "wechatdevtools.exe",
            "微信开发者工具.exe",
        }
        is_runtime_process = name == "wechatappex.exe"
        has_devtools_title = (
            "微信开发者工具" in title
            or "wechat developer tools" in title
        )
        if is_primary_devtools_process or is_runtime_process or has_devtools_title:
            score = (
                int(is_primary_devtools_process) * 10
                + int(has_devtools_title) * 5
                + int(is_runtime_process)
            )
            score += int(bool(user32.IsWindowVisible(hwnd)))
            candidates.append((score, hwnd, thread_id))
        return True

    user32.EnumWindows(enum_windows_proc(callback), 0)
    return sorted(candidates, key=lambda item: item[0], reverse=True)


def activate():
    """Restore and foreground the best matching DevTools top-level window."""
    candidates = _window_candidates()
    if not candidates:
        return False

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    _, target_window, target_thread = candidates[0]
    foreground_window = user32.GetForegroundWindow()
    if foreground_window == target_window:
        return True

    current_thread = kernel32.GetCurrentThreadId()
    foreground_thread = (
        user32.GetWindowThreadProcessId(foreground_window, None)
        if foreground_window
        else 0
    )
    attached_threads = []
    for thread_id in (foreground_thread, target_thread):
        if thread_id and thread_id != current_thread and thread_id not in attached_threads:
            if user32.AttachThreadInput(current_thread, thread_id, True):
                attached_threads.append(thread_id)

    try:
        user32.ShowWindow(target_window, 9)
        user32.BringWindowToTop(target_window)
        return bool(user32.SetForegroundWindow(target_window))
    finally:
        for thread_id in reversed(attached_threads):
            user32.AttachThreadInput(current_thread, thread_id, False)


class ForegroundMonitor:
    def __init__(self, interval=0.8):
        self.interval = max(float(interval), 0.2)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="minium-devtools-foreground",
            daemon=True,
        )

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self):
        while not self._stop.is_set():
            try:
                activate()
            except Exception:
                pass
            self._stop.wait(self.interval)


def start_foreground_monitor():
    return ForegroundMonitor().start()
'''


def write_windows_text(path, content, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=encoding, newline="\r\n") as handle:
        handle.write(content.strip() + "\n")


def copy_runtime_files(source_root, package_dir):
    for relative_path in RUNTIME_FILES:
        source = source_root / relative_path
        if not source.is_file():
            raise FileNotFoundError(f"Agent runtime source is missing: {source}")
        target = package_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def replace_once(path, old, new):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"无法应用执行机兼容补丁，未找到预期内容: {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_runtime_files(package_dir):
    """为新版执行机注入 Windows DevTools 前台和元素定位兼容层。"""
    helper_path = package_dir / "tools" / "devtools_foreground.py"
    write_windows_text(helper_path, DEVTOOLS_FOREGROUND_HELPER)

    base_page_path = package_dir / "framework" / "base" / "base_page.py"
    replace_once(
        base_page_path,
        "import logging\nimport time\n",
        "import logging\nimport re\nimport time\n",
    )
    old_find_element = (
        '''    def find_element(self, selector, max_timeout=10):
        """轮询查找元素；超时后截图并抛出包含当前页面路径的异常。"""
        start_time = time.time()
        while time.time() - start_time < max_timeout:
            if self.page.element_is_exists(selector):
                return self.page.get_element(selector)
            self.wait(self.FIND_POLL_INTERVAL)
'''
        + "        \n"
        + '''        self.logger.error(f"Element not found: {selector}")
'''
    )
    new_find_element = r'''    @staticmethod
    def _text_selector_parts(selector):
        """识别常见文本 XPath，返回标签和文本，供 CSS 协议降级使用。"""
        if not isinstance(selector, str):
            return None
        match = re.fullmatch(
            r"""//([a-zA-Z][\w-]*)\[contains\(text\(\),\s*(['"])(.*?)\2\)\]""",
            selector.strip(),
        )
        if not match:
            return None
        return match.group(1), match.group(3)

    def _find_elements_without_xpath(self, selector):
        """将常见的 XPath 定位转换为 CSS 查询，避免调用失效的 XPath 协议。"""
        if not isinstance(selector, str):
            return None

        raw_selector = selector.strip()
        index = None
        indexed_match = re.fullmatch(r"\((.*)\)\[(\d+)\]", raw_selector)
        if indexed_match:
            raw_selector = indexed_match.group(1)
            index = int(indexed_match.group(2)) - 1

        segment = raw_selector.rsplit("//", 1)[-1]
        segment_match = re.fullmatch(
            r"([a-zA-Z*][\w-]*)\[(.*)\]",
            segment,
            re.DOTALL,
        )
        if not segment_match:
            return None

        tag = segment_match.group(1)
        conditions = segment_match.group(2)
        classes = re.findall(
            r"contains\(concat\(' ',\s*@class,\s*' '\),\s*' ([^']+) '\)",
            conditions,
        )
        classes.extend(
            re.findall(
                r"contains\(@class,\s*['\"]([^'\"]+)['\"]\)",
                conditions,
            )
        )
        text_match = re.search(
            r"contains\(text\(\),\s*['\"](.*?)['\"]\)",
            conditions,
        )
        src_match = re.search(
            r"contains\(@src,\s*['\"](.*?)['\"]\)",
            conditions,
        )
        if not classes and not text_match and not src_match:
            return None

        css_selector = "" if tag == "*" else tag
        css_selector += "".join(f".{class_name}" for class_name in classes)
        elements = self.page.get_elements(
            css_selector or "*",
            max_timeout=0,
            index=-1,
        )

        if text_match:
            expected_text = text_match.group(1)
            exact_elements = [
                element
                for element in elements
                if str(element.inner_text or "").strip() == expected_text
            ]
            elements = exact_elements or [
                element
                for element in elements
                if expected_text in str(element.inner_text or "")
            ]
        if src_match:
            expected_src = src_match.group(1)
            elements = [
                element
                for element in elements
                if expected_src in str(element.attribute("src")[0] or "")
            ]
        if index is not None:
            return elements[index:index + 1]
        return elements

    def _custom_tab_index(self, selector):
        """识别首页自定义 TabBar 的文本定位并返回对应索引。"""
        parts = self._text_selector_parts(selector)
        if not parts:
            return None
        try:
            page_path = self.page.path.rstrip("/") or "/"
        except Exception:
            return None
        if page_path != "/pages/index/index":
            return None
        return {
            "抽卡": 0,
            "抽赏": 1,
            "图鉴": 2,
            "我的": 3,
        }.get(parts[1])

    @staticmethod
    def _unwrap_app_result(value):
        """兼容不同 Minium 版本的 App.callFunction 返回结构。"""
        for _ in range(5):
            if isinstance(value, dict) and "result" in value:
                value = value["result"]
                continue
            if hasattr(value, "result"):
                value = value.result
                continue
            break
        if isinstance(value, dict) and set(value) == {"value"}:
            value = value["value"]
        return value

    def _try_custom_tab_click(self, selector):
        """通过 App.callFunction 触发首页自定义 TabBar，避开失效的元素协议。"""
        index = self._custom_tab_index(selector)
        if index is None:
            return False

        app_function = """function(index) {
            var pages = getCurrentPages();
            if (!pages || !pages.length) {
                return {ok: false, reason: "no current page"};
            }
            var page = pages[pages.length - 1];
            if (!page || typeof page.selectComponent !== "function") {
                return {ok: false, reason: "selectComponent unavailable"};
            }
            var component = page.selectComponent("my-tab-bar")
                || page.selectComponent(".my-tab-bar");
            if (!component || typeof component.triggerEvent !== "function") {
                return {ok: false, reason: "custom TabBar not found"};
            }
            component.triggerEvent("change", index);
            return {ok: true, index: index};
        }"""
        try:
            response = self.app.evaluate(
                app_function,
                args=[index],
                sync=True,
                desc=f"trigger custom TabBar index {index}",
            )
            result = self._unwrap_app_result(response)
            if isinstance(result, dict) and result.get("ok") is True:
                self.log_step(f"点击自定义 TabBar: {selector}")
                self.logger.info(
                    f"Custom TabBar click -> {selector}, index={index}"
                )
                return True
            self.logger.warning(
                f"Custom TabBar fallback did not run for {selector}: {result}"
            )
        except Exception as exc:
            self.logger.warning(
                f"Custom TabBar fallback failed for {selector}: {exc}"
            )
        return False

    def find_element(self, selector, max_timeout=10):
        """轮询查找元素；优先避开新开发者工具不响应的 XPath 文本协议。"""
        start_time = time.time()
        while time.time() - start_time < max_timeout:
            try:
                compatible_elements = self._find_elements_without_xpath(selector)
            except Exception as exc:
                self.logger.debug(f"CSS locator failed: {exc}")
                compatible_elements = None
            if compatible_elements is not None:
                if compatible_elements:
                    return compatible_elements[0]
            elif self.page.element_is_exists(selector):
                return self.page.get_element(selector)
            self.wait(self.FIND_POLL_INTERVAL)

        self.logger.error(f"Element not found: {selector}")
'''
    base_page = base_page_path.read_text(encoding="utf-8")
    if old_find_element not in base_page:
        raise RuntimeError(
            f"无法应用执行机元素定位兼容补丁，未找到预期内容: {base_page_path}"
        )
    base_page_path.write_text(
        base_page.replace(old_find_element, new_find_element, 1),
        encoding="utf-8",
    )

    replace_once(
        base_page_path,
        """        el = self.find_element(selector)
        self.log_step(f"点击元素: {selector}")
""",
        r'''        if self._try_custom_tab_click(selector):
            self.wait(after_wait, "after custom TabBar click")
            if capture:
                self.mini.capture(f"after_click_{int(time.time())}")
            if check_errors:
                self.wait(settle_wait, "request settle")
                self.check_console_errors()
                self.check_api_error(
                    ignore_errors=self.ignore_api_errors,
                    allowed_errors=self.allowed_api_errors,
                )
            return

        el = self.find_element(selector)
        self.log_step(f"点击元素: {selector}")
''',
    )

    replace_once(
        base_page_path,
        """        xpath = "//view[contains(text(), '系统繁忙') or contains(text(), '网络错误')] | //*[contains(@class, 'toast-error')]"
        if self.page.element_is_exists(xpath):
            raise AssertionError("Detected Error Toast on page! Interface might be failed.")
""",
        """        for text in ("系统繁忙", "网络错误"):
            selector = f"//view[contains(text(), '{text}')]"
            if self._find_elements_without_xpath(selector):
                raise AssertionError("Detected Error Toast on page! Interface might be failed.")
        if self._find_elements_without_xpath("//*[contains(@class, 'toast-error')]"):
            raise AssertionError("Detected Error Toast on page! Interface might be failed.")
""",
    )

    replace_once(
        base_page_path,
        """        while time.time() < end_time:
            if self.page.element_is_exists(selector):
                return True
            self.wait(0.5)
        return False
""",
        """        while time.time() < end_time:
            try:
                compatible_elements = self._find_elements_without_xpath(selector)
            except Exception as exc:
                self.logger.debug(f"CSS locator failed: {exc}")
                compatible_elements = None
            if compatible_elements is not None:
                if compatible_elements:
                    return True
            elif self.page.element_is_exists(selector):
                return True
            self.wait(0.5)
        return False
        """,
    )

    action_executor_path = package_dir / "framework" / "utils" / "action_executor.py"
    replace_once(
        action_executor_path,
        "            is_exist = self.mini.page.element_is_exists(expect_value)\n",
        "            is_exist = self.pages[\"front\"].element_exists(expect_value, timeout=3)\n",
    )
    replace_once(
        action_executor_path,
        "            element_text = self.mini.page.get_element(selector).inner_text\n",
        "            element_text = self.pages[\"front\"].find_element(selector).inner_text\n",
    )

    run_path = package_dir / "run.py"
    replace_once(
        run_path,
        "import shutil\nfrom pathlib import Path\n",
        "import shutil\nfrom pathlib import Path\n\n"
        "from tools.devtools_foreground import start_foreground_monitor\n",
    )
    replace_once(
        run_path,
        "import os\nimport time\n",
        "import os\nimport time\nimport json\n",
    )
    replace_once(
        run_path,
        "    return path\n\ndef kill_port(port):\n",
        """    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return path

    changed = False
    if "auto_capture" not in config:
        config["auto_capture"] = False
        changed = True
    if "check_mp_foreground" not in config:
        config["check_mp_foreground"] = True
        changed = True
    if changed:
        path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\\n",
            encoding="utf-8",
        )
    return path

def kill_port(port):
""",
    )
    replace_once(
        run_path,
        "    original_argv = sys.argv\n    \n    try:\n",
        "    original_argv = sys.argv\n    foreground_monitor = start_foreground_monitor()\n    \n    try:\n",
    )
    replace_once(
        run_path,
        "    finally:\n        sys.argv = original_argv\n        \n        # 3. 显式生成报告到 report 目录，避免覆盖 outputs 导致的异常\n",
        "    finally:\n        foreground_monitor.stop()\n        sys.argv = original_argv\n        \n        # 3. 显式生成报告到 report 目录，避免覆盖 outputs 导致的异常\n",
    )

    config_path = package_dir / "config.example.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.setdefault("auto_capture", False)
    config.setdefault("check_mp_foreground", True)
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_package_files(package_dir, version):
    if not INSTALLATION_GUIDE.is_file():
        raise FileNotFoundError(f"Installation guide is missing: {INSTALLATION_GUIDE}")

    write_windows_text(
        package_dir / "install_agent.ps1",
        INSTALL_SCRIPT,
        encoding="utf-8-sig",
    )
    write_windows_text(package_dir / "start_agent.cmd", START_SCRIPT)
    write_windows_text(package_dir / "README.md", PACKAGE_README)
    shutil.copy2(INSTALLATION_GUIDE, package_dir / "INSTALLATION_GUIDE.md")
    (package_dir / "runtime_version.json").write_text(
        json.dumps(
            {
                "runtime_version": version,
                "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "runtime_type": "windows_execution_agent",
                "installer_encoding": "utf-8-sig",
                "powershell_compatibility": [
                    "Windows PowerShell 5.1",
                    "PowerShell 7",
                ],
                "files": list(RUNTIME_FILES),
                "generated_files": [
                    "install_agent.ps1",
                    "start_agent.cmd",
                    "README.md",
                    "INSTALLATION_GUIDE.md",
                    "runtime_version.json",
                    "tools/devtools_foreground.py",
                ],
                "compatibility": [
                    "Keep WeChat DevTools in the foreground during Minium execution",
                    "Disable Minium setup and teardown screenshots by default",
                    "Use App.callFunction for the custom home TabBar text actions",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def create_zip(package_dir, zip_path):
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package_dir.parent))


def write_checksum(zip_path):
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    checksum_path = zip_path.with_suffix(zip_path.suffix + ".sha256")
    checksum_path.write_text(
        f"{digest}  {zip_path.name}\n",
        encoding="ascii",
    )
    return checksum_path


def build_package(source_root, output_dir, version):
    source_root = source_root.resolve()
    output_dir = output_dir.resolve()
    package_name = f"minitest-agent-runtime-{version}"
    package_dir = output_dir / package_name
    zip_path = output_dir / f"{package_name}.zip"
    checksum_path = zip_path.with_suffix(zip_path.suffix + ".sha256")

    output_dir.mkdir(parents=True, exist_ok=True)
    if package_dir.exists():
        shutil.rmtree(package_dir)
    for path in (zip_path, checksum_path):
        if path.exists():
            path.unlink()

    package_dir.mkdir()
    copy_runtime_files(source_root, package_dir)
    patch_runtime_files(package_dir)
    write_package_files(package_dir, version)
    create_zip(package_dir, zip_path)
    checksum_path = write_checksum(zip_path)
    return package_dir, zip_path, checksum_path


def main():
    parser = argparse.ArgumentParser(
        description="Build the Windows Minitest execution-agent ZIP."
    )
    parser.add_argument(
        "--source-root",
        default=str(DEFAULT_SOURCE_ROOT),
        help="Full Minitest source repository.",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "release"),
        help="Release output directory.",
    )
    parser.add_argument(
        "--version",
        default=datetime.now().strftime("%Y.%m.%d.1"),
        help="Release version, for example 2026.07.28.1.",
    )
    args = parser.parse_args()

    package_dir, zip_path, checksum_path = build_package(
        source_root=Path(args.source_root),
        output_dir=Path(args.output),
        version=str(args.version).strip(),
    )
    print(f"Agent runtime directory: {package_dir}")
    print(f"Agent runtime ZIP: {zip_path}")
    print(f"SHA-256 file: {checksum_path}")


if __name__ == "__main__":
    main()
