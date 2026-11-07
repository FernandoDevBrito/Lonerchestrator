<#
  Install lonerchestrator on Windows (PowerShell 5.1+).

    .\install.ps1              install (editable: git pull updates the command)
    .\install.ps1 -DryRun      show what it would do, change nothing
    .\install.ps1 -Uninstall   remove the package

  Touches nothing outside Python (no registry, no Windows settings), except adding Python's
  Scripts folder to the USER PATH if it is not there yet.
#>
param([switch]$DryRun, [switch]$Uninstall)
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Run($label, [scriptblock]$cmd) {
    if ($DryRun) { Write-Host "  [dry-run] $label" } else { & $cmd }
}

Step "Requirements"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python not found. Install Python 3.10+ (python.org) and run again." }
if ((& python -c "import sys; print(int(sys.version_info >= (3, 10)))") -ne "1") { throw "Python 3.10 or newer is required." }
Write-Host "  python  $(& python --version)"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git not found (https://git-scm.com)." }
Write-Host "  git     ok"
foreach ($t in @(@("claude", "Claude Code (planner, builder, qa): https://claude.com/claude-code"),
                 @("agy", "Antigravity CLI, optional (Gemini reviewer): https://antigravity.google"),
                 @("wt", "Windows Terminal, for 'lonerchestrator live': Microsoft Store"))) {
    if (Get-Command $t[0] -ErrorAction SilentlyContinue) { Write-Host "  $($t[0].PadRight(7)) ok" } else { Warn "$($t[0]) not found. $($t[1])" }
}

if ($Uninstall) {
    Step "Removing"
    Run "python -m pip uninstall -y lonerchestrator" { & python -m pip uninstall -y lonerchestrator }
    Write-Host "Done. (Your projects, boards and memory were not touched.)"
    return
}

Step "Installing the package (editable) from $repo"
Run "python -m pip install --upgrade -e `"$repo`"" { & python -m pip install --upgrade --quiet -e $repo; if ($LASTEXITCODE) { throw "pip failed" } }

Step "Checking the command"
$scripts = (& python -c "import sysconfig; print(sysconfig.get_path('scripts'))").Trim()
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$norm = { param($p) $p.TrimEnd('\').ToLowerInvariant() }
$known = @(($env:Path + ";" + $userPath) -split ";" | Where-Object { $_ } | ForEach-Object { & $norm $_ })
$onPath = $known -contains (& $norm $scripts)
if (-not $onPath) {
    Warn "$scripts is not on PATH. Adding it to the user PATH."
    Run "add $scripts to the user PATH" {
        [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $scripts), "User")
        $env:Path += ";$scripts"
        Write-Host "  Open a new terminal for the PATH change to apply."
    }
}
if (-not $DryRun) {
    if (Test-Path (Join-Path $scripts "lonerchestrator.exe")) { Write-Host "  lonerchestrator.exe in $scripts" } else { throw "The command was not created in $scripts" }
}

Write-Host ""
Write-Host "Done. In a NEW terminal:" -ForegroundColor Green
Write-Host "  cd your-project"
Write-Host "  lonerchestrator init     # set up board, agents, guardrails + introduction"
Write-Host "  lonerchestrator          # open the panel"
