# lonerchestrator

[English](README.md)

Orquestrador local de agentes de IA. Você escreve **cards** de demanda; agentes planejam, implementam, revisam e corrigem sozinhos, e só param quando o card é aprovado ou precisa de você.

Roda 100% na sua máquina, usando as assinaturas que você já tem logadas (**Claude Code** por padrão; Antigravity, Codex, Gemini CLI, Ollama ou qualquer CLI que você descrever também servem). Sem chaves de API, sem GitHub Actions, sem servidor.

<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/board-dark.png">
  <img alt="O kanban do lonerchestrator: Backlog, In progress, Needs you e Done" src="docs/images/board-light.png" width="100%">
</picture>
<br><sub>O board no navegador (<code>lonerchestrator web</code>): dois cards em andamento ao mesmo tempo, um esperando as suas respostas.</sub>
</p>

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
| CHECKS | código | Guardrails (arquivos protegidos, tamanho, segredos, testes apagados) + o seu script de CI |
| REVIEW | `qa` + `cross` | Dois revisores independentes, **em modelos diferentes**, em paralelo. Os dois precisam aprovar |
| MERGE | git + `retro` | Commit, merge na branch base, `retro` registra as lições |

Regras de ouro: **quem faz nunca avalia** (os revisores só veem o card, o diff e a saída dos testes, nunca o raciocínio de quem implementou), **3 tentativas** por card e depois ele vai para `NEEDS YOU`, e **nunca faz deploy**.

## Requisitos

A lista completa, com como conferir e instalar cada item, está em [`requirements/`](requirements/README.md). O `lonerchestrator doctor` confere tudo, e o `lonerchestrator ais` mostra quais CLIs de IA você tem e instala as que faltam (pergunta antes).

