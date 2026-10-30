"""Akira Teaching Mode — an adaptive, local-first learning environment.

Architecture (see AKIRA_SYSTEM_OVERVIEW_AND_ROADMAP.md):

  * Models only ever produce Markdown + small JSON sidecars that follow a fixed
    schema (teaching/schema.py). They never write UI code and never touch the OS.
  * The UI (teaching/static) is a dumb, deterministic renderer over those files.
  * Nothing here dispatches to executor.py, guard*.py or Obsidian. Teaching Mode
    reads/writes ONLY inside its own workspace directory.

Security posture is documented in teaching/server.py and tested in
tests/test_teaching_mode.py.
"""
