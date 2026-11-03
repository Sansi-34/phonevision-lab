<#
.SYNOPSIS
    PhoneVision Lab Web — Windows x64 便携包构建脚本（PyInstaller onedir + ZIP）。

.DESCRIPTION
    在干净的 .venv-web-build 虚拟环境里安装锁定依赖、运行网页测试套件、
    执行 PyInstaller 打包，校验 EXE，生成 ZIP 与 SHA-256。

    与桌面端 build_windows.ps1 的关键差异：
      - 不安装 PySide6 / TensorFlow：网页后端只需 opencv + numpy + requests；
      - 测试范围是 web\tests（网页服务 + 前端契约），不跑 Qt 界面测试；
      - 产物名 PhoneVisionLabWeb-<version>-win-x64.zip。

    清理只允许删除 web\build、web\dist、仓库根 artifacts\web 内的产物。
    本脚本不含任何本机绝对路径/用户名。

.PARAMETER SkipTests
    跳过测试（默认运行）。
.PARAMETER NoInstall
    跳过依赖安装（假设 .venv-web-build 已就绪）。
.PARAMETER KeepVenv
    构建后保留虚拟环境（默认删除以节省磁盘）。

.EXAMPLE
    .\web\scripts\build_windows.ps1                  # 完整构建
    .\web\scripts\build_windows.ps1 -SkipTests       # 跳过测试
    .\web\scripts\build_windows.ps1 -NoInstall       # 复用已有 venv
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$NoInstall,
    [switch]$KeepVenv
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ------------------------------------------------------------------
# 0. 基础路径（全部相对推导，无硬编码本机路径）
# ------------------------------------------------------------------
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path   # web/scripts/
$WebRoot    = Split-Path -Parent $ScriptDir                     # web/
$RepoParent = Split-Path -Parent $WebRoot                       # 仓库根
$BuildVenv  = Join-Path $WebRoot ".venv-web-build"
$PyInst     = Join-Path $BuildVenv "Scripts\pyinstaller.exe"
$BuildDir   = Join-Path $WebRoot "build"
$DistDir    = Join-Path $WebRoot "dist"
$Artifacts  = Join-Path $RepoParent "artifacts\web"
$SpecFile   = Join-Path $WebRoot "packaging\PhoneVisionLabWeb.spec"
$ReqFile    = Join-Path $WebRoot "packaging\requirements-web-build.txt"

# 版本来源：复用桌面端 qt_client/version.py（唯一事实来源）。
$VersionPy  = Join-Path $RepoParent "pc-client\qt_client\version.py"
$AppSlug    = "PhoneVisionLabWeb"

Write-Host "== PhoneVision Lab Web portable build ==" -ForegroundColor Cyan
Write-Host "  web        : $WebRoot"
Write-Host "  venv       : $BuildVenv"

# ------------------------------------------------------------------
# 1. 环境检查
# ------------------------------------------------------------------
if ($IsMacOS -or $IsLinux) { throw "此脚本只支持 Windows。" }
if ($PSVersionTable.PSVersion.Major -lt 5) { throw "需要 PowerShell 5.1+。" }
if (-not (Test-Path $VersionPy)) { throw "找不到 version.py：$VersionPy" }
if (-not (Test-Path $SpecFile)) { throw "找不到 spec：$SpecFile" }

$VersionMatch = Select-String -Path $VersionPy -Pattern '__version__\s*=\s*"([^"]+)"'
if (-not $VersionMatch) { throw "version.py 中未找到 __version__。" }
$Version    = $VersionMatch.Matches[0].Groups[1].Value
$VersionSafe = ($Version -replace '[^\w.-]', '_')
$Product    = "$AppSlug-$VersionSafe-win-x64"

