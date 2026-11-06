<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.svg">
  <img src="docs/images/logo-light.svg" alt="Berthline logo" width="96">
</picture>

# Berthline

**A lighter editor that works closer to an IDE.**

Java and Web profiles built on VSCodium, with one Hub to launch them.

[![License: MIT](https://img.shields.io/badge/license-MIT-26313D)](LICENSE)
![Platforms: Windows and Linux](https://img.shields.io/badge/platforms-Windows%20%7C%20Linux-26313D)
![Status: early preview](https://img.shields.io/badge/status-early%20preview-C8102E)

[Download](#download) · [First run](#first-run) · [Profiles](#profiles) · [Why Berthline](#why-berthline) · [Limitations](#limitations)

</div>

<br>

<table>
  <tr>
    <td width="34%"><img src="docs/images/hub.png" alt="Berthline Hub listing the Java, Web and Standard apps"></td>
    <td width="66%"><img src="docs/images/welcome.png" alt="Welcome screen of Berthline Web"></td>
  </tr>
</table>

## Download

Get the latest package from [Releases](https://github.com/RichardSpinola/berthline/releases).

| System | File | Download | Extracted |
|---|---|---|---|
| Windows 10 or 11, x64 | `berthline-windows.zip` | about 530 MB | about 1.1 GB |
| Linux x64 | `berthline-linux.tar.gz` | about 590 MB | about 1.5 GB |

`SHA256SUMS` in each release lets you check the files.

## First run

**Windows**

1. Extract the zip to a local folder, such as the Desktop. It runs slowly from a USB drive.
2. Open `Hub.exe`.
3. The package is not signed yet, so SmartScreen may warn you. Choose *More info*, then *Run anyway*.

**Linux**

```bash
tar -xzf berthline-linux.tar.gz
./berthline-linux/Hub
```

On Ubuntu 24.04 or later, the editor may need unprivileged user namespaces to start.

## Profiles

Each profile keeps its own settings and extensions, so nothing touches an editor you already have.

| | Profile | What you get |
|---|---|---|
| <img src="hub/assets/java.svg" alt="" width="40"> | **Java** | Run with console input, debug, create classes and profile. The Java runtime is included, so you don't need to install a JDK. |
| <img src="hub/assets/web.svg" alt="" width="40"> | **Web** | HTML, CSS, JavaScript and TypeScript, with Node.js, Live Server, ESLint, Prettier and a REST client. |
| <img src="hub/assets/standard.svg" alt="" width="40"> | **Standard** | The plain editor, for everything else. |

![Java profile running a program that reads console input](docs/images/java.png)

## Why Berthline

IntelliJ IDEA is great, but it can use a lot of memory and slow down a modest computer. VS Code is lighter, yet many people complain about how it handles Java.

Berthline tries to close that gap. Each profile sets up the editor for one kind of work, starting with Java, so it behaves more like an IDE and stays light. Keeping profiles apart also means a Java setup never slows down a Web project.

It suits small and medium projects and modest computers. For large projects, a full IDE is still the better tool.

### The name

A *berth* is the place where a ship docks. A *line* is a shipping line, a fleet that sails under one flag. Berthline is a fleet of coding tools, and each one has its own berth.

### The look

The interface takes its cues from JetBrains IDEs and Toolbox: one place to launch your tools, a quiet dark theme, IntelliJ-style shortcuts and run buttons where you expect them.

The icons follow the nautical theme. All of them share the same hull and change only the cargo: steam for Java, `< >` for Web and a prompt for Standard. The Hub is the ship with the red flag. They are flat, in solid colors, so they stay clear at small sizes.

## Portability and privacy

- Profiles, settings and extensions stay inside the Berthline folder.
- The list of trusted folders is stored in `.berthline-shared` in your user folder, and new projects go to `Projects` there. This is what stays on a shared computer.
- On Linux, the Hub adds a hidden shortcut to your user folder so the taskbar shows the right icon.
- Telemetry and AI features are off by default. You can change them per app under Settings.

## Limitations

- Early preview: expect rough edges.
- No automatic updates yet. Download a new release to update.
- A managed computer can block `.exe` files. Only its administrator can change that.

## Build from source

```bash
python3 -m venv .venv
.venv/bin/pip install PySide6 pyinstaller
.venv/bin/python build/build.py
```

The package lands in `dist/`. Tests live in `tests/` and run on GitHub Actions on Windows and Linux.

## AI use

This project was built with AI assistance: Claude Opus 5.5 (Anthropic), through Claude Code. A person reviewed the work and decided what to keep.

## License

MIT, see [LICENSE](LICENSE). Bundled software keeps its own license, see [NOTICE](NOTICE).

Not affiliated with VSCodium, Microsoft, JetBrains or Oracle.
