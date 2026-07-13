# BiliSpider Agent File Guide

This file is for AI coding agents and human contributors. Read it before adding files.

## Golden Rule

Do not add new files to the repository root unless they are stable project entry points or top-level project metadata.

Allowed root files are limited to:

- `README.md`, `requirements.txt`, `.gitignore`, `.gitattributes`
- CLI/GUI entry points: `gui.py`, `login.py`, `crawl_comments.py`
- Explicit project metadata added intentionally by maintainers

Root-level scratch files such as `test_*.py`, `analyze_*.py`, `cdp_*.py`, `debug_*.py`, temporary databases, and one-off reports are not allowed.

## Where Files Belong

Use this placement map:

| File type | Put it here | Notes |
| --- | --- | --- |
| Application package code | `bilispider/` | Core reusable modules only. Keep GUI wrappers outside unless they are package internals. |
| GUI/CLI entry points | repository root | Only stable user-facing launchers belong here. |
| Dataset tools | `tools/` | User-facing scripts for export/import/validation/reporting. |
| Developer-only maintenance scripts | `tools/dev/` | Reusable diagnostics, manifest rebuilders, API probes. |
| Short-lived local scratch | `tmp/` | Ignored by git. Delete when done. |
| Examples | `examples/` | Small runnable examples, not tests or private experiments. |
| Documentation | `docs/` | Architecture notes, guides, changelogs, references. |
| Packaging config | `packaging/` | PyInstaller, Inno Setup, release build scripts. |
| Shared datasets | `datasets/` | Only sanitized `.jsonl` datasets and `manifest.json`. |
| Runtime data | `data/` | Local-only cookies, config, queue, SQLite DB. Never commit secrets. |
| Build outputs | `build/`, `dist/`, `release/` | Generated artifacts. Do not edit manually. |

## Tests And Experiments

- Do not create root-level `test_*.py` files.
- If a test is intended to be kept, create a dedicated test layout first, for example `tests/test_*.py`.
- If a script is only for one investigation, put it in `tmp/` and do not commit it.
- If a diagnostic script is useful long term, put it in `tools/dev/` with a clear name and no embedded secrets.

## Sensitive And Generated Files

Never commit or print secrets from:

- `data/cookies.json`
- `data/config.json`
- `data/crawl_queue.json`
- `data/comments.db`
- `*.db`, `*.db-wal`, `*.db-shm`
- raw browser captures that contain Cookie, authorization headers, or personal data

Do not commit generated outputs from:

- `.venv/`
- `__pycache__/`
- `build/`
- `dist/`
- `release/`
- `tmp/`

## Before Adding A File

Ask these questions:

1. Is this file meant to be used by end users?
2. Is it reusable, or just for this debugging session?
3. Does it contain local paths, cookies, tokens, database records, or raw network captures?
4. Does an existing directory already express its purpose?

If the answer is unclear, prefer `tmp/` for scratch work or update `docs/PROJECT_STRUCTURE.md` when introducing a new stable directory.

