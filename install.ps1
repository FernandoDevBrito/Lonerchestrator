# lonerchestrator installer for Windows (PowerShell 5.1+)
#
#   irm https://raw.githubusercontent.com/FernandoDevBrito/lonerchestrator/main/install.ps1 | iex
#
# Options. As arguments when you run the file:
#   .\install.ps1 [-DryRun] [-Uninstall] [-Dev] [-Ref v0.1.0] [-Manager uv|pipx|pip] [-NoPath] [-Source <path-or-url>]
# Or as environment variables when piped (LONERCHESTRATOR_DRYRUN=1, _REF, _MANAGER, _NO_PATH=1, _SOURCE).
#
# It uses uv if you have it (uv can even fetch Python for you), else pipx, else pip --user.
# It never installs other programs, never needs admin rights, and -DryRun shows every command without running it.

$ErrorActionPreference = "Stop"
$Repo = "https://github.com/FernandoDevBrito/lonerchestrator"
$Package = "git+$Repo"          # becomes "lonerchestrator" once the first release is on PyPI

$o = @{ DryRun = ($env:LONERCHESTRATOR_DRYRUN -eq "1"); Uninstall = $false; Dev = $false; NoPath = ($env:LONERCHESTRATOR_NO_PATH -eq "1")
        Ref = $env:LONERCHESTRATOR_REF; Source = $env:LONERCHESTRATOR_SOURCE; Manager = $env:LONERCHESTRATOR_MANAGER }
for ($i = 0; $i -lt $args.Count; $i++) {
    switch ($args[$i]) {
        "-DryRun"    { $o.DryRun = $true }
        "-Uninstall" { $o.Uninstall = $true }
        "-Dev"       { $o.Dev = $true }
        "-NoPath"    { $o.NoPath = $true }
        "-Ref"       { $i++; $o.Ref = $args[$i] }
        "-Source"    { $i++; $o.Source = $args[$i] }
        "-Manager"   { $i++; $o.Manager = $args[$i] }
        default      { throw "unknown option: $($args[$i])" }
    }
}

function Tag($label, $color) { Write-Host ("  [{0}] " -f $label) -NoNewline -ForegroundColor $color }
function Ok($t)   { Tag " ok " Green;  Write-Host $t }
function Warn($t) { Tag " !! " Yellow; Write-Host $t }
function Bad($t)  { Tag " xx " Red;    Write-Host $t }
function Info($t) { Write-Host "         $t" -ForegroundColor DarkGray }
function Has($n)  { [bool](Get-Command $n -ErrorAction SilentlyContinue) }
function Run($shown, [scriptblock]$cmd) {
    if ($o.DryRun) { Write-Host "  [dry ] $shown" -ForegroundColor Cyan; return }
    $global:LASTEXITCODE = 0
    & $cmd
    if ($LASTEXITCODE) { throw "'$shown' failed (exit code $LASTEXITCODE)" }
}

Write-Host ""
Write-Host "  lonerchestrator" -NoNewline -ForegroundColor Cyan
Write-Host "  installer" -NoNewline -ForegroundColor DarkGray
if ($o.DryRun) { Write-Host "   (dry run: nothing will change)" -NoNewline -ForegroundColor Yellow }
Write-Host "`n"

# ---- which tool installs it
if ($o.Manager) {
    $mgr = $o.Manager
    if ($mgr -notin @("uv", "pipx", "pip")) { throw "-Manager must be uv, pipx or pip" }
    if ($mgr -ne "pip" -and -not (Has $mgr)) { throw "$mgr was asked for but is not installed" }
} elseif (Has uv) { $mgr = "uv" } elseif (Has pipx) { $mgr = "pipx" } else { $mgr = "pip" }

# ---- remove
if ($o.Uninstall) {
    $found = $false
    if ($mgr -eq "uv" -and ((uv tool list 2>$null) -match "^lonerchestrator\b")) { Run "uv tool uninstall lonerchestrator" { uv tool uninstall lonerchestrator }; $found = $true }
    elseif ($mgr -eq "pipx" -and ((pipx list --short 2>$null) -match "^lonerchestrator\b")) { Run "pipx uninstall lonerchestrator" { pipx uninstall lonerchestrator }; $found = $true }
    elseif ($mgr -eq "pip" -and (Has python) -and ((python -m pip show lonerchestrator 2>$null) -match "^Name:")) { Run "python -m pip uninstall -y lonerchestrator" { python -m pip uninstall -y lonerchestrator }; $found = $true }
    if ($found) { Ok "lonerchestrator removed"; Info "Your projects, boards and memory were not touched." } else { Warn "lonerchestrator is not installed with $mgr" }
    Write-Host ""
    return
}

