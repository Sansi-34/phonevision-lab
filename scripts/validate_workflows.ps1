# PhoneVision Lab - workflow static validation
#
# Local static checks only. GitHub-hosted CI is NOT executed here (no remote yet;
# real Actions runs happen after the first P0-5C push).
param(
    [switch]$RequireActionlint
)
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Workflows = Join-Path $RepoRoot ".github\workflows"

Write-Host "== Workflow static validation =="
Write-Host "  repo   : $RepoRoot"

# 1. YAML files exist
$Missing = @()
foreach ($n in "ci.yml", "windows-package.yml", "android-candidate.yml") {
    if (-not (Test-Path (Join-Path $Workflows $n))) { $Missing += $n }
}
if ($Missing.Count -gt 0) {
    Write-Host ("MISSING: " + ($Missing -join ", ")) -ForegroundColor Red
    exit 1
}
Write-Host "  workflows: present (ci / windows-package / android-candidate)" -ForegroundColor Green

# 2. Python static tests (SHA audit / permissions / paths / PR events)
Write-Host "  running pc-client/tests/test_ci_workflows.py ..."
$env:QT_QPA_PLATFORM = "offscreen"
Push-Location (Join-Path $RepoRoot "pc-client")
try {
    python -m unittest tests.test_ci_workflows
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ci_workflows tests FAILED" -ForegroundColor Red
        exit 1
    }
    Write-Host "  ci_workflows tests PASS" -ForegroundColor Green
} finally {
    Pop-Location
}

# 3. actionlint (if available)
$Actionlint = Get-Command actionlint -ErrorAction SilentlyContinue
if ($Actionlint) {
    $Results = & $Actionlint.Path (Join-Path $Workflows "*.yml") 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  actionlint: PASS" -ForegroundColor Green
    } else {
        Write-Host "  actionlint: FAIL" -ForegroundColor Red
        $Results | ForEach-Object { Write-Host "    $_" }
        exit 1
    }
} elseif ($RequireActionlint) {
    Write-Host "  actionlint: not installed (required by -RequireActionlint)" -ForegroundColor Red
    exit 1
} else {
    Write-Host "  actionlint: not installed, skipped" -ForegroundColor Yellow
}

Write-Host "== Static validation done. GitHub-hosted CI not executed (no remote). =="
