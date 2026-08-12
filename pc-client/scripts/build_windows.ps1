<#
.SYNOPSIS
    PhoneVision Lab — Windows x64 便携包构建脚本（PyInstaller onedir + ZIP）。

.DESCRIPTION
    在干净的 .venv-build 虚拟环境里安装锁定依赖、运行全量测试、执行
    PyInstaller 打包，校验 EXE，复制 README/许可/构建信息，生成 ZIP 与
    SHA-256，并输出包大小与文件数。

    本脚本不含任何本机绝对路径/用户名；所有路径由脚本所在位置与
    仓库结构相对推导。清理只允许删除 pc-client\build、pc-client\dist、
    仓库根 artifacts\windows 内解析到的产物。

.PARAMETER SkipTests
    跳过全量测试（默认运行）。
.PARAMETER NoInstall
    跳过依赖安装/校验（假设 .venv-build 已就绪；默认按需安装）。
.PARAMETER Config
    构建配置（当前仅 "release"）。

.EXAMPLE
    .\scripts\build_windows.ps1                  # 完整构建
    .\scripts\build_windows.ps1 -SkipTests       # 跳过测试
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$NoInstall,
    [string]$Config = "release"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ------------------------------------------------------------------
# 0. 基础路径（全部相对推导，无硬编码本机路径）
# ------------------------------------------------------------------
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptDir                 # pc-client/
$RepoParent = Split-Path -Parent $RepoRoot                  # 仓库根
$BuildVenv  = Join-Path $RepoRoot ".venv-build"
$PyInst     = Join-Path $BuildVenv "Scripts\pyinstaller.exe"
$BuildDir   = Join-Path $RepoRoot "build"
$DistDir    = Join-Path $RepoRoot "dist"
$Artifacts  = Join-Path $RepoParent "artifacts\windows"
$SpecFile   = Join-Path $RepoRoot "packaging\PhoneVisionLab.spec"

# 版本来源：qt_client/version.py（唯一事实来源）。
$VersionPy = Join-Path $RepoRoot "qt_client\version.py"
$AppName   = "PhoneVisionLab"
$Version   = $null

Write-Host "== PhoneVision Lab Windows portable build ==" -ForegroundColor Cyan
Write-Host "  repo       : $RepoRoot"
Write-Host "  venv       : $BuildVenv"
Write-Host "  config     : $Config"

# ------------------------------------------------------------------
# 1. 环境检查
# ------------------------------------------------------------------
if ($IsMacOS -or $IsLinux) {
    throw "此脚本只支持 Windows。"
}
if ($PSVersionTable.PSVersion.Major -lt 5) {
    throw "需要 PowerShell 5.1+。"
}
if (-not (Test-Path $VersionPy)) {
    throw "找不到 version.py：$VersionPy"
}

# 解析 version.py 中的 __version__（不 import，避免依赖本机 Python）。
$VersionMatch = Select-String -Path $VersionPy -Pattern '__version__\s*=\s*"([^"]+)"'
if (-not $VersionMatch) {
    throw "version.py 中未找到 __version__。"
}
$Version = $VersionMatch.Matches[0].Groups[1].Value
# 版本用于产物命名时，把 alpha 等预发布串折成合法文件名（0.1.0-alpha.1 -> 0.1.0-alpha_1）。
$VersionSafe = ($Version -replace '[^\w.-]', '_')
$Product = "$AppName-$VersionSafe-win-x64"

# ------------------------------------------------------------------
# 2. .venv-build 虚拟环境
# ------------------------------------------------------------------
function Test-IsBuildVenv {
    $exe = Join-Path $BuildVenv "Scripts\python.exe"
    if (-not (Test-Path $exe)) { return $false }
    # 双保险：存在 python.exe 且能运行。
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
    throw ".venv-build 已存在但损坏，请手动删除后重试（脚本不自动删除）。"
} else {
    Write-Host ".venv-build 已存在且可用。" -ForegroundColor Green
}

