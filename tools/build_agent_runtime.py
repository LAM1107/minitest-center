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
