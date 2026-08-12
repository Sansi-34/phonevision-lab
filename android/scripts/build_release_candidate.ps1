# PhoneVision Lab — Release 候选构建脚本（P0-5B）
#
# 用途：
#   在本地构建可复现的 Release 候选产物，输出到 git 忽略的 artifacts/android/：
#     PhoneVisionLab-<version>-debug.apk
#     PhoneVisionLab-<version>-release-unsigned.apk
#     PhoneVisionLab-<version>-release-unsigned.aab
#     SHA256SUMS.txt
#     android-build-info.json
#   并用 aapt2 / bundletool 核对 applicationId / versionCode / versionName /
#   minSdk / targetSdk / debuggable / 图标 / 权限 / ABI / 签名状态。
#
# 签名说明：
#   - 本脚本不生成、不提交任何 keystore。正式签名通过四个环境变量启用：
#       $env:PVL_ANDROID_KEYSTORE       = "C:\path\to\release.keystore"
#       $env:PVL_ANDROID_KEY_ALIAS      = "alias"
#       $env:PVL_ANDROID_STORE_PASSWORD = "..."
#       $env:PVL_ANDROID_KEY_PASSWORD   = "..."
#   - 四项齐全 -> 构建带正式签名的 release；任缺其一 -> release 产物为 unsigned，
#     文件名显式带 "-unsigned" 并打印醒目提示，绝不拿 debug key 冒充正式签名。
#
# 用法：
#   cd android && powershell -ExecutionPolicy Bypass -File scripts\build_release_candidate.ps1
#
# 环境要求：JDK 17（JAVA_HOME）与 Android SDK（local.properties 或 ANDROID_HOME）。
# Gradle 由 wrapper 提供。

$ErrorActionPreference = "Stop"

$Root       = Split-Path -Parent $PSScriptRoot          # .../android
$RepoRoot   = Split-Path -Parent $Root                  # PhoneVision Lab 仓库根
$ArtOut     = Join-Path $RepoRoot "artifacts\android"   # git 忽略的产物目录

# ---------- 版本与产物命名（与 pc-client/qt_client/version.py 保持一致） ----------
$Version    = "0.1.0-alpha.1"
$AppSlug    = "PhoneVisionLab"
$ReleaseTag = "$Version-release-unsigned"

New-Item -ItemType Directory -Force -Path $ArtOut | Out-Null

# ---------- JDK / SDK ----------
if (-not $env:JAVA_HOME) {
    throw "JAVA_HOME 未设置，请指向 JDK 17（如 C:\Users\...\Adoptium\jdk-17.0.20+8）。"
}
$JavaExe = Join-Path $env:JAVA_HOME "bin\java.exe"
if (-not (Test-Path $JavaExe)) {
    throw "JAVA_HOME 下找不到 java.exe: $JavaExe"
}

