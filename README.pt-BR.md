# lonerchestrator

[English](README.md)

Orquestrador local de agentes de IA. Você escreve **cards** de demanda; agentes planejam, implementam, revisam e corrigem sozinhos, e só param quando o card é aprovado ou precisa de você.

Roda 100% na sua máquina, usando as assinaturas que você já tem logadas (**Claude Code** e, opcionalmente, **Antigravity/Gemini**). Sem chaves de API, sem GitHub Actions, sem servidor.

```
 card ─▶ SPLIT ─▶ PLAN ─▶ BUILD ─▶ CHECKS ─▶ REVIEW ─▶ MERGE
          │         │        │         │         │         │
      splitter   planner  builder  regras+CI   qa + cross   git + retro
```

| Etapa | Quem | O que faz |
|---|---|---|
| SPLIT | `splitter` | Mantém o card inteiro ou quebra um card grande em cards pequenos (3+ entregas independentes) |
| PLAN | `planner` | Escreve o plano e a lista de tarefas; se o card for vago, **para e pergunta** (nunca chuta) |
| BUILD | `builder` | Implementa as tarefas e escreve os testes |
| CHECKS | código | Guardrails (arquivos protegidos, tamanho, segredos, testes apagados) + `scripts/ci.sh` |
| REVIEW | `qa` + `cross` | Dois revisores independentes, **em modelos diferentes**, em paralelo. Os dois precisam aprovar |
| MERGE | git + `retro` | Commit, merge na branch base, `retro` registra as lições |

Regras de ouro: **quem faz nunca avalia** (os revisores só veem o card, o diff e a saída dos testes, nunca o raciocínio de quem implementou), **3 tentativas** por card e depois ele vai para `NEEDS YOU`, e **nunca faz deploy**.

## Requisitos

