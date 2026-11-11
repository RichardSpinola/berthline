# Build from source

```bash
python3 -m venv .venv
.venv/bin/pip install PySide6 pyinstaller certifi
.venv/bin/python build/build.py
```

The package lands in `dist/`. Downloads (editor, Node.js) are cached in `build/cache`.

## Tests

They live in `tests/` and run on GitHub Actions on Windows and Linux.

| Test | Checks |
|---|---|
| `tests/hub_test.py <package>` | Hub logic: settings, keymaps, shortcuts, Setup, update check |
| `tests/hub_audit.py <package>` | Every Hub control, against `tests/hub_controls.txt` |
| `tests/update_test.py [<package> [--from <older package>] [--audit]]` | The updater: swap, rollback, migration; with `--from`, a real update from an older release, and with `--audit`, the Java audit afterwards |
| `node tests/audit.js <package> <java\|web>` | Commands, shortcuts, menus, themes and editor behaviour |
| `node tests/smoke.js <package>` | Each profile starts |
| `node tests/measure.js <package>` | Startup time and memory, see [measurements](measurements.md) |

The editor tests need a display; on a server, run them under `xvfb-run`.
