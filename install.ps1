<#
  Instala o lonerchestrator nesta maquina (Windows, PowerShell 5.1+).

    .\install.ps1              instala (modo editavel: git pull ja atualiza o comando)
    .\install.ps1 -DryRun      mostra o que faria, sem mudar nada
    .\install.ps1 -Uninstall   remove o pacote

  Nao toca em nada fora do Python (nem registro, nem configuracao do Windows), exceto
  adicionar a pasta de scripts do Python ao PATH do USUARIO se ela ainda nao estiver la.
#>
param([switch]$DryRun, [switch]$Uninstall)
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Run($label, [scriptblock]$cmd) {
    if ($DryRun) { Write-Host "  [dry-run] $label" } else { & $cmd }
}

Step "Requisitos"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { throw "Python nao encontrado. Instale o Python 3.10+ (python.org) e rode de novo." }
if ((& python -c "import sys; print(int(sys.version_info >= (3, 10)))") -ne "1") { throw "Precisa de Python 3.10 ou mais novo." }
Write-Host "  python  $(& python --version)"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git nao encontrado (https://git-scm.com)." }
Write-Host "  git     ok"
foreach ($t in @(@("claude", "Claude Code (planner, builder, qa): https://claude.com/claude-code"),
                 @("agy", "Antigravity CLI (revisor cross, modelos Gemini): https://antigravity.google"),
                 @("wt", "Windows Terminal (janela do `lonerchestrator live`): Microsoft Store"))) {
    if (Get-Command $t[0] -ErrorAction SilentlyContinue) { Write-Host "  $($t[0].PadRight(7)) ok" } else { Warn "$($t[0]) nao encontrado. $($t[1])" }
}

if ($Uninstall) {
    Step "Removendo"
    Run "python -m pip uninstall -y lonerchestrator" { & python -m pip uninstall -y lonerchestrator }
    Write-Host "Pronto. (Seus projetos, boards e memoria nao foram tocados.)"
    return
}

Step "Instalando o pacote (editavel) a partir de $repo"
Run "python -m pip install --upgrade -e `"$repo`"" { & python -m pip install --upgrade --quiet -e $repo; if ($LASTEXITCODE) { throw "pip falhou" } }

Step "Conferindo o comando"
$scripts = (& python -c "import sysconfig; print(sysconfig.get_path('scripts'))").Trim()
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$norm = { param($p) $p.TrimEnd('\').ToLowerInvariant() }
$known = @(($env:Path + ";" + $userPath) -split ";" | Where-Object { $_ } | ForEach-Object { & $norm $_ })
$onPath = $known -contains (& $norm $scripts)
if (-not $onPath) {
    Warn "$scripts nao esta no PATH. Adicionando ao PATH do usuario."
    Run "adicionar $scripts ao PATH do usuario" {
        [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $scripts), "User")
        $env:Path += ";$scripts"
        Write-Host "  Abra um terminal novo para o PATH valer."
    }
}
if (-not $DryRun) {
    if (Test-Path (Join-Path $scripts "lonerchestrator.exe")) { Write-Host "  lonerchestrator.exe em $scripts" } else { throw "O comando nao foi criado em $scripts" }
}

Write-Host ""
Write-Host "Pronto. Em um terminal NOVO:" -ForegroundColor Green
Write-Host "  cd D:\Github\seu_projeto"
Write-Host "  lonerchestrator init     # prepara o projeto (board, agentes, guardrails) + introducao"
Write-Host "  lonerchestrator          # abre o painel"