# ---- what to install
$here = if ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { $null }
if ($o.Source) { $spec = $o.Source }
elseif ($o.Dev) {
    if (-not $here -or -not (Test-Path (Join-Path $here "pyproject.toml"))) { throw "-Dev needs a clone: run .\install.ps1 -Dev from inside the repository folder" }
    $spec = $here
} else { $spec = $Package + $(if ($o.Ref) { "@" + $o.Ref } else { "" }) }

# ---- requirements for the install itself (Claude Code etc. are checked by `lonerchestrator doctor` at the end)
if ($spec -like "git+*") {
    if (-not (Has git)) { Bad "git is needed to download it"; Info "install it from https://git-scm.com and run this again"; throw "git not found" }
    Ok "git found"
}
switch ($mgr) {
    "uv"   { Ok ("uv found: " + (((uv --version) -split " ")[0..1] -join " ") + "  (fetches Python by itself if needed)") }
    "pipx" { Ok "pipx found" }
    "pip"  {
        if (-not (Has python)) { Bad "Python 3.10+ is needed (or install uv: https://docs.astral.sh/uv/)"; throw "python not found" }
        if ((python -c "import sys; print(int(sys.version_info >= (3, 10)))") -ne "1") { Bad "Python 3.10 or newer is needed"; throw "python too old" }
        Ok ("python found: " + (python --version))
        Info "tip: uv (https://docs.astral.sh/uv/) installs tools like this one more cleanly"
    }
}
Info "source: $spec"

# ---- install
Write-Host ""
switch ($mgr) {
    "uv"   { if ($o.Dev) { Run "uv tool install --force --editable `"$spec`"" { uv tool install --force --editable $spec } } else { Run "uv tool install --force `"$spec`"" { uv tool install --force $spec } } }
    "pipx" { if ($o.Dev) { Run "pipx install --force --editable `"$spec`"" { pipx install --force --editable $spec } } else { Run "pipx install --force `"$spec`"" { pipx install --force $spec } } }
    "pip"  { if ($o.Dev) { Run "python -m pip install --user --upgrade --editable `"$spec`"" { python -m pip install --user --upgrade --quiet --editable $spec } } else { Run "python -m pip install --user --upgrade `"$spec`"" { python -m pip install --user --upgrade --quiet $spec } } }
}

# ---- make sure the command is on PATH
switch ($mgr) {
    "uv"   { $bin = ((uv tool dir --bin) -join "").Trim() }
    "pipx" { $bin = ((pipx environment --value PIPX_BIN_DIR 2>$null) -join "").Trim(); if (-not $bin) { $bin = Join-Path $HOME ".local\bin" } }
    "pip"  { $bin = ((python -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user'))") -join "").Trim() }
}
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$norm = { param($p) $p.TrimEnd('\').ToLowerInvariant() }
$known = @(($env:Path + ";" + $userPath) -split ";" | Where-Object { $_ } | ForEach-Object { & $norm $_ })
if ($known -contains (& $norm $bin)) { Ok "$bin is on PATH" }
elseif ($o.NoPath) { Warn "$bin is not on PATH (left alone: -NoPath)" }
else {
    Warn "$bin is not on PATH yet: adding it to your user PATH"
    switch ($mgr) {
        "uv"   { Run "uv tool update-shell" { uv tool update-shell } }
        "pipx" { Run "pipx ensurepath" { pipx ensurepath } }
        "pip"  { Run "add $bin to the user PATH" { [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $bin), "User") } }
    }
    Info "open a new terminal for that to apply"
}
if (-not $o.DryRun) { $env:Path = "$bin;$env:Path" }

# ---- prove it works
Write-Host ""
if ($o.DryRun) { Ok "dry run finished: nothing was changed" }
else {
    $exe = Join-Path $bin "lonerchestrator.exe"
    if (-not (Test-Path $exe)) { Bad "the command was not created in $bin"; throw "install failed" }
    Ok ((& $exe --version) -join " ")
    & $exe doctor
    if ($LASTEXITCODE) { Warn "doctor found something to fix (see above): the install itself is fine" }
}

Write-Host ""
Write-Host "  Next steps" -ForegroundColor Cyan
Write-Host "    cd your-project            a git repository"
Write-Host "    lonerchestrator init       sets up the board and asks which AIs to use"
Write-Host "    lonerchestrator            opens the panel (tab 6 'Settings' shows what is still missing)"
Write-Host ""