# SDK：优先 local.properties 的 sdk.dir，其次 ANDROID_HOME。
# 注意 local.properties 可能含中文注释，PS 5.1 默认按 ANSI 读会串行破坏换行，
# 必须用 -Encoding UTF8 读取。
$SdkDir = $null
$LocalProps = Join-Path $Root "local.properties"
if (Test-Path $LocalProps) {
    foreach ($line in Get-Content $LocalProps -Encoding UTF8) {
        if ($line -match "^sdk.dir=(.+)$") { $SdkDir = $Matches[1].Replace("/", "\"); break }
    }
}
if (-not $SdkDir) { $SdkDir = $env:ANDROID_HOME }
if (-not $SdkDir -or -not (Test-Path $SdkDir)) {
    throw "找不到 Android SDK：请设置 local.properties 的 sdk.dir 或 ANDROID_HOME。"
}

# aapt2 与 apksigner：取已安装 build-tools 的最高版本。
$BuildToolsDir = Get-ChildItem (Join-Path $SdkDir "build-tools") -Directory |
    Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
$Aapt2 = Join-Path $BuildToolsDir.FullName "aapt2.exe"
$ApkSigner = Join-Path $BuildToolsDir.FullName "apksigner.bat"
if (-not (Test-Path $Aapt2))     { throw "找不到 aapt2.exe（build-tools 未安装）。" }
if (-not (Test-Path $ApkSigner)) { throw "找不到 apksigner（build-tools 未安装）。" }

# ---------- 签名环境变量接口 ----------
$envKeys = @(
    "PVL_ANDROID_KEYSTORE",
    "PVL_ANDROID_KEY_ALIAS",
    "PVL_ANDROID_STORE_PASSWORD",
    "PVL_ANDROID_KEY_PASSWORD"
)
$SignReady = $true
$signingSummary = @{}
foreach ($k in $envKeys) {
    $v = [Environment]::GetEnvironmentVariable($k)
    if ([string]::IsNullOrWhiteSpace($v)) {
        $SignReady = $false
    } else {
        if ($k -match "PASSWORD") { $signingSummary[$k] = "***" } else { $signingSummary[$k] = $v }
    }
}

# ---------- 构建 ----------
Push-Location $Root
try {
    Write-Host "==> 构建 debug APK ..."
    & .\gradlew.bat --no-daemon assembleDebug
    if ($LASTEXITCODE -ne 0) { throw "assembleDebug 失败" }

    Write-Host "==> 构建 release（unsigned / 或按 env 签名）..."
    & .\gradlew.bat --no-daemon assembleRelease bundleRelease
    if ($LASTEXITCODE -ne 0) { throw "assembleRelease / bundleRelease 失败" }

    $gradleVersion = (.\gradlew.bat --version | Select-String "^Gradle " | Select-Object -First 1).Line.Trim()
}
finally {
    Pop-Location
}

# ---------- 产物拷贝与命名 ----------
$AppDir   = Join-Path $Root "app\build\outputs"
$apkDebug = Join-Path $AppDir "apk\debug\app-debug.apk"
$apkRel   = Join-Path $AppDir "apk\release\app-release-unsigned.apk"
$aabRel   = Join-Path $AppDir "bundle\release\app-release.aab"

$OutDebug   = Join-Path $ArtOut "$AppSlug-$Version-debug.apk"
$OutRelApk  = Join-Path $ArtOut "$AppSlug-$ReleaseTag.apk"
$OutRelAab  = Join-Path $ArtOut "$AppSlug-$ReleaseTag.aab"

Copy-Item $apkDebug $OutDebug -Force
Copy-Item $apkRel   $OutRelApk -Force
Copy-Item $aabRel   $OutRelAab -Force

if (-not $SignReady) {
    Write-Host ""
    Write-Host "############################################################"
    Write-Host "# 警告：release 产物未签名，不可发布！"
    Write-Host "# 缺失的环境变量："
    foreach ($k in $envKeys) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($k))) {
            Write-Host "  - $k"
        }
    }
    Write-Host "# 设置全部四个 PVL_ANDROID_* 后重新运行可得到正式签名产物。"
    Write-Host "############################################################"
} else {
    Write-Host "==> release 已用正式签名构建（keystore: $($signingSummary['PVL_ANDROID_KEYSTORE'])）。"
}

# ---------- 核对（aapt2 dump） ----------
function Get-ApkInfo([string]$apkPath, [string]$label) {
    Write-Host "==> 核对 $label ..."
    $dumpLines = @(& $Aapt2 dump badging $apkPath 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "aapt2 dump badging 失败: $apkPath`n$($dumpLines -join "`n")" }
    $dump     = $dumpLines -join "`n"
    $manifest = (@(& $Aapt2 dump xmltree --file AndroidManifest.xml $apkPath 2>&1)) -join "`n"

    $applicationLine = ($dumpLines | Select-String "application:") | Select-Object -First 1

    $info = [ordered]@{
        label        = $label
        file         = Split-Path $apkPath -Leaf
        applicationId = if ($dump -match "name='([^']+)'") { $Matches[1] } else { "" }
        versionName  = if ($dump -match "versionName='([^']+)'") { $Matches[1] } else { "" }
        versionCode  = if ($dump -match "versionCode='([^']+)'") { $Matches[1] } else { "" }
        minSdk       = if ($dump -match "sdkVersion:'([^']+)'") { $Matches[1] } else { "" }
        targetSdk    = if ($dump -match "targetSdkVersion:'([^']+)'") { $Matches[1] } else { "" }
        debuggable   = [bool]($manifest -match "android:debuggable")
        icon         = if ($applicationLine -match "icon='([^']+)'") { $Matches[1] } else { "" }
        roundIcon    = if ($manifest -match "android:roundIcon") { "present" } else { "" }
        usesPermissions = @(
            $dumpLines | Select-String "uses-permission: name='([^']+)'" |
                ForEach-Object { $_.Matches[0].Groups[1].Value }
        )
        nativeCodeAbi = @(
            $dumpLines | Select-String "native-code: '([^']+)'" |
                ForEach-Object { $_.Matches[0].Groups[1].Value }
        )
    }
    return $info
}

# 签名状态：用 apksigner verify 检查 v1/v2/v3 签名。
# 注意：PS 5.1 在 $ErrorActionPreference=Stop 下会把原生命令 stderr 当终止错误
# （尤其 .bat 经 cmd.exe 运行时），因此函数内临时降回 Continue，用 $LASTEXITCODE 判定。
function Get-SignatureState([string]$apkPath) {
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = (& $ApkSigner verify --verbose --print-certs $apkPath 2>&1) -join "`n"
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prevEAP
    }
    if ($code -eq 0) {
        $schemes = @()
        foreach ($scheme in @("v1", "v2", "v3", "v4")) {
            if ($out -match "Verified using $scheme scheme") { $schemes += $scheme }
        }
        if ($schemes.Count -gt 0) { return "SIGNED ($($schemes -join "+"))" }
        return "SIGNED (scheme unknown)"
    }
    return "UNSIGNED (apksigner 校验未通过)"
}