- Python 3.10+ (só biblioteca padrão) e git
- [Claude Code](https://claude.com/claude-code) logado (`claude`), **obrigatório**: planner, builder, retro e o revisor `qa` rodam nele
- [Antigravity CLI](https://antigravity.google) logado (`agy`), **opcional**: dá ao revisor `cross` um modelo Gemini (uma família de modelo diferente pega erros diferentes). Sem ele, o `cross` usa um segundo modelo Claude
- bash, para rodar o `scripts/ci.sh` do projeto (Git Bash no Windows)

Você precisa da sua própria assinatura/login do Claude Code; o uso conta nos limites dela (o orquestrador espera e tenta de novo quando bate o limite).

| Plataforma | Painel (`tui`) | Janela nova (`live`) |
|---|---|---|
| Windows 10/11 | ✅ uso diário | ✅ Windows Terminal (`wt`) |
| macOS | ✅ implementado, testado no CI | ⚠️ Terminal.app via `osascript`, melhor esforço |
| Linux | ✅ implementado, testado no CI | ⚠️ gnome-terminal, xfce4-terminal, kitty, alacritty, konsole, xterm (precisa de sessão gráfica) |

`lonerchestrator tui` funciona em qualquer terminal com pelo menos **120×34**.

> O `gemini` CLI antigo não funciona mais em contas individuais; o `agy` é o substituto.
> **Leia o [SECURITY.md](SECURITY.md) antes de usar:** os agentes editam arquivos e rodam comandos na sua máquina.

## Instalação

```bash
git clone <url-do-repositorio> lonerchestrator && cd lonerchestrator
```

**Windows (PowerShell):**

```bash
.\install.ps1            # confere requisitos, instala o pacote, garante o comando no PATH
.\install.ps1 -DryRun    # só mostra o que faria
```

**macOS / Linux:**

```bash
./install.sh             # usa pipx se existir, senão pip --user
./install.sh --dry-run
```

O que os scripts fazem: conferem Python/git (e avisam o que falta de claude/agy), rodam a instalação **editável** (um `git pull` já atualiza o comando) e, no Windows, adicionam a pasta de scripts do Python ao PATH do **usuário** se ela não estiver lá. Não mexem em mais nada do sistema.

Manualmente: `pipx install -e .` ou `python -m pip install -e .`

Abra um terminal **novo** e teste:

```bash
lonerchestrator --help
```

Desinstalar: `.\install.ps1 -Uninstall` ou `./install.sh --uninstall` (seus projetos, cards e memória não são tocados).

## Começando em um projeto

```bash
cd D:\Github\meu_projeto
claude                       # uma vez: aceite o diálogo de confiança da pasta
lonerchestrator init         # instala board, agentes, guardrails, context/ e faz a introdução
```

1. **Introdução** (`init` ou `lonerchestrator intro`): detecta em quais IAs você está logado, deixa escolher o modelo de cada papel, os dois revisores e qual agente cuida de cada área.
2. Preencha `context/project.md` (stack, como rodar testes, convenções) e ajuste `scripts/ci.sh` para o seu projeto.
3. Crie um card: `lonerchestrator new "Adicionar login"`, abra o arquivo em `board/backlog/` e preencha objetivo e critérios **testáveis**.
4. Abra o painel: `lonerchestrator`, e aperte `r`.

## O painel

`lonerchestrator` (sem argumentos) abre uma janela do Windows Terminal já em **120×34**, com cinco abas:

| Aba | Mostra |
|---|---|
| **1 Board** | Colunas TO DO / DOING / DONE / NEEDS YOU com os cards |
| **2 Flow** | O pipeline estilo n8n: nós, sub-nós (modelo, memória, agente, regras) e os últimos eventos |
| **3 Planner** | Card selecionado: objetivo, critérios, plano, tarefas (`[ ]`/`[x]`), perguntas pra você e histórico |
| **4 Agents** | O que cada agente está fazendo agora, em seis painéis alinhados |
| **5 AIs** | Checklist das IAs/modelos que você permite, quem faz o quê e o seu **uso em tempo real** (veja abaixo) |

Teclas: `←→↑↓` mover/selecionar · `1`-`5` ou `Tab` trocar de aba · `a` responder um card bloqueado · `PgUp`/`PgDn` rolar · `r` rodar o pipeline · `x` parar · `q` sair.

Dentro de um terminal já aberto: `lonerchestrator tui` (precisa de pelo menos 120×34).

### A aba AIs: escolha suas IAs e acompanhe o uso

- **AIs to use**: todos os modelos das IAs em que você está logado, como checklist (`↑↓` move, `espaço` marca/desmarca). Desmarcar um modelo que um papel usa move o papel para outro modelo marcado; o último modelo Claude não pode ser desmarcado. As mudanças são salvas na hora em `.orchestrator/config.json`.
- **Who does what**: `splitter`, `planner`, `builder`, `retro` (modelos Claude) e os dois revisores `qa`/`cross` (qualquer IA marcada). `←/→` ou `espaço` troca o modelo. Avisa quando os dois revisores usam o mesmo modelo.
- **Uso ao vivo**, só com números que as próprias CLIs informam:
  - **Claude Code**: os limites da sua conta, **sessão de 5 horas** e **semanal**, em barras com o horário de reset (os mesmos números do `/usage`), mais tokens por modelo nesta execução e em todas. Atualizam a cada chamada de agente; `u` atualiza na hora (uma chamada mínima com haiku).
  - **Antigravity (`agy`)**: só tokens por modelo. O `agy` não expõe a cota restante, e o painel diz isso em vez de inventar um número.
  - O cabeçalho mostra sempre a versão compacta, ex.: `claude ● 5h 52% wk 19%   agy ● 18.0k tok`.
- `d` detecta de novo em quais IAs você está logado.

## Comandos

| Comando | Faz |
|---|---|
| `lonerchestrator` | Abre o painel do projeto da pasta atual (= `live`) |
| `init [--force]` | Prepara o projeto (não sobrescreve arquivos existentes sem `--force`) |
| `intro [--yes]` | Detecta IAs logadas e atribui modelos/agentes (`--yes` aceita os padrões) |
| `new "título" [--area frontend\|backend\|both]` | Cria um card numerado em `board/backlog/` |
| `answer [card]` | Responde as perguntas de um card bloqueado no terminal e o devolve ao backlog |
| `run [--card id] [--base branch] [--dry-run]` | Processa o backlog sem interface |
| `live` / `tui` | Painel em janela nova (tamanho fixo) / no terminal atual |
| `tail <papel>` | Segue a saída de um agente (`planner`, `builder`, `qa`, `cross`, `retro`, `pipeline`) |
| `status` | Contagem do board e últimos eventos |
| `-C <pasta>` | (antes de qualquer comando) aponta outro projeto |

## Quando o card precisa de você

Cards vagos ("deixa mais rápido", "relatório bonito") **não são implementados**. O agente para e deixa perguntas numeradas, e o card vai para **Needs you**. Cards que estouram as 3 tentativas também vão para lá, com o trabalho parcial guardado na branch `card/<id>`.

**Responda dentro do painel:** abra o card na aba **Planner** (ou selecione-o na Board) e aperte `a`. As perguntas aparecem uma por vez; digite a resposta e aperte `Enter` para a próxima (`Esc` cancela, resposta vazia pula a pergunta). Depois da última, as respostas são gravadas no card em `## Answers`, as perguntas são limpas e o card volta para o backlog. Aperte `r` para rodar de novo; o planner lê suas respostas e não pergunta a mesma coisa duas vezes.

**Sem o painel:** `lonerchestrator answer 002` faz as mesmas perguntas no terminal e faz o mesmo.

**À mão** ainda funciona: escreva as respostas na seção `## Answers` do card e mova o arquivo de `board/blocked/` de volta para `board/backlog/`.

## Guardrails e segurança

Verificados por **código**, não por prompt, antes dos testes:

- arquivos protegidos intocáveis (`scripts/**`, `.claude/**`, `CLAUDE.md`, `GEMINI.md`, `.orchestrator/**`)
- limite de arquivos e linhas por card (padrão 25 arquivos / 1000 linhas): card grande demais deve ser quebrado
- testes apagados e segredos no diff (chaves, tokens, senhas) são rejeitados
- uma branch por card (`card/<id>`); nada é mergeado sem os dois revisores aprovarem e o CI passar
- agentes não fazem commit, merge, push nem trocam de branch: o orquestrador é dono do git
- rate limit/cota: espera com backoff e retoma; login expirado aborta sem perder o card
- `.claude/settings.json` do projeto libera só o necessário e nega `rm -rf`, `git push`, `git reset --hard` etc.

## Configuração

`.orchestrator/config.json` do projeto (só o que você quiser mudar; o resto vem do padrão):

```json
{
  "base": "main",
  "ci": "bash scripts/ci.sh",
  "max_attempts": 3,
  "split": true,
  "verbose": false,
  "roles": { "planner": { "cli": "claude", "model": "sonnet" } },
  "reviewers": [
    { "name": "qa",    "kind": "claude", "agent": "qa", "model": "sonnet" },
    { "name": "cross", "kind": "agy",    "model": "gemini-4-argon-high" }
  ],
  "guardrails": { "max_files": 25, "max_diff_lines": 1000 }
}
```

`base` é a branch que recebe os cards aprovados. Use outra (ex.: `agents-setup`) para a `main` ficar intocada até você decidir.

## O que cada projeto ganha

```
meu_projeto/
├── CLAUDE.md  GEMINI.md          regras do orquestrador e do revisor
├── board/{backlog,doing,review,done,blocked}/   cards (.md); fica local, no .gitignore
├── context/{project,decisions,history}.md       contexto lido pelos agentes
├── memory/{backend,frontend,qa}.md              lições aprendidas por área (a retro cuida)
├── .claude/{agents,skills,settings.json}        agentes e permissões
├── scripts/ci.sh                                lint + testes + build do projeto
└── .orchestrator/                               config, logs por execução, streams
```

Logs: `board/_log.md` (tabela legível), `.orchestrator/runs/<execução>/events.jsonl` (estruturado) e, por card, o texto completo de cada agente.

## Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| `Failed to authenticate` / OAuth expirado | Rode `claude` (ou `agy`) uma vez e faça login |
| Permissões do `settings.json` ignoradas | Pasta não confiável: rode `claude` dentro dela e aceite o diálogo (confiar na pasta-pai não vale) |
| "working tree not clean" | Faça commit ou stash antes de rodar; o orquestrador exige árvore limpa |
| "Window too small" | O painel precisa de 120×34; use `lonerchestrator live` ou aumente a janela |
| `gemini` pede para migrar | Use o `agy` (já é o padrão do revisor `cross`) |
| Pipeline não inicia pelo painel | Veja `.orchestrator/run.out` |

## Desenvolvimento

```bash
cd D:\Github\orchestrator
python -m venv .venv
.venv\Scripts\python -m pip install -e . pytest ruff
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m pytest -q        # 33 testes: pipeline com agentes falsos + git real, guardrails, TUI
```

Só biblioteca padrão, sem dependências. Módulos em `orch/`: `pipeline` (o laço), `agents` (execução dos CLIs, backoff), `guardrails`, `board` (cards), `gitops`, `events` (logs), `tui`/`view` (painel), `intro`, `config`, `cli`. Os templates copiados pelo `init` ficam em `orch/templates/` (`dot-claude/` vira `.claude/`).
