# Vendored: FoundationAgents/ReCode

- Source: https://github.com/FoundationAgents/ReCode (MIT, see LICENSE)
- Commit: 6e7223f71281d914762e78d7bbcf6446d362ecbc (2026-04-21, "Add MIT License")
- Files: only what the agent loop imports (agents/recode, base, utils). Environments, configs and run.py are not
  included.
- Local changes: empty `__init__.py` files so these directories import as regular packages ahead of any other
  `utils`/`base` package. No upstream source line is modified.
- Integration: `clevrer_bench/systems/recode_system.py` subclasses `ReCodeAgent` (model calls through the metered
  client; resources for the `docqa` environment) and `Executor` (every code block runs in the OTF sandbox).