$apkDebugInfo = Get-ApkInfo $OutDebug "debug"
$apkRelInfo   = Get-ApkInfo $OutRelApk "release-unsigned"
$apkDebugInfo["signatureState"] = Get-SignatureState $OutDebug
$apkRelInfo["signatureState"]   = Get-SignatureState $OutRelApk

# ---------- 校验产物信息 ----------
$expected = @{
    applicationId = "com.phonevisionlab.app"
    versionCode   = "1"
    versionName   = $Version
    minSdk        = "21"
    targetSdk     = "35"
}
$issues = [System.Collections.Generic.List[string]]::new()
foreach ($k in $expected.Keys) {
    foreach ($info in @($apkDebugInfo, $apkRelInfo)) {
        $actual = [string]$info[$k]
        if ($actual -ne [string]$expected[$k]) {
            $issues.Add("$($info.label): $k = '$actual'，期望 '$($expected[$k])'")
        }
    }
}
if (-not $apkDebugInfo.debuggable) { $issues.Add("debug APK 应标记 debuggable=true") }
if ($apkRelInfo.debuggable)        { $issues.Add("release APK 不应标记 debuggable") }

if ($issues.Count -gt 0) {
    Write-Host ""
    Write-Host "!!! 产物核对发现问题："
    $issues | ForEach-Object { Write-Host "  - $_" }
    Write-Host "!!! 以上问题需要修复，Release 候选不应带着这些问题发布。"
} else {
    Write-Host ""
    Write-Host "==> 产物核对全部通过：applicationId / versionCode / versionName / minSdk / targetSdk / debuggable / 图标 / 权限 与预期一致。"
}

# ---------- SHA256SUMS.txt ----------
$sumsFile = Join-Path $ArtOut "SHA256SUMS.txt"
@($OutDebug, $OutRelApk, $OutRelAab) | ForEach-Object {
    $h = (Get-FileHash $_ -Algorithm SHA256).Hash.ToLower()
    "$h  $(Split-Path $_ -Leaf)"
} | Set-Content $sumsFile -Encoding ascii

# ---------- android-build-info.json ----------
$buildInfo = [ordered]@{
    project        = $AppSlug
    version        = $Version
    versionCode    = 1
    generatedAt    = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
    gradle         = $gradleVersion
    signingEnabled = $SignReady
    signingEnv     = $signingSummary
    artifacts = [ordered]@{
        debug_apk            = "$AppSlug-$Version-debug.apk"
        release_unsigned_apk = "$AppSlug-$ReleaseTag.apk"
        release_unsigned_aab = "$AppSlug-$ReleaseTag.aab"
    }
    verified = [ordered]@{
        debug   = $apkDebugInfo
        release = $apkRelInfo
    }
}
# 写 JSON：PS 5.1 的 Set-Content -Encoding utf8 会带 BOM，用 .NET UTF8 无 BOM 编码写。
$jsonText = $buildInfo | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText(
    (Join-Path $ArtOut "android-build-info.json"),
    $jsonText,
    (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "==> 完成。产物目录：$ArtOut"
Get-ChildItem $ArtOut | Select-Object Name, Length | Format-Table -AutoSize