$Py = Join-Path $BuildVenv "Scripts\python.exe"
$Pip = Join-Path $BuildVenv "Scripts\pip.exe"

# ------------------------------------------------------------------
# 3. 安装/验证构建依赖
# ------------------------------------------------------------------
if (-not $NoInstall) {
    Write-Host "== 安装构建依赖（requirements-build.txt）==" -ForegroundColor Cyan
    & $Pip install --disable-pip-version-check --upgrade pip | Out-Host
    & $Pip install --disable-pip-version-check -r (Join-Path $RepoRoot "packaging\requirements-build.txt")
    if ($LASTEXITCODE -ne 0) { throw "构建依赖安装失败。" }
} else {
    Write-Host "== 跳过依赖安装（-NoInstall）==" -ForegroundColor Yellow
}

# 验证 PyInstaller 可用。
if (-not (Test-Path $PyInst)) {
    throw "找不到 pyinstaller：$PyInst（请去掉 -NoInstall 或检查安装）。"
}
& $Py -c "import PyInstaller; print('PyInstaller', PyInstaller.__version__)"

# ------------------------------------------------------------------
# 4. 全量测试（默认运行；-SkipTests 跳过）
# ------------------------------------------------------------------
if ($SkipTests) {
    Write-Host "== 跳过测试（-SkipTests）==" -ForegroundColor Yellow
} else {
    Write-Host "== 运行全量测试（offscreen）==" -ForegroundColor Cyan
    Push-Location $RepoRoot
    try {
        $env:QT_QPA_PLATFORM = "offscreen"
        & $Py -m unittest discover -s tests -t tests
        if ($LASTEXITCODE -ne 0) {
            Write-Host "测试失败（exit=$LASTEXITCODE）。构建中止。" -ForegroundColor Red
            throw "测试未通过。"
        }
    } finally {
        Pop-Location
        Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    }
    Write-Host "测试通过。" -ForegroundColor Green
}

# ------------------------------------------------------------------
# 5. 清理上次产物（只允许删除解析到的 pc-client\build 与 pc-client\dist）
# ------------------------------------------------------------------
$RepoRootResolved = [System.IO.Path]::GetFullPath($RepoRoot)
foreach ($target in @($BuildDir, $DistDir)) {
    $targetResolved = [System.IO.Path]::GetFullPath($target)
    # 双保险：目标必须严格位于 pc-client 仓库根之下，且确实是 build/dist。
    $isUnderRepo = $targetResolved.StartsWith($RepoRootResolved + [System.IO.Path]::DirectorySeparatorChar)
    $isAllowedName = $targetResolved.EndsWith("\build") -or $targetResolved.EndsWith("\dist")
    if ($isUnderRepo -and $isAllowedName -and (Test-Path $target)) {
        Write-Host "清理：$target" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $target
    } else {
        throw "拒绝清理非预期目录：$target"
    }
}

# ------------------------------------------------------------------
# 6. 运行 PyInstaller
# ------------------------------------------------------------------
Write-Host "== PyInstaller（onedir, windowed）==" -ForegroundColor Cyan
Push-Location $RepoRoot
try {
    & $PyInst --noconfirm --clean $SpecFile
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败。" }
} finally { Pop-Location }

$ExePath = Join-Path $DistDir "$AppName\PhoneVisionLab.exe"
if (-not (Test-Path $ExePath)) {
    throw "未生成可执行文件：$ExePath"
}
Write-Host "EXE 已生成：$ExePath" -ForegroundColor Green
$ExeSize = (Get-Item $ExePath).Length
Write-Host ("EXE 大小：{0:N2} MB" -f ($ExeSize / 1MB))

# ------------------------------------------------------------------
# 7. 复制说明 / 许可 / 构建信息到产物目录
# ------------------------------------------------------------------
$OutDir = Join-Path $DistDir $AppName
$pkgDir = Join-Path $RepoRoot "packaging"

Copy-Item (Join-Path $pkgDir "README.portable.txt") -Destination (Join-Path $OutDir "README.portable.txt") -Force
Copy-Item (Join-Path $pkgDir "THIRD_PARTY_NOTICES.md") -Destination (Join-Path $OutDir "THIRD_PARTY_NOTICES.md") -Force

