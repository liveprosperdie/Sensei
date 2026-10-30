# Akira — Local-First Voice & Desktop Assistant (Standalone)

Akira is a zero-Claude-cost, local-first Windows desktop & browser automation assistant powered by free Groq API routing + local Ollama (`llama3:8b`) Servant & Guard models.

## Key Safety Guarantees
- **100% Non-Destructive Handoff**: Akira never deletes files, folders, branches, repositories, slides, or calendar events, nor does it empty the Recycle Bin or power off your PC. Instead, Akira navigates you directly to the target (e.g., highlighting the file in Windows Explorer with `explorer.exe /select,<path>`) and says: *"Now you can delete it yourself."*
- **100% Free Operation (`AKIRA_DISABLE_CLAUDE=true`)**: Uses free Groq API (`llama-3.3-70b-versatile` / `llama-3.1-8b-instant`) and local Ollama models. Paid Anthropic Claude API calls are disabled by default.
- **Deterministic Guard (`guard_rules.py` + `security_guard.py`)**: Every action is validated against strict field shapes, path traversal rules, Windows reserved device name checks, and URI protocol allowlists before execution.

## Quick Start
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Add your free GROQ_API_KEY in .env
python verify_guard_coverage.py
python akira.py
```
