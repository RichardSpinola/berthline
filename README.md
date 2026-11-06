# Berthline

Portable coding profiles built on top of a pinned VSCodium. Each profile keeps its own settings and extensions, so nothing touches an editor you already use.

## Profiles
- **Java**: run, debug, refactor and inspect Java projects.
- **Web**: HTML, CSS, JavaScript and TypeScript, with Node.js included.
- **Standard**: the plain editor.

## Use
Extract the package and open `Hub` (`Hub.exe` on Windows). Telemetry and AI features are off by default and can be changed per app under Settings.

## Build
```bash
python3 -m venv .venv
.venv/bin/pip install PySide6 pyinstaller
.venv/bin/python build/build.py
```
The package lands in `dist/`.

## AI use
This project was built with AI assistance: Claude Opus 5.5 (Anthropic), through Claude Code. A person reviewed the work and decided what to keep.

## Status
Early preview. Not affiliated with VSCodium, Microsoft, JetBrains or Oracle.
