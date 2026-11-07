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
]
IDS = [e["id"] for e in AIS]
