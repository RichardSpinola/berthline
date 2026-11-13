# Bean Barge

The Java profile. It aims to feel close to IntelliJ IDEA on a computer that can't run it comfortably.

## What you get

- The Java runtime is included: no JDK to install.
- **Run and debug** with one button, console input in the terminal, saved run configurations.
- **New Project** with Maven or Gradle, or a plain `src/` folder.
- **New Java Class**: class, abstract class, interface, enum, record, exception, main class and
  annotation. `Dog extends Pet implements Runnable` fills in what the parents require.
- **Generate** (constructor, getters, setters, `equals`/`hashCode`, `toString`, override) and
  postfix completion (`.var`, `.sout`, `.for`, `.if`, `.null`).
- **Build** menu: Build, Rebuild and Export Runnable JAR.
- **Run with Profiler**, with a page that shows where the program spends time and memory.
- Islands Dark theme, JetBrains-style file icons and an icon per Java type.

## Keys

IntelliJ keys by default; the Hub can switch Bean Barge to the plain VS Code keys, under Customize.
The Hub's Learn screen lists the keys in use.

| Action | Keys |
| --- | --- |
| Search Everywhere | Shift Shift |
| Run / Debug | Shift+F10 / Shift+F9 |
| Rerun / Stop | Ctrl+5 / Ctrl+2 |
| Build | Ctrl+9 |
| Context Actions | Alt+Enter |
| Generate | Alt+Insert |
| Rename | Shift+F6 |

## Memory

The Java language server is the biggest part of Bean Barge's memory. Its limit is set under
Customize > Memory limit. See [measurements](../measurements.md).

## Under the hood

Red Hat's Java support, Microsoft's Java debugger, Maven and Gradle support, and Berthline's own
extension (`extension/`) for menus, dialogs, run configurations and icons. Settings live in
`profiles/java/` and `profiles/base/`.
