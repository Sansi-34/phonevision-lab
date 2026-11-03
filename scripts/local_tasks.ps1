[CmdletBinding()]
param(
    [ValidateSet('Run', 'TrainRun', 'Portable', 'Shell', 'Check', 'Test', 'BuildAndroid', 'BuildWindows')]
    [string]$Task = 'Run',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AppArgs
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $OutputEncoding
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PcRoot = Join-Path $ProjectRoot 'pc-client'
$LocalConfig = Join-Path $ProjectRoot '.local\environment.ps1'
if (-not (Test-Path -LiteralPath $LocalConfig)) {
    throw "Local configuration missing: $LocalConfig. See docs/local-setup.zh-CN.md."
}
. $LocalConfig
if ($Task -eq 'TrainRun') {
    $env:PVL_PYTHON = Join-Path $PcRoot '.venv-train\Scripts\python.exe'
}
$env:VIRTUAL_ENV = Split-Path -Parent (Split-Path -Parent $env:PVL_PYTHON)
foreach ($RequiredPath in @($env:PVL_PYTHON, (Join-Path $env:JAVA_HOME 'bin\java.exe'), (Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe'))) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) { throw "Required tool missing: $RequiredPath" }
}
$env:Path = (Join-Path $env:JAVA_HOME 'bin') + ';' + (Join-Path $env:ANDROID_HOME 'platform-tools') + ';' + (Split-Path -Parent $env:PVL_PYTHON) + ';' + $env:Path

function Assert-Exit([string]$Action) {
    if ($LASTEXITCODE -ne 0) { throw "$Action failed (exit $LASTEXITCODE)." }
}

switch ($Task) {
    'Shell' {
        Set-Location -LiteralPath $ProjectRoot
        Write-Host "Project: $ProjectRoot"
        Write-Host "Python:  $env:PVL_PYTHON"
        Write-Host "JDK:     $env:JAVA_HOME"
        Write-Host "SDK:     $env:ANDROID_HOME"
        Write-Host 'Development shell ready. Run .\scripts\local_tasks.ps1 -Task Check/Test/BuildAndroid/BuildWindows.'
    }
    { $_ -in 'Run', 'TrainRun' } {
        Push-Location -LiteralPath $PcRoot
        try {
            & $env:PVL_PYTHON (Join-Path $PcRoot 'main.py') @AppArgs
            Assert-Exit 'Source client'
        } finally { Pop-Location }
    }
    'Portable' {
        $PortableExe = Join-Path $PcRoot 'dist\PhoneVisionLab\PhoneVisionLab.exe'
        if (-not (Test-Path -LiteralPath $PortableExe)) { throw "Portable application missing: $PortableExe" }
        $PortableOptions = @{ FilePath = $PortableExe; WorkingDirectory = $PcRoot }
        if ($AppArgs) { $PortableOptions.ArgumentList = $AppArgs }
        Start-Process @PortableOptions | Out-Null
    }
    'Check' {
        Write-Host "Project: $ProjectRoot"
        & $env:PVL_PYTHON -c "import sys, importlib.metadata as m; import PySide6, cv2, numpy, requests, PIL, yaml; print('Python:', sys.executable); print('Packages:', {n:m.version(n) for n in ['PySide6', 'opencv-python', 'numpy', 'requests', 'pillow', 'PyYAML', 'pyinstaller']})"
        Assert-Exit 'Python imports'
        & $env:PVL_PYTHON -m pip check
        Assert-Exit 'Dependency check'
        & (Join-Path $env:JAVA_HOME 'bin\java.exe') -version
        Assert-Exit 'JDK check'
        & (Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe') version
        Assert-Exit 'ADB check'
        git -C $ProjectRoot diff --check
        Assert-Exit 'Git whitespace check'
        Write-Host 'Environment checks passed.' -ForegroundColor Green
    }
    'Test' {
        $PreviousQtPlatform = $env:QT_QPA_PLATFORM
        Push-Location -LiteralPath $PcRoot
        try {
            $env:QT_QPA_PLATFORM = 'offscreen'
            & $env:PVL_PYTHON -m unittest discover -s tests -t tests
            Assert-Exit 'Python tests'
        } finally {
            $env:QT_QPA_PLATFORM = $PreviousQtPlatform
            Pop-Location
        }
    }
    'BuildAndroid' {
        Push-Location -LiteralPath (Join-Path $ProjectRoot 'android')
        try {
            $GradleArgs = @('--no-daemon', '--console=plain', '-Dorg.gradle.internal.http.connectionTimeout=15000', '-Dorg.gradle.internal.http.socketTimeout=15000')
            if ($env:PVL_GRADLE_VERBOSE -eq '1') { $GradleArgs += '--info' }
            $LocalRepositories = Join-Path $ProjectRoot '.local\repositories.init.gradle'
            if (Test-Path -LiteralPath $LocalRepositories) {
                $GradleArgs += @('--init-script', $LocalRepositories)
            }
            # Java does not automatically use the HTTP(S)_PROXY environment.
            # Pass an unauthenticated HTTP proxy only to this Gradle invocation.
            $ProxyAddress = if ($env:HTTPS_PROXY) { $env:HTTPS_PROXY } else { $env:HTTP_PROXY }
            if ($ProxyAddress -and $env:PVL_GRADLE_USE_PROXY -ne '0') {
                $BuildProxy = [uri]$ProxyAddress
                if ($BuildProxy.Scheme -eq 'http' -and -not $BuildProxy.UserInfo) {
                    $GradleArgs += "-Dhttps.proxyHost=$($BuildProxy.Host)"
                    $GradleArgs += "-Dhttps.proxyPort=$($BuildProxy.Port)"
                    $GradleArgs += "-Dhttp.proxyHost=$($BuildProxy.Host)"
                    $GradleArgs += "-Dhttp.proxyPort=$($BuildProxy.Port)"
                }
            }
            & .\gradlew.bat @GradleArgs assembleDebug testDebugUnitTest
            Assert-Exit 'Android build and unit tests'
            Write-Host ('APK: ' + (Join-Path $ProjectRoot 'android\app\build\outputs\apk\debug\app-debug.apk'))
        } finally { Pop-Location }
    }
    'BuildWindows' {
        # The existing packaging script uses PowerShell 7 platform variables.
        # Define them for Windows PowerShell 5.1 as well.
        if ($PSVersionTable.PSVersion.Major -lt 6) {
            $IsMacOS = $false
            $IsLinux = $false
        }
        & (Join-Path $PcRoot 'scripts\build_windows.ps1') -NoInstall
        Assert-Exit 'Windows packaging'
    }
}
