# Berthline Tools

The Java side of [Berthline](https://github.com/RichardSpinola/berthline): run, debug, create and
refactor Java with menus and shortcuts close to IntelliJ IDEA, on top of Red Hat's Java support.

## What it adds

- **Run and debug** with one button and saved run configurations.
- **Build** menu: Build, Rebuild and Export Runnable JAR.
- **New Java Class** dialog: class, abstract class, interface, enum, record, exception, main class
  and annotation. `Dog extends Pet implements Runnable` fills in what the parents require.
- **Generate** (constructor, getters, setters, `equals`/`hashCode`, `toString`, override).
- **Postfix completion**: `.var`, `.sout`, `.for`, `.if`, `.null`.
- **Refactor, navigation and Git menus** in the editor and the Explorer.
- **An icon per Java type** in tabs and in the tree, and tabs without `.java`.

## Shortcuts (IntelliJ keymap)

| Action | Keys |
| --- | --- |
| Search Everywhere | Shift Shift |
| Run / Debug | Shift+F10 / Shift+F9 |
| Rerun / Stop | Ctrl+5 / Ctrl+2 |
| Build | Ctrl+9 |
| Toggle Breakpoint | Ctrl+8 |
| Context Actions | Alt+Enter |
| Generate | Alt+Insert |
| Rename | Shift+F6 |
| File Structure | Ctrl+0 |
| Recent Files | Ctrl+E |
| Terminal | Alt+F12 |

The Hub can switch the Java app to the plain VS Code keymap; its Learn screen lists the keys in use.

## Icons

The Java type icons are drawn for Berthline and ship here. The file icon pack named Berthline comes
with the Berthline Hub extension; pick the pack in the Hub, under Customize.

## License and AI use

MIT, like the rest of Berthline. Most of the code was written with AI: Claude Opus 5.5 and
Claude Fable 5.2 (Anthropic), through Claude Code, directed and tested by the author.
