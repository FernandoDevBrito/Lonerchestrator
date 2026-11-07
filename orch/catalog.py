"""The AI CLIs lonerchestrator can drive, and how each one is installed.
The install commands are the vendors' own official one-liners (Claude Code: code.claude.com/docs/en/setup,
Antigravity: antigravity.google/docs/getting-started?tab=cli). They are only ever run after showing the command and asking,
unless the user passed --yes / -With on purpose."""

AIS = [
    {
        "id": "claude", "name": "Claude Code", "exe": "claude", "required": True,
        "why": "planner, builder, retro and the qa reviewer run on it",
        "url": "https://code.claude.com/docs/en/setup",
        "install": {"windows": "irm https://claude.ai/install.ps1 | iex",
                    "posix": "curl -fsSL https://claude.ai/install.sh | bash"},
        "dirs": ["~/.local/bin"], "win_dirs": [],
        "login": "run `claude` once and follow the browser prompts",
    },
    {
        "id": "agy", "name": "Antigravity CLI", "exe": "agy", "required": False,
        "why": "a Gemini model for the second reviewer (a different model family catches different mistakes)",
        "url": "https://antigravity.google/docs/getting-started?tab=cli",
        "install": {"windows": "irm https://antigravity.google/cli/install.ps1 | iex",
                    "posix": "curl -fsSL https://antigravity.google/cli/install.sh | bash"},
        "dirs": ["~/.local/bin"], "win_dirs": ["%LOCALAPPDATA%/agy/bin"],
        "login": "run `agy` once and sign in with a Google account approved for Antigravity",
    },
    {
        "id": "codex", "name": "OpenAI Codex CLI", "exe": "codex", "required": False,
        "why": "OpenAI models for any role (needs Node.js/npm)",
        "url": "https://github.com/openai/codex",
        "install": {"windows": "npm install -g @openai/codex", "posix": "npm install -g @openai/codex"},
        "dirs": [], "win_dirs": [],
        "login": "run `codex` once and sign in",
    },
    {
        "id": "gemini", "name": "Gemini CLI", "exe": "gemini", "required": False,
        "why": "Google Gemini models for any role (needs Node.js/npm)",
        "url": "https://github.com/google-gemini/gemini-cli",
        "install": {"windows": "npm install -g @google/gemini-cli", "posix": "npm install -g @google/gemini-cli"},
        "dirs": [], "win_dirs": [],
        "login": "run `gemini` once and sign in",
    },
    {
        "id": "ollama", "name": "Ollama (local models)", "exe": "ollama", "required": False,
        "why": "free local models; text only, so they review and suggest but do not build",
        "url": "https://ollama.com/download",
        "install": {"windows": "irm https://ollama.com/install.ps1 | iex", "posix": "curl -fsSL https://ollama.com/install.sh | sh"},
        "dirs": [], "win_dirs": [],
        "login": "run `ollama pull <model>` once to download a model",
    },
]
IDS = [e["id"] for e in AIS]