# 许可目录（licenses/）
$LicDest = Join-Path $OutDir "licenses"
if (Test-Path (Join-Path $pkgDir "licenses")) {
    if (-not (Test-Path $LicDest)) { New-Item -ItemType Directory -Path $LicDest | Out-Null }
    Get-ChildItem (Join-Path $pkgDir "licenses") -File | ForEach-Object {
        Copy-Item $_.FullName -Destination (Join-Path $LicDest $_.Name) -Force
    }
}

# 仓库根 LICENSE（本项目 MIT）
$RepoLicense = Join-Path $RepoParent "LICENSE"
if (Test-Path $RepoLicense) {
    Copy-Item $RepoLicense -Destination (Join-Path $OutDir "LICENSE") -Force
}

# build-info.json（版本/构建时间/Python/PyInstaller/关键依赖版本；无本机路径、
# 用户名或密钥）。gitCommit 由 `git rev-parse HEAD` 动态取当前提交，避免陈旧。
$PyVer = (& $Py -c "import platform; print(platform.python_version())").Trim()
$PyInstVer = (& $Py -c "import PyInstaller; print(PyInstaller.__version__)").Trim()
$PySide6Ver = (& $Py -c "import PySide6; print(PySide6.__version__)").Trim()
$OpenCvVer = (& $Py -c "import cv2; print(cv2.__version__)").Trim()
$NumpyVer = (& $Py -c "import numpy; print(numpy.__version__)").Trim()
$GitCommit = (git -C $RepoParent rev-parse HEAD 2>$null).Trim()
$BuildStampUtc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
$BuildInfoJson = [ordered]@{
    applicationVersion = $Version
    gitCommit          = $GitCommit
    buildTimeUtc       = $BuildStampUtc
    pythonVersion      = $PyVer
    architecture       = "x64"
    pyinstaller        = $PyInstVer
    PySide6            = $PySide6Ver
    opencv             = $OpenCvVer
    numpy              = $NumpyVer
} | ConvertTo-Json
Set-Content -Path (Join-Path $OutDir "build-info.json") -Value $BuildInfoJson -Encoding UTF8

# ------------------------------------------------------------------
# 8. 生成 ZIP + SHA-256（放入仓库根 artifacts/windows）
# ------------------------------------------------------------------
if (-not (Test-Path $Artifacts)) {
    New-Item -ItemType Directory -Path $Artifacts | Out-Null
}
$ZipPath = Join-Path $Artifacts "$Product.zip"

# 从 dist 目录内打包（zip 内第一级为 PhoneVisionLab\）
Push-Location $DistDir
try {
    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
    Compress-Archive -Path (Join-Path $DistDir $AppName) -DestinationPath $ZipPath -CompressionLevel Optimal
    if (-not (Test-Path $ZipPath)) { throw "ZIP 生成失败：$ZipPath" }
} finally { Pop-Location }

# SHA-256（文件与整个 ZIP）
$Hash = Get-FileHash -Algorithm SHA256 -Path $ZipPath
Set-Content -Path (Join-Path $Artifacts "$Product.zip.sha256") `
    -Value ("{0}  {1}" -f $Hash.Hash, (Split-Path -Leaf $ZipPath)) -Encoding ASCII

# 校验总入口
$EntryTotal = (Get-ChildItem -Recurse -File $OutDir | Measure-Object).Count
$ZipSize = (Get-Item $ZipPath).Length

Write-Host "== 完成 ==" -ForegroundColor Green
Write-Host ("  ZIP        : {0}" -f $ZipPath)
Write-Host ("  ZIP 大小   : {0:N2} MB" -f ($ZipSize / 1MB))
Write-Host ("  包内文件数 : {0}" -f $EntryTotal)
Write-Host ("  SHA-256    : {0}" -f $Hash.Hash)
Write-Host ("  产物目录   : {0}" -f $Artifacts)
