# Berthline Web

The Web side of [Berthline](https://github.com/RichardSpinola/berthline): a live preview beside the
editor, plain HTML blocks, and one Run button for HTML, JavaScript and TypeScript.

## Preview

Opens beside the editor when the folder has an `index.html`, or with **Web: Open Preview**
(Ctrl+K V). A small server inside the editor serves the folder on `127.0.0.1` at a free port, and
stops when the preview tab closes. No extra browser runs.

- Saving reloads the page; a CSS change swaps in place without a reload.
- A project whose `package.json` has a `dev` script (Vite and the like) can run `npm run dev`
  instead. The preview reads the address it prints and shows that server. The choice is
  remembered per folder; `npm install` runs first when `node_modules` is missing.
- Toolbar: reload, address, width (Fit, 390, 768, 1280), inspect, move to a new window, open in
  your browser (for DevTools).
- **Inspect**: click an element to open its line in the HTML file. While inspect is on, the cursor
  in the HTML file outlines its element in the preview. Exact for plain HTML; for React, Vue and
  Svelte it uses their development metadata when it is there.
- **DevTools**: right-click in the page > Inspect, or the toolbar's DevTools button, docks Chromium's
  own DevTools (Elements, Console, Sources, Network) under the page. Its window button moves it to a
  window of its own. It uses the editor's debugging port, which the Hub opens; the preview server
  relays it and accepts it only from itself and only for the preview page.
- Console errors of the page are counted in the toolbar and listed under Output > Preview.
- Status bar: **Preview** opens it; while it runs it shows the port, and a click offers Show, Stop
  and whether it opens by itself. Nothing runs while the preview is closed.
- `web.preview.openOnStartup` turns the automatic opening off.

## Insert Block

**Web: Insert Block** (Ctrl+Alt+B, or the editor's right-click menu in HTML) lists eight plain HTML
pieces: navigation, hero, cards, card with image, gallery, contact form, two columns and footer.
Each goes in at the cursor with fields to fill (Tab moves between them), and its CSS is added once to
the stylesheet the page links to (`style.css` when there is none).

## Run

| Action | Keys |
| --- | --- |
| Run (HTML opens the preview; JS and TS run on the bundled Node) | Ctrl+F5 |
| Debug (HTML: in Chrome, Chromium, Edge, Brave or Vivaldi if one is installed, breakpoints in the editor) | F5 |
| Stop | Shift+F5 |
| Run again | Ctrl+Shift+F5 |

## License and AI use

MIT, like the rest of Berthline. Most of the code was written with AI: Claude Opus 5.5 and
Claude Fable 5.2 (Anthropic), through Claude Code, directed and tested by the author. The preview
and blocks in 0.3.0 were written with Claude Opus 5.5.