# ------------------------------------------------------------------
# 2. 构建虚拟环境
# ------------------------------------------------------------------
function Test-IsBuildVenv {
    $exe = Join-Path $BuildVenv "Scripts\python.exe"
    if (-not (Test-Path $exe)) { return $false }
    try {
        & $exe -c "print('ok')" 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

if (-not (Test-Path $BuildVenv)) {
    Write-Host "创建构建虚拟环境：$BuildVenv" -ForegroundColor Cyan
    python -m venv $BuildVenv
    if ($LASTEXITCODE -ne 0) { throw "创建 venv 失败。" }
} elseif (-not (Test-IsBuildVenv)) {
    throw ".venv-web-build 已存在但损坏，请手动删除后重试（脚本不自动删除）。"
} else {
    Write-Host ".venv-web-build 已存在且可用。" -ForegroundColor Green
}

$Py  = Join-Path $BuildVenv "Scripts\python.exe"
$Pip = Join-Path $BuildVenv "Scripts\pip.exe"

# ------------------------------------------------------------------
# 3. 安装构建依赖（不含 PySide6 / TensorFlow）
# ------------------------------------------------------------------
if (-not $NoInstall) {
    Write-Host "== 安装构建依赖 ==" -ForegroundColor Cyan
    if (-not (Test-Path $ReqFile)) { throw "找不到依赖清单：$ReqFile" }
    & $Pip install --disable-pip-version-check --upgrade pip | Out-Host
    & $Pip install --disable-pip-version-check -r $ReqFile
    if ($LASTEXITCODE -ne 0) { throw "依赖安装失败。" }
} else {
    Write-Host "== 跳过依赖安装（-NoInstall）==" -ForegroundColor Yellow
}

if (-not (Test-Path $PyInst)) { throw "PyInstaller 不可用：$PyInst" }

# ------------------------------------------------------------------
# 4. 测试（web\tests：后端单元 + HTTP 集成 + 前端契约）
# ------------------------------------------------------------------
if (-not $SkipTests) {
    Write-Host "== 运行网页测试套件 ==" -ForegroundColor Cyan
    Push-Location $WebRoot
    try {
        & $Py -m unittest discover -s tests -t tests
        if ($LASTEXITCODE -ne 0) { throw "测试失败，终止构建。" }
    } finally { Pop-Location }
} else {
    Write-Host "== 跳过测试（-SkipTests）==" -ForegroundColor Yellow
}

# ------------------------------------------------------------------
# 5. PyInstaller 打包
# ------------------------------------------------------------------
Write-Host "== PyInstaller 打包 ==" -ForegroundColor Cyan
Push-Location $WebRoot
try {
    & $PyInst --noconfirm --clean --distpath $DistDir --workpath $BuildDir $SpecFile
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败。" }
} finally { Pop-Location }

$ExePath = Join-Path $DistDir "$AppSlug\$AppSlug.exe"
if (-not (Test-Path $ExePath)) { throw "打包后找不到 EXE：$ExePath" }
Write-Host "EXE 已生成：$ExePath" -ForegroundColor Green

# ------------------------------------------------------------------
# 6. 附带说明文件
# ------------------------------------------------------------------
$DistApp = Join-Path $DistDir $AppSlug
$Readme = @"
PhoneVision Lab Web（便携版）
=============================

启动：双击 $AppSlug.exe
  - 会自动启动本地服务并打开浏览器（默认 http://127.0.0.1:8088）
  - 关闭"服务正在运行"窗口即停止服务
  - 服务只监听本机 127.0.0.1，同一 Wi-Fi 下的其他设备不能访问

第一次使用：
  1. 手机与电脑连同一个 Wi-Fi
  2. 手机打开 PhoneVision Lab App，点击"开始推流"，记下 IP
  3. 浏览器里进入"实验台"，填入该 IP 与端口 8080，点击连接

训练模型（可选）：
  便携版未内置 TensorFlow。需要训练时，在浏览器打开"模型训练"页，
  按页面提示在电脑上安装：
      pip install -r pc-client\requirements.txt -r pc-client\requirements-train.txt
  然后用源码方式启动服务（python -m web.server）即可训练。

日志位置：
  %LOCALAPPDATA%\PhoneVisionLab\logs\phonevision-web.log

完整说明：docs\web-platform.zh-CN.md
"@
Set-Content -Path (Join-Path $DistApp "README.txt") -Value $Readme -Encoding UTF8

# ------------------------------------------------------------------
# 7. ZIP + SHA-256
# ------------------------------------------------------------------
if (-not (Test-Path $Artifacts)) { New-Item -ItemType Directory -Path $Artifacts -Force | Out-Null }
$ZipPath = Join-Path $Artifacts "$Product.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

Write-Host "== 生成 ZIP ==" -ForegroundColor Cyan
Compress-Archive -Path (Join-Path $DistApp "*") -DestinationPath $ZipPath -CompressionLevel Optimal
if (-not (Test-Path $ZipPath)) { throw "ZIP 生成失败。" }

$Hash = (Get-FileHash -Path $ZipPath -Algorithm SHA256).Hash.ToLower()
$HashLine = "$Hash  $(Split-Path -Leaf $ZipPath)"
Set-Content -Path "$ZipPath.sha256" -Value $HashLine -Encoding ASCII

# 附带构建信息（不含本机路径/用户名）
$BuildInfo = [ordered]@{
    app        = $AppSlug
    version    = $Version
    platform   = "win-x64"
    built_at   = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    sha256     = $Hash
    entry      = "launcher.py"
    dependencies = @("opencv-python", "numpy", "requests", "pyinstaller")
    notes      = "Web client portable build. PySide6 and TensorFlow are not bundled."
} | ConvertTo-Json -Depth 4
Set-Content -Path (Join-Path $Artifacts "$Product.build-info.json") -Value $BuildInfo -Encoding UTF8

# ------------------------------------------------------------------
# 8. 汇总
# ------------------------------------------------------------------
$ZipSize = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
$AppSize = [math]::Round(((Get-ChildItem $DistApp -Recurse -File | Measure-Object -Property Length -Sum).Sum) / 1MB, 1)
$FileCount = (Get-ChildItem $DistApp -Recurse -File).Count

Write-Host ""
Write-Host "== 构建完成 ==" -ForegroundColor Green
Write-Host "  目录体积 : $AppSize MB（$FileCount 个文件）"
Write-Host "  ZIP      : $ZipPath（$ZipSize MB）"
Write-Host "  SHA-256  : $Hash"

if (-not $KeepVenv) {
    Write-Host "== 清理构建虚拟环境 ==" -ForegroundColor Cyan
    Remove-Item $BuildVenv -Recurse -Force -ErrorAction SilentlyContinue
}