- Python 3.10+ (só biblioteca padrão) e git
- [Claude Code](https://claude.com/claude-code) logado (`claude`). A IA padrão e a mais testada; qualquer outra IA que edite arquivos pode substituí-lo (veja [Qualquer IA](#qualquer-ia))
- [Antigravity CLI](https://antigravity.google) logado (`agy`), **opcional**: dá ao revisor `cross` um modelo Gemini (uma família de modelo diferente pega erros diferentes). Sem ele, o `cross` usa um segundo modelo Claude
- bash, para rodar o script de CI do projeto, `ci.sh` (Git Bash no Windows)

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

Uma linha, sem precisar clonar. O instalador usa o [uv](https://docs.astral.sh/uv/) se você tiver (o uv até baixa o Python para você), senão o pipx, senão `pip --user`. Ele nunca pede admin e não instala nada além desta ferramenta.

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/FernandoDevBrito/lonerchestrator/main/install.ps1 | iex
```

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/FernandoDevBrito/lonerchestrator/main/install.sh | bash
```

Abra um **terminal novo** e confira tudo:

```bash
lonerchestrator doctor
```

O `doctor` lista o que está instalado (git, Claude Code, ...), o que falta e exatamente como resolver. Dentro de um projeto, também roda as checagens do "Ready to run?".

### Outras formas

**Instalar as CLIs de IA junto:** no fim o instalador mostra quais IAs você tem (Claude Code, Antigravity) e oferece instalar as que faltam, mostrando cada comando oficial antes. Use `-With claude,agy` (PowerShell) ou `--with claude,agy` (bash) para instalar sem perguntar, ou rode `lonerchestrator ais` quando quiser.

| Você quer | Faça |
|---|---|
| Usar uv ou pipx direto | `uv tool install git+https://github.com/FernandoDevBrito/lonerchestrator` ou `pipx install git+https://github.com/FernandoDevBrito/lonerchestrator` |
| Fixar uma versão | `$env:LONERCHESTRATOR_REF="v0.1.0"` antes da linha do PowerShell, ou `curl ... \| bash -s -- --ref v0.1.0` |
| Olhar antes de instalar | Salve o script e rode com `-DryRun` / `--dry-run`: mostra cada comando e não muda nada |
| Atualizar | Rode a mesma linha de novo, ou `uv tool upgrade lonerchestrator` / `pipx upgrade lonerchestrator` |
| Desinstalar | `install.ps1 -Uninstall` / `install.sh --uninstall` (seus projetos, cards e memória nunca são tocados) |
| Mexer no código | Clone e rode `.\install.ps1 -Dev` / `./install.sh --dev`: instalação editável, então `git pull` atualiza o comando |

> Passar um script direto para o shell é confiar nele. Os dois instaladores são curtos e estão neste repositório: leia antes, ou use `-DryRun`. Ainda não está publicado no PyPI.

## Começando em um projeto

```bash
cd D:\Github\meu_projeto
claude                       # uma vez: aceite o diálogo de confiança da pasta
lonerchestrator init         # prepara a pasta do projeto (cards, agentes, contexto, script de CI) e faz a introdução
```

O `init` não coloca nada no seu projeto: tudo vai para uma pasta própria fora dele (veja [Onde ficam os arquivos dele](#onde-ficam-os-arquivos-dele)).

1. **Introdução** (`init` ou `lonerchestrator intro`): detecta em quais IAs você está logado, deixa escolher o modelo de cada papel, os dois revisores e qual agente cuida de cada área.
2. O `context/project.md` (stack, como rodar testes, convenções) se preenche sozinho: quando está vazio, o primeiro `lonerchestrator run` faz a IA estudar o seu repositório e escrevê-lo (ou rode `lonerchestrator context` quando quiser). Leia e corrija o que estiver errado. Ajuste o script de CI `ci.sh` para o seu projeto (o `init` mostra onde os dois estão).
3. Abra o painel e aperte `n`: escreva em palavras simples o que quer mudar, aperte `Enter`, e o card é criado e o pipeline começa a trabalhar nele (um pedido vago vira perguntas para você, não chute). `Tab` nessa caixa escolhe o agente (backend, frontend, both). Prefere escrever o card você mesmo? `lonerchestrator new "Adicionar login"` mostra o caminho do card novo: edite com objetivo e critérios **testáveis**.
4. Abra o painel: `lonerchestrator`, e aperte `r`.

<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/new-request-dark.png">
  <img alt="A caixa New request" src="docs/images/new-request-light.png" width="100%">
</picture>
<br><sub>Diga o que quer em palavras simples. A IA monta o card, o pipeline começa, e um pedido vago vira perguntas em vez de chutes.</sub>
</p>

## O painel

<p align="center">
<img alt="O painel no terminal" src="docs/images/terminal.png" width="100%">
<br><sub>O mesmo board no painel do terminal (<code>lonerchestrator</code>), 120x34, controlado pelo teclado.</sub>
</p>

`lonerchestrator` (sem argumentos) abre uma janela do Windows Terminal já em **120×34**, com seis abas:

| Aba | Mostra |
|---|---|
| **1 Board** | Colunas TO DO / DOING / DONE / NEEDS YOU com os cards |
| **2 Flow** | O pipeline estilo n8n: nós, sub-nós (modelo, memória, agente, regras) e os últimos eventos |
| **3 Planner** | Card selecionado: objetivo, critérios, plano, tarefas (`[ ]`/`[x]`), perguntas pra você e histórico |
| **4 Agents** | O que cada agente está fazendo agora, em seis painéis alinhados |
| **5 AIs** | Checklist das IAs/modelos que você permite, quem faz o quê e o seu **uso em tempo real** (veja abaixo) |
| **6 Settings** | As opções do projeto e um **"Ready to run?"** que diz o que ainda falta e como resolver |

Teclas: `←→↑↓` mover/selecionar · `1`-`6` ou `Tab` trocar de aba · `a` responder um card bloqueado · `PgUp`/`PgDn` rolar · `r` rodar o pipeline · `x` parar · `q` sair.

Dentro de um terminal já aberto: `lonerchestrator tui` (precisa de pelo menos 120×34).

### A aba Settings: configure sem editar JSON

- **Settings** (esquerda): branch base, comando de CI, tentativas por card, quebrar cards grandes, limite de tempo, máximo de arquivos e de linhas por card, texto completo dos agentes e rodar seus próprios git hooks. `↑↓` move, `←/→` ou `espaço` muda o valor, `Enter` edita o comando de CI. Cada mudança é salva na hora na config do projeto, e a linha embaixo da lista explica a opção selecionada. O comando de CI que você digita aqui é aprovado automaticamente (foi você que escreveu).
- **Ready to run?** (direita): Git e a branch base, Claude Code instalado e logado, os dois revisores, o comando de CI (o script existe, está aprovado), `context/project.md` preenchido, o Claude Code confiando na pasta e cards no backlog. O que faltar mostra o conserto exato. Abra esta aba primeiro em um projeto novo.

### A aba AIs: escolha suas IAs e acompanhe o uso

- **AIs to use**: todos os modelos das IAs em que você está logado, como checklist (`↑↓` move, `espaço` marca/desmarca). Desmarcar um modelo que um papel usa move o papel para outro modelo marcado; o último modelo Claude não pode ser desmarcado. As mudanças são salvas na hora na config do projeto.
- **Who does what**: `splitter`, `planner`, `builder`, `retro` (modelos Claude) e os dois revisores `qa`/`cross` (qualquer IA marcada). `←/→` ou `espaço` troca o modelo. Avisa quando os dois revisores usam o mesmo modelo.
- **Uso ao vivo**, do mesmo jeito para toda IA:
  - **Claude Code**: os limites da sua conta, **sessão de 5 horas** e **semanal**, em barras com o horário de reset (os mesmos números do `/usage`), mais tokens por modelo. Atualizam a cada chamada de agente; `u` atualiza na hora (uma chamada mínima com haiku).
  - **Todas as outras IAs** (Antigravity, Codex, Gemini, Ollama, a sua): chamadas e tokens por modelo, nesta execução e em todas, e em janelas móveis (5 horas, dia e semana na página web). Os tokens são **exatos** quando a CLI os informa (o Antigravity informa; qualquer CLI pode ser ensinada com `usage` no provider) e **estimados** caso contrário (cerca de 4 caracteres por token), sempre marcados com `~`.
  - **Seus próprios limites**: a maioria das CLIs não publica a cota, então você define a sua. `"budgets": {"agy": {"tokens": 5000000, "per": "day"}, "codex": {"calls": 200, "cost": 20, "per": "5h"}}` (a chave é uma IA ou `ia/modelo`; unidades `tokens`, `calls`, `cost` em USD; períodos `5h`, `day`, `week`, `month`, móveis). Cada um aparece como uma barra com o momento em que a chamada mais antiga deixa de contar. A aba AIs da página web tem um formulário para isso.
  - **Custo**: dê um `price` ao provider (`{"in": 3.0, "out": 15.0}`, USD por milhão de tokens) e os tokens viram um custo estimado.
  - O cabeçalho mostra sempre a versão compacta, ex.: `claude ● 5h 52% wk 19%   agy ● 18.0k tok`.
- `d` detecta de novo em quais IAs você está logado. Uma IA que não está pronta mostra como resolver (instalar ou logar).

## Comandos

| Comando | Faz |
|---|---|
| `lonerchestrator` | Abre o painel do projeto da pasta atual (= `live`) |
| `init [--force]` | Prepara a pasta do projeto, nada no projeto (não sobrescreve os arquivos dela sem `--force`) |
| `intro [--yes]` | Detecta IAs logadas e atribui modelos/agentes (`--yes` aceita os padrões) |
| `new "título" [--area frontend\|backend\|both\|docs\|<sua>]` | Cria um card numerado no backlog e mostra o caminho dele |
| `answer [card]` | Responde as perguntas de um card bloqueado no terminal e o devolve ao backlog |
| `trust [--yes]` | Aprova o comando de CI do projeto (roda por um shell). Perguntado uma vez, na primeira abertura ou execução |
| `run [--card id] [--base branch] [--dry-run]` | Processa o backlog sem interface |
| `live` / `tui` | Painel em janela nova (tamanho fixo) / no terminal atual |
| `tail <papel>` | Segue a saída de um agente (`planner`, `builder`, `qa`, `cross`, `retro`, `pipeline`) |
| `status` | Contagem do board e últimos eventos |
| `graph <card> [--attempt N] [--compare A..B] [--focus NOME] [--format tree\|ascii\|json\|mermaid\|dot\|svg] [--out ARQUIVO] [--tui]` | O [grafo de mudanças](#grafo-de-mudanças) de um card: os símbolos que o diff mudou e quem os usa |
| `-C <pasta>` | (antes de qualquer comando) aponta outro projeto |

## Quando o card precisa de você

Cards vagos ("deixa mais rápido", "relatório bonito") **não são implementados**. O agente para e deixa perguntas numeradas, e o card vai para **Needs you**. Cards que estouram as 3 tentativas também vão para lá, com o trabalho parcial guardado na branch `card/<id>`.

<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/planner-dark.png">
  <img alt="A aba Planner com as perguntas de um card e três respostas sugeridas" src="docs/images/planner-light.png" width="100%">
</picture>
<br><sub>O planner pergunta em vez de chutar. Escolha uma das 3 respostas sugeridas ou escreva a sua, depois <em>Send answers &amp; run</em>.</sub>
</p>

**Responda dentro do painel:** abra o card na aba **Planner** (ou selecione-o na Board) e aperte `a`. As perguntas aparecem uma por vez, cada uma com **3 respostas sugeridas**: aperte `1`, `2` ou `3` para escolher uma (já vai direto para a próxima pergunta), ou digite a sua e aperte `Enter` (`Esc` cancela, resposta vazia pula a pergunta). Depois que você digitou algo, os números viram texto normal. Se as perguntas de um card vieram sem sugestões (um card antigo, ou um agente que esqueceu), o painel pede ao Claude em segundo plano quando você aperta `a`: uma chamada pequena com haiku, somente leitura, e você já pode ir digitando. Depois da última, as respostas são gravadas no card em `## Answers`, as perguntas são limpas e o card volta para o backlog. Aperte `r` para rodar de novo; o planner lê suas respostas e não pergunta a mesma coisa duas vezes.

**Sem o painel:** `lonerchestrator answer 002` faz as mesmas perguntas no terminal (digite 1-3 para escolher uma sugestão, ou escreva a sua) e faz o mesmo.

**À mão** ainda funciona: escreva as respostas na seção `## Answers` do card e mova o arquivo de `board/blocked/` de volta para `board/backlog/` (na pasta do projeto).

## Guardrails e segurança

Verificados por **código**, não por prompt, antes dos testes:

- arquivos protegidos intocáveis (`.claude/**`, `CLAUDE.md`, `GEMINI.md`: a configuração das suas ferramentas de IA). Os arquivos do orquestrador não ficam no projeto, e a config, as regras, os agentes e o script de CI dele ficam fora do alcance dos agentes
- limite de arquivos e linhas por card (padrão 25 arquivos / 1000 linhas): card grande demais deve ser quebrado
- testes apagados e segredos no diff (chaves, tokens, senhas) são rejeitados; um segredo é apontado como `caminho:linha`, nunca copiado para o card ou os logs
- uma branch por card (`card/<id>`); nada é mergeado sem os dois revisores aprovarem e o CI passar
- agentes não fazem commit, merge, push nem trocam de branch: o orquestrador é dono do git
- rate limit/cota: espera com backoff e retoma; login expirado aborta sem perder o card
- as permissões que o Claude Code recebe (`settings.json` na pasta do projeto) liberam só o necessário e negam `rm -rf`, `git push`, `git reset --hard` etc.

## Configuração

`config.json` na pasta do projeto (o `lonerchestrator doctor` mostra onde; só o que você quiser mudar, o resto vem do padrão):

```json
{
  "base": "main",
  "ci": "bash \"{folder}/ci.sh\"",
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

`base` é a branch que recebe os cards aprovados. Use outra (ex.: `agents-setup`) para a `main` ficar intocada até você decidir. O `ci` roda no projeto (ou numa worktree de card dele); `{folder}` vira a pasta do projeto.

### Esforço, áreas e o agente de docs

- **Esforço por papel.** Qualquer papel ou revisor pode dizer o quanto o modelo pensa: `"builder": {"cli": "claude", "model": "opus", "effort": "xhigh"}`, ou `"effort": "low"` no splitter para poupar cota. As palavras são `low`, `medium`, `high`, `xhigh`, `max` (sem valor = o padrão da CLI). O Claude Code recebe `--effort`; o Codex recebe `model_reasoning_effort` (acima de `high` vira `high`); uma CLI que não aceita esforço ignora. O seu provider recebe com `"effort_args": ["--effort", "{effort}"]` e, se quiser, `"efforts"` (as palavras que ele aceita). A aba IAs da página tem uma lista de esforço ao lado de cada papel.
- **As áreas são suas.** As chaves de `agents` são as áreas que um card pode ter, cada uma ligada a um arquivo de agente: `"agents": {"data": "data-eng"}` cria a área `data`, feita por `agents/data-eng.md` na pasta do projeto (`{folder}` e `{ci}` no texto dele são preenchidos). As outras IAs recebem o texto desse arquivo no prompt, então qualquer IA faz o papel de qualquer agente. O *Pronto para rodar?* avisa quando falta o arquivo do agente de uma área.
- **A área `docs`: documentador e pesquisador.** Cards de documentação (README, guias, docstrings, docs de API, changelog) ou com uma pergunta a responder ("qual biblioteca serve?") vão para o agente `docs`. Ele lê antes de escrever, sustenta cada afirmação sobre o projeto com `caminho:linha` ou a saída de um comando, roda todo exemplo que escreve, nunca muda o comportamento do produto e grava pesquisas em `docs/research/<card>.md`: resposta curta primeiro, evidências, opções com prós e contras, uma recomendação. Um pedido com palavras como *documentar*, *README*, *guia* ou *pesquisa* (e sem palavras de código) vai sozinho para `docs`.
- **Decisões deixam rastro.** Todo builder (backend, frontend, docs) registra uma escolha não óbvia como uma linha em `context/decisions.md` (data, decisão, porquê, card) e atualiza `context/project.md` quando a stack ou os comandos mudam, para o próximo agente não repetir a discussão.

## O kanban no navegador

```bash
lonerchestrator web
```

Tudo que o painel do terminal faz, no navegador, servido só para o seu computador (`127.0.0.1`, com um token aleatório no link que ele imprime). Oito abas (teclas `1`-`8`), que se atualizam sozinhas enquanto o pipeline roda:

<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/flow-dark.png">
  <img alt="A aba Flow: etapas e revisores de um card" src="docs/images/flow-light.png" width="100%">
</picture>
<br><sub>Flow: em que etapa o card está, e o que cada revisor independente disse.</sub>
</p>
<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/card-dark.png">
  <img alt="Os detalhes de um card no painel lateral" src="docs/images/card-light.png" width="100%">
</picture>
<br><sub>Clique num card: objetivo, critérios, plano, progresso das tarefas e o que cada agente fez.</sub>
</p>
<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/agents-dark.png">
  <img alt="A aba Agents com a saída ao vivo" src="docs/images/agents-light.png" width="100%">
</picture>
<br><sub>Agents: a saída ao vivo do planner, builder, revisores e retro.</sub>
</p>
<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/settings-dark.png">
  <img alt="A aba Settings com a lista de prontidão" src="docs/images/settings-light.png" width="100%">
</picture>
<br><sub>Settings: "Ready to run?" com o conserto exato de cada item, e todas as opções.</sub>
</p>

- **Board:** o kanban. **Arraste um card para outra coluna**: de Backlog para *Needs you* segura o card, de *Needs you* ou *Done* de volta para o Backlog recoloca na fila (um card pronto pode ser refeito), e soltar um card entre outros no Backlog define a prioridade (`priority:` no cabeçalho do card; menor roda primeiro). As colunas válidas acendem enquanto você arrasta; um card em andamento não pode ser movido, e só o pipeline move cards para *In progress* e *Done*. Sem mouse (ou no celular) abra o card e use *Move to*.
- **Flow:** as etapas de um card (split, plan, build, checks, review, merge), os vereditos dos revisores independentes e o que aconteceu, do card em execução ou de qualquer recente.
- **Planner:** todos os cards com objetivo, critérios, plano, progresso das tarefas e log. As perguntas vêm com 3 respostas sugeridas (clique em uma ou escreva a sua, depois *Send answers & run*); *Suggest answers* pede à IA quando o card veio sem.
- **Agents:** a saída ao vivo de pipeline, planner, builder, qa, cross e retro.
- **AIs:** quais modelos de IA estão ligados, quem faz o quê (splitter, planner, builder, retro, suggester, qa, cross), os limites da conta Claude ao vivo (sessão e semana, com a hora do reset), tokens e chamadas por modelo desta execução e de todas, *Detect again* e *Refresh limits*.
- **Settings:** "Ready to run?" com o conserto exato de cada item, e todas as configurações (branch base, comando de CI, tentativas, cards ao mesmo tempo, builders por card, limites...). Salvar o comando de CI o aprova, como no terminal.
- **Git:** a sua pasta como o TortoiseGit mostra. Cada arquivo alterado (novo, modificado, apagado, renomeado) com uma caixa para escolher e o diff a um clique; uma mensagem e *Commit* (ou *Commit & push*) commita só os arquivos escolhidos, e o que você deixou em stage em outros arquivos continua lá. *Fetch*, *Pull* (só fast-forward: nunca um commit de merge) e *Push* (o primeiro push publica a branch), quantos commits há para enviar e para trazer, e os últimos 30 commits com os que faltam enviar marcados (*to push*). Não muda nada enquanto um card está sendo construído na sua pasta, e só roda os seus git hooks com *Run my git hooks* ligado.
- **Map:** uma mudança como mapa mental, para ver o que está sendo feito, onde, e o que cada método faz. Escolha *Your uncommitted work* (os ramos são as pastas) ou qualquer card que já saiu do backlog (os ramos são as tarefas dele, pelos `[files: ...]` que cada tarefa cita, mais *Other changes*). As folhas são os arquivos alterados com as funções e classes que mudaram, cada uma com a própria docstring ou o comentário logo acima. Clique em uma para ver o que ela usa, quem a usa e o diff dela; uma sem docstring ganha o botão **Explain**: uma chamada pequena, só de leitura, à IA do papel `suggester`, só com aquele código (possíveis segredos apagados), guardada na pasta do projeto para o mesmo código nunca ser perguntado duas vezes. O seu index, as branches e os arquivos ficam como estão (usa uma cópia do index), e arquivos novos acima de 1 MB ficam fora do mapa.

<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/map-dark.png">
  <img alt="A aba Map: um card como mapa mental, o título no centro, as pastas como ramos, e os arquivos alterados com cada função alterada e o que a docstring dela diz" src="docs/images/map-light.png" width="100%">
</picture>
<br><sub>Map: o que está sendo feito (centro), onde (ramos), o que cada função alterada faz (folhas).</sub>
</p>

**＋ New request** (em qualquer aba): diga em palavras simples o que quer mudar. A IA do papel `suggester` monta o card (título, qual agente constrói, objetivo, 2 a 5 critérios testáveis); sem IA disponível, usa um rascunho simples por regras, então o pedido nunca se perde. Marque *start working now* e o pipeline começa (ou pega o card se já estiver rodando). Pedido vago não tem problema: o planner pergunta em vez de chutar. **Run** e **Stop** ficam no cabeçalho.

Segurança: a página só aceita pedidos com o token, vindos de `127.0.0.1`/`localhost` (proteção contra DNS rebinding) e, para alterações, da própria página (checagem de Origin). Tudo que o servidor envia é mostrado como texto, nunca como HTML. Use `--port N` para escolher a porta e `--no-open` para só imprimir o link.

## Grafo de mudanças

Antes de ler o diff de um card linha por linha, veja o que ele tocou: as funções, classes e arquivos que mudaram, e o código que os usa ou é usado por eles. Abra um card e clique em **Change graph** (ou `g`):

<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/graph-dark.png">
  <img alt="O grafo de mudanças de um card: arquivos como caixas, símbolos alterados como linhas, arestas de quem usa para o que é usado, e o painel lateral da função selecionada com o seu diff" src="docs/images/graph-light.png" width="100%">
</picture>
<br><sub>Arquivos são caixas, símbolos alterados são linhas (<code>+</code> adicionado, <code>~</code> modificado, <code>-</code> removido, <code>.</code> um vizinho sem mudança), as arestas vão de quem usa para o que é usado. Os hotspots, as mudanças mais conectadas, vêm marcados: comece por eles.</sub>
</p>

- **Clique em um símbolo** para ver onde ele está, o que usa, quem o usa, o que os revisores e os guardrails disseram dele e as suas próprias linhas do diff. **Focus here** mantém só ele e os vizinhos.
- **View** filtra por status, testes, achados dos revisores e alertas dos guardrails; busque com `/`; **List** mostra o mesmo em texto; **Export** salva SVG, Mermaid (cole num pull request), DOT ou JSON. Arraste para mover, roda do mouse ou `+` `-` para zoom, `f` para enquadrar. A barra de endereço é sempre um link para essa visão exata (`?graph=<card>`).
- **Tentativas:** cada tentativa salva o seu grafo, então dá para abrir uma anterior ou comparar duas e ver o que o ciclo de correção mudou.
- **No terminal:** `lonerchestrator graph 005` imprime o mesmo como árvore; `--focus <nome>` a vizinhança de um símbolo, `--compare 1..2` duas tentativas, `--format mermaid|dot|svg|json --out ARQUIVO` um arquivo, `--tui` navega pelo teclado.

Ele só mostra: nunca aprova nem bloqueia um card, lê o git sem rodar o seu código e nunca mostra um segredo nem o conteúdo de um arquivo protegido. Os revisores também podem receber um resumo dele calculado a partir do diff (*Reviewers read the graph* em Settings, desligado por padrão). Como é montado, o schema JSON e como adicionar uma linguagem: [docs/change-graph.md](docs/change-graph.md) (em inglês).

## Vários cards ao mesmo tempo

Ajuste **Cards at the same time** na aba Settings (ou `"parallel": 3` na config, ou `lonerchestrator run -j 3`). Cada card passa a trabalhar em uma git worktree própria (na pasta do projeto, `work/<card>`), com branch própria, então os agentes nunca mexem nos arquivos uns dos outros. Plano, build, guardrails, CI e as duas revisões rodam em paralelo; merges e retros acontecem um de cada vez no seu checkout principal. Se outro card foi mesclado antes, o card traz a base nova para a sua branch e roda o CI de novo antes do merge.

- **Dependências:** um card que precisa de outro antes diz isso no cabeçalho, `depends: 001-schema, 002-api`. Ele espera esses cards chegarem em `done/`. Cards sem `depends` são considerados independentes.
- **Uma worktree nova não tem dependências instaladas** (`node_modules`, virtualenv...). Coloque em `"setup"` o comando que prepara uma (por exemplo `"npm ci"`); ele roda uma vez por card e faz parte do que o `lonerchestrator trust` aprova.
- Cada card em andamento faz suas próprias chamadas de IA, então seus limites acabam mais rápido. O limite de taxa continua sendo esperado por card.
- A aba Flow acompanha o card mais recente; a aba Board marca todos os que estão rodando. Os painéis dos agentes misturam a saída de todos os cards (cada linha da tabela de log diz o card).
- `parallel: 1` (padrão) é o comportamento antigo: um card depois do outro, sem worktrees (a não ser que você tenha mudanças sem commit, veja abaixo).

## Mudanças sem commit não atrapalham

Você não precisa commitar antes de rodar. O `lonerchestrator run` (e o Run do painel e da página web) não tem arquivos próprios no seu projeto, então nunca commita nada além do trabalho dos cards, e as suas mudanças ficam exatamente como estão: o que você deixou em stage continua em stage. Cada card passa a ser construído a partir do último commit da branch base, numa worktree própria como no `parallel`, então os agentes não veem o que você não commitou (commite antes se um card depende disso; ajuste `setup` se o CI precisa de dependências instaladas). Um card aprovado chega na sua pasta por um fast-forward que atualiza só os arquivos que ele mudou. Se ele mudou um arquivo que você também está editando, o git recusa, nada é tocado, e o card espera em *Needs you* com o nome do arquivo: commite ou tire a sua mudança de lá (a aba Git da página web faz isso), depois mande o card de volta.

Ele ainda para em dois casos: mudanças numa branch que não é a base (volte para ela, ou commite) e um repositório sem nenhum commit (faça o primeiro, na aba Git ou com `git add -A` e `git commit`).

## Vários builders no mesmo card

Ajuste **Builders per card** (aba Settings, ou `"builders": 3`) e o planner passa a listar os arquivos de cada tarefa: `- [ ] criar o endpoint [files: api/users.py, tests/test_users.py] (critério 1)`. Tarefas que não dividem arquivo são construídas **ao mesmo tempo**, cada grupo por um builder em uma worktree descartável; as partes são mescladas na branch do card, e guardrails, CI e as duas revisões rodam no resultado inteiro como sempre.

Se qualquer coisa for duvidosa, volta para UM builder sem aproveitar nada da tentativa: tarefa sem `[files: ...]`, todas as tarefas dividindo um arquivo, parte que mexeu em arquivo que não declarou, parte bloqueada ou conflito de merge. Só a primeira tentativa é feita pelo time; as tentativas depois de uma rejeição usam um builder. Combina com cards em paralelo. Projetos criados antes desta função mantêm as instruções antigas do planner: rode `lonerchestrator init --force` para atualizá-las (ele sobrescreve as regras, os agentes e o script de CI da pasta com os modelos, então copie as suas edições antes), ou adicione a regra `[files: ...]` aos seus agentes planner.

## Qualquer IA

Todo papel (splitter, planner, builder, retro, os dois revisores e o sugestor de respostas) pode rodar em **qualquer IA de linha de comando**, não só o Claude Code. Escolha na aba AIs, ou no `config.json` do projeto:

<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/ais-dark.png">
  <img alt="A aba AIs com papéis e uso" src="docs/images/ais-light.png" width="100%">
</picture>
<br><sub>Qualquer IA em qualquer papel, com o uso ao vivo: limites da conta Claude, tokens exatos quando a CLI informa, estimativas marcadas com <code>~</code> e os seus próprios orçamentos.</sub>
</p>

```json
{
  "roles": { "builder": { "cli": "codex", "model": "default" }, "suggester": { "cli": "ollama", "model": "llama3" } },
  "reviewers": [ { "name": "qa", "kind": "gemini", "model": "default" }, { "name": "cross", "kind": "mine" } ],
  "providers": {
    "mine": {
      "name": "Minha IA",
      "cmd": ["minha-ia", "run"],
      "model_args": ["--model", "{model}"],
      "edit_args": ["--allow-edits"],
      "read_args": ["--read-only"],
      "prompt_via": "stdin",
      "models": ["grande", "pequeno"]
    }
  }
}
```

Um provider é só *como chamar a CLI*: `cmd`, `model_args` (`{model}` é trocado; o modelo `default` não passa nenhum), `edit_args` (vai nos papéis que alteram arquivos), `read_args` (revisores e sugestões) e `prompt_via` (`arg`, o padrão, com `prompt_flag` opcional como `-p`; ou `stdin`). Use `"can_edit": false` para modelos só de texto: eles revisam e sugerem, mas não constroem. Serve qualquer coisa que receba um prompt e imprima uma resposta.

| IA | Como é conhecida | Situação |
|---|---|---|
| Claude Code | preset nativo | testado pelo autor |
| Antigravity (`agy`) | preset | testado pelo autor |
| OpenAI Codex (`codex exec`) | preset | **escrito pela documentação do fabricante, não rodado aqui**: confira `codex exec --help` |
| Gemini CLI (`gemini`) | preset | **escrito pela documentação do fabricante, não rodado aqui**: confira `gemini --help` |
| Ollama (`ollama run`) | preset, só texto | **escrito pela documentação do fabricante, não rodado aqui** |
| Grok Build (`grok`), GitHub Copilot CLI (`copilot`), Cursor CLI (`cursor-agent`) | preset | **escrito pela documentação do fabricante, não rodado aqui** |
| Modelos do Ollama no Claude Code (`ollama-claude`), LM Studio (`lmstudio`) | preset: o Claude Code conduz o modelo local, então ele também constrói | **escrito pela documentação do fabricante, não rodado aqui** |
| MiniMax, DeepSeek, Z.ai GLM, Kimi, OpenRouter | preset: Claude Code com o endereço compatível com a Anthropic do fabricante, chave em `MINIMAX_API_KEY`, `DEEPSEEK_API_KEY`, `ZAI_API_KEY`, `MOONSHOT_API_KEY`, `OPENROUTER_API_KEY` | **escrito pela documentação do fabricante, não rodado aqui** |
| OpenCode, Aider, Goose, Qwen Code, seu script... | defina em `providers` | as flags mudam por versão: confira o `--help` da ferramenta |

**Como são encontradas.** Aperte `d` na aba AIs (ou rode `lonerchestrator intro`) e toda IA que este computador pode usar é encontrada sem perguntar nada a modelo nenhum: CLIs no seu PATH e a checagem de login delas (`claude auth status`, `codex login status`, `agy models`), servidores de modelos que respondem neste computador (Ollama na porta 11434 lista só os modelos que usam ferramentas; LM Studio na 1234) e chaves de API presentes no seu ambiente (só se estão definidas: o valor nunca é guardado nem mostrado). Só aparece o que existe de verdade, cada uma com o que falta se ainda não estiver pronta.

**Claude Code com outros modelos.** Um provider com `server` (um servidor de modelos local) ou `env` roda o próprio Claude Code contra aquele endereço, então o modelo ganha os agentes, as ferramentas e as edições do Claude Code. Sua chave e seu login da Anthropic ficam em branco nessas chamadas, a chave vem do seu ambiente (`"$MINHA_CHAVE"` em `env`, nunca escrita na config), todo apelido de modelo aponta para o modelo escolhido, e os tokens contam para aquela IA com o `price` dela, não para a sua conta Claude. O seu: `"providers": {"lan": {"native": true, "server": "http://box:8080", "models": ["qwen3-coder"]}}` (um provider definido pelo repositório precisa da sua aprovação, `lonerchestrator trust`).

Dá para mudar um preset do mesmo jeito (uma entrada `codex` em `providers` troca as flags dele). As outras IAs recebem as mesmas instruções dos agentes do Claude (o `agents/<papel>.md` da pasta mais o `rules.md`, colocados no prompt) e os revisores recebem o diff dentro do prompt, então funcionam mesmo se a CLI não lê arquivos. Um planner ou builder também precisa alcançar os cards, `context/` e `memory/` na pasta do projeto: `dir_args` diz como (`["--add-dir", "{dir}"]` no Codex, `["--include-directories", "{dir}"]` no Gemini CLI). Uma IA sem isso (o Antigravity não tem) pode não alcançá-los, então deixe-a nos papéis de revisor.

O que vale para toda IA: os guardrails do diff (caminhos protegidos, tamanho, segredos, testes apagados), a checagem de que a IA não mexeu no `.git`, o comando de CI, os dois revisores independentes e as pausas humanas. O que muda: o `settings.json` da pasta (listas de permitir/negar) só restringe o Claude Code. Nas outras IAs os limites são as flags do provider (`edit_args`/`read_args`, por exemplo um modo sandbox), então leia-as. Como um provider inicia um programa, o que vem na config de um projeto precisa ser aprovado uma vez com `lonerchestrator trust`, como o comando de CI.

## Os agentes estudam o seu projeto

Os agentes leem o `context/project.md` antes de cada card. Quando ele está vazio, o orquestrador estuda o repositório e o preenche, para os agentes não trabalharem às cegas:

- **Quando:** no começo do `lonerchestrator run` (inclusive o Run do painel e da página web) quando há cards a fazer, com `lonerchestrator context`, ou com o botão *Study the project now* na aba Settings da página web.
- **O que ele olha, sem nenhuma IA:** árvore de arquivos e linguagens, `package.json` / `pyproject.toml` / `Cargo.toml` / `go.mod` / `Makefile` (scripts e alvos viram os comandos de teste, lint e build, todos eles num repositório misto), configs de ferramentas, workflows de CI, pastas de teste, o começo do README e os últimos commits. Segredos (`.env`, chaves) nunca são lidos.
- **Quem escreve:** a IA do papel `suggester` recebe só esses fatos (somente leitura, sem ferramentas) e escreve os cinco itens: o que é, stack, como rodar/testar/lintar/buildar, convenções, o que os agentes nunca devem fazer. Ela é instruída a escrever `unknown: ask the user` em vez de inventar. Sem IA disponível, os fatos são escritos como estão, então o arquivo nunca fica vazio e uma execução nunca espera por uma IA.
- **O que é seu continua seu:** um arquivo que já tem conteúdo nunca é sobrescrito (`--force` redige de novo; `--basic` pula a IA). Ele fica na pasta do projeto, então não há nada para commitar.
- Os fatos (nomes de arquivos, scripts dos manifestos, começo do README) vão para a mesma IA que você já usa no papel `suggester`, nada mais sai da sua máquina.

## Onde ficam os arquivos dele

Fora do seu projeto. Cada projeto ganha uma pasta própria, `~/.lonerchestrator/projects/<projeto>-<hash>/` (o `lonerchestrator doctor` mostra qual), então perder o projeto ou clonar de novo não perde card, contexto nem lição, e nenhum arquivo do orquestrador aparece no seu git status:

```
~/.lonerchestrator/projects/meu_projeto-1a2b3c4d/
├── config.json                                  suas configurações (só o que você mudou)
├── rules.md  agents/  settings.json             as regras, os agentes e as permissões deles (edite à vontade)
├── ci.sh                                        lint + testes + build do projeto
├── board/{backlog,doing,review,done,blocked}/   cards (.md)
├── context/{project,decisions,history}.md       contexto lido pelos agentes
├── memory/{backend,frontend,docs,qa}.md         lições aprendidas por área (a retro cuida)
├── runs/  streams/  log.md                      logs por execução, streams, tabela legível
└── work/<card>/                                 a worktree de um card, enquanto ele é construído
```

A pasta é achada pelo caminho do projeto. Um projeto que mudou de lugar (renomeado, outro disco, clonado de novo depois de perdido) é reconhecido pelo primeiro commit e recebe a pasta dele de volta no primeiro comando, aprovação incluída; um segundo clone ao lado do original ganha uma pasta própria.

O `LONERCHESTRATOR_HOME` muda tudo isso de lugar, por exemplo para uma pasta sincronizada, para sobreviver também à perda da máquina. Os agentes alcançam os cards, `context/` e `memory/` da pasta (o Claude Code pelo `--add-dir`), nunca a config, as regras, os agentes ou o script de CI. O Claude Code recebe o agente, as regras e as permissões por flags de linha de comando, então um `CLAUDE.md` ou `.claude/` seu fica como está.

**Vindo de uma versão antiga:** os arquivos do orquestrador ficavam no projeto (`board/`, `context/`, `memory/`, `.orchestrator/`, `scripts/ci.sh`, `CLAUDE.md`, `GEMINI.md`, `.claude/agents`...). O primeiro comando num projeto assim move tudo para a pasta dele: cards, contexto, memória, logs, config e script de CI como estão; as regras, permissões e agentes-modelo antigos para `old-setup/` (os novos tomam o lugar); agentes seus para o orquestrador para `agents/`, apontados para a pasta. Um arquivo que não é reconhecidamente do orquestrador fica onde está, e as linhas que o `init` pôs no `.gitignore` saem. O git então mostra os arquivos movidos como apagados: commite isso (aba Git da página web).

Logs: `log.md` (tabela legível), `runs/<execução>/events.jsonl` (estruturado) e, por card, o texto completo de cada agente.

## Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| `Failed to authenticate` / OAuth expirado | Rode `claude` (ou `agy`) uma vez e faça login |
| Permissões do `settings.json` ignoradas | Pasta não confiável: rode `claude` dentro dela e aceite o diálogo (confiar na pasta-pai não vale) |
| "you have uncommitted changes on X" | Volte para a branch base, ou faça commit delas: os cards aprovados são mesclados na branch base |
| Card bloqueado: "merge into main failed: ... would be overwritten" | O card mudou um arquivo que você está editando: faça commit ou tire a sua mudança de lá (aba Git), depois mande o card de volta |
| "Window too small" | O painel precisa de 120×34; use `lonerchestrator live` ou aumente a janela |
| `gemini` pede para migrar | Use o `agy` (já é o padrão do revisor `cross`) |
| Pipeline não inicia pelo painel | Veja o `run.out` na pasta do projeto (a página web mostra a última linha dele ao lado de *stopped*) |

## Desenvolvimento

```bash
cd D:\Github\orchestrator
python -m venv .venv
.venv\Scripts\python -m pip install -e . -r requirements/dev.txt
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m pytest -q        # 33 testes: pipeline com agentes falsos + git real, guardrails, TUI
```

Só biblioteca padrão, sem dependências. Módulos em `orch/`: `pipeline` (o laço), `agents` (execução dos CLIs, backoff), `guardrails`, `board` (cards), `gitops`, `events` (logs), `tui`/`view` (painel), `intro`, `config`, `folder` (a pasta do projeto, e a mudança do layout antigo para ela), `cli`. Os templates que o `init` copia para a pasta do projeto ficam em `orch/templates/`.
