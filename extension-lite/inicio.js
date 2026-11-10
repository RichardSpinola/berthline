// Berthline start page: replaces the editor's own welcome page, in the editor's own look.
// The app's boat bobs on the water: a 1-second timer moves it one pixel (no CSS animation, which repaints every frame);
// it stops with the Hub's Animations option, the berthline.welcome.animation setting or reduced motion.
const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

let painel = null;

function raiz() {
    if (process.env.SUITE_HUB_ROOT) return process.env.SUITE_HUB_ROOT;
    return process.env.SUITE_HUB ? path.dirname(process.env.SUITE_HUB) : null;
}

function ler(arquivo, padrao) {
    try { return fs.readFileSync(arquivo, 'utf8'); } catch { return padrao; }
}

function dadosDoApp() {
    const app = process.env.SUITE_APP || 'standard';
    const r = raiz();
    const info = r ? JSON.parse(ler(path.join(r, 'profiles', app, 'app.json'), '{}')) : {};
    const marca = r ? JSON.parse(ler(path.join(r, 'brand.json'), '{}')) : {};
    // Only the app's own icon is inlined; anything unexpected in it is dropped
    let barco = r ? ler(path.join(r, 'assets', `${app}.svg`), '') : '';
    if (!/^<svg[\s>]/.test(barco.trim()) || /<script|on\w+=/i.test(barco)) barco = '';
    return { app, titulo: info.title || 'Standard', cor: info.accent || '#8C939E', aprender: info.learn || [],
        nome: marca.name || 'Berthline', lema: marca.tagline || '', versao: marca.version || '', barco };
}

const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

async function recentes() {
    try {
        const r = await vscode.commands.executeCommand('_workbench.getRecentlyOpened');
        return (r?.workspaces || []).map(w => w.folderUri || w.workspace?.configPath).filter(Boolean).slice(0, 6)
            .map(u => vscode.Uri.revive(u)).filter(u => u.scheme === 'file');
    } catch { return []; }
}

function animar() {
    return process.env.SUITE_ANIMATIONS !== '0' && vscode.workspace.getConfiguration('berthline.welcome').get('animation', true);
}

async function abrir(context, focar = true) {
    if (painel) return painel.reveal(undefined, !focar);
    const midia = vscode.Uri.file(path.join(vscode.env.appRoot, 'out', 'media'));
    painel = vscode.window.createWebviewPanel('berthline.welcome', 'Welcome', { viewColumn: vscode.ViewColumn.One, preserveFocus: !focar },
        { enableScripts: true, localResourceRoots: [midia] });
    painel.onDidDispose(() => { painel = null; }, null, context.subscriptions);
    painel.webview.onDidReceiveMessage(async m => {
        if (m.type === 'cmd' && COMANDOS.has(m.id)) vscode.commands.executeCommand(m.id);
        else if (m.type === 'recent') {
            const lista = await recentes();
            const alvo = lista[Number(m.i)];
            if (alvo) vscode.commands.executeCommand('vscode.openFolder', alvo, { forceNewWindow: false });
        } else if (m.type === 'link' && /^https:\/\//.test(m.url)) vscode.env.openExternal(vscode.Uri.parse(m.url));
        else if (m.type === 'startup') vscode.workspace.getConfiguration('berthline.welcome').update('onStartup', !!m.on, vscode.ConfigurationTarget.Global);
        else if (m.type === 'animation') {
            await vscode.workspace.getConfiguration('berthline.welcome').update('animation', !!m.on, vscode.ConfigurationTarget.Global);
        }
    }, null, context.subscriptions);
    painel.webview.html = pagina(painel.webview, dadosDoApp(), await recentes(), animar());
}

const COMANDOS = new Set(['workbench.action.files.newUntitledFile', 'workbench.action.files.openFile', 'workbench.action.files.openFolder',
    'git.clone', 'berthline.openHub', 'workbench.action.openRecent', 'workbench.action.showCommands']);

function pagina(webview, d, lista, mover) {
    const nonce = crypto.randomBytes(16).toString('base64');
    const fonte = webview.asWebviewUri(vscode.Uri.file(path.join(vscode.env.appRoot, 'out', 'media', 'codicon.ttf')));
    const inicio = vscode.workspace.getConfiguration('berthline.welcome').get('onStartup', true);
    const acoes = [
        ['workbench.action.files.newUntitledFile', '&#xea7f;', 'New File…'],
        ['workbench.action.files.openFile', '&#xea94;', 'Open File…'],
        ['workbench.action.files.openFolder', '&#xeaf7;', 'Open Folder…'],
        ['git.clone', '&#xeb3e;', 'Clone Git Repository…'],
        ['berthline.openHub', '&#xea9b;', 'Back to Hub'],
    ];
    const casa = require('os').homedir();
    const curto = p => p.startsWith(casa) ? '~' + p.slice(casa.length) : p;
    return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; font-src ${webview.cspSource}; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>
@font-face { font-family: codicon; src: url("${fonte}") format("truetype"); }
body { margin: 0; color: var(--vscode-foreground); background: var(--vscode-editor-background);
  font-family: var(--vscode-font-family); font-size: 13px; }
main { max-width: 900px; padding: 56px 64px 32px; }
header { display: flex; align-items: flex-end; gap: 20px; margin-bottom: 40px; }
.mar { position: relative; width: 88px; height: 76px; overflow: hidden; flex: none; }
.barco { position: absolute; left: 12px; top: 6px; width: 64px; height: 64px; transform-origin: 50% 70%; }
.barco svg { width: 64px; height: 64px; display: block; }
.agua { position: absolute; left: 0; bottom: 6px; width: 176px; height: 8px; color: ${d.cor}; opacity: .55; }
.agua.dois { bottom: 1px; opacity: .3; }
h1 { margin: 0; font-size: 28px; font-weight: 400; line-height: 1.2; }
.lema { margin-top: 4px; color: var(--vscode-descriptionForeground); font-size: 16px; }
.colunas { display: grid; grid-template-columns: 1fr 1fr; gap: 48px; }
h2 { margin: 0 0 10px; font-size: 18px; font-weight: 400; }
section + section { margin-top: 32px; }
ul { list-style: none; margin: 0; padding: 0; }
li { margin: 0 0 6px; }
a, button.link { color: var(--vscode-textLink-foreground); text-decoration: none; cursor: pointer; background: none; border: 0; padding: 0; font: inherit; }
a:hover, button.link:hover { color: var(--vscode-textLink-activeForeground); text-decoration: underline; }
a:focus-visible, button:focus-visible, input:focus-visible { outline: 1px solid var(--vscode-focusBorder); outline-offset: 2px; }
.ico { font: normal normal normal 16px/1 codicon; display: inline-block; width: 16px; margin-right: 8px; vertical-align: -3px; }
.caminho { color: var(--vscode-descriptionForeground); margin-left: 8px; }
.vazio { color: var(--vscode-descriptionForeground); }
footer { display: flex; gap: 24px; justify-content: center; padding: 24px; color: var(--vscode-descriptionForeground); }
label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
input[type=checkbox] { accent-color: ${d.cor}; margin: 0; }
@media (max-width: 640px) { main { padding: 32px 24px; } .colunas { grid-template-columns: 1fr; gap: 32px; } }
</style>
</head>
<body>
<main>
  <header>
    <div class="mar${mover ? ' anda' : ''}" id="mar" aria-hidden="true">
      <div class="barco">${d.barco}</div>
      <svg class="agua" viewBox="0 0 176 8" preserveAspectRatio="none"><path d="M0 4 Q11 0 22 4 T44 4 T66 4 T88 4 T110 4 T132 4 T154 4 T176 4" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
      <svg class="agua dois" viewBox="0 0 176 8" preserveAspectRatio="none"><path d="M0 4 Q11 0 22 4 T44 4 T66 4 T88 4 T110 4 T132 4 T154 4 T176 4" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
    </div>
    <div>
      <h1>${esc(d.nome)} ${esc(d.titulo)}</h1>
      <div class="lema">${esc(d.lema)}${d.versao ? ` · ${esc(d.versao)}` : ''}</div>
    </div>
  </header>
  <div class="colunas">
    <div>
      <section>
        <h2>Start</h2>
        <ul>${acoes.map(([id, ico, texto]) => `<li><button class="link" data-cmd="${id}"><span class="ico">${ico}</span>${texto}</button></li>`).join('')}</ul>
      </section>
      <section>
        <h2>Recent</h2>
        ${lista.length ? `<ul>${lista.map((u, i) => `<li><button class="link" data-recent="${i}">${esc(path.basename(u.fsPath))}</button><span class="caminho">${esc(curto(path.dirname(u.fsPath)))}</span></li>`).join('')}
          <li><button class="link" data-cmd="workbench.action.openRecent">More…</button></li></ul>` : '<div class="vazio">Folders you open show up here.</div>'}
      </section>
    </div>
    <div>
      ${d.aprender.length ? `<section>
        <h2>Learn</h2>
        <ul>${d.aprender.map(([nome, url]) => `<li><a href="#" data-url="${esc(url)}">${esc(nome)}</a></li>`).join('')}</ul>
      </section>` : ''}
      <section>
        <h2>Help</h2>
        <ul>
          <li><button class="link" data-cmd="workbench.action.showCommands"><span class="ico">&#xea65;</span>All commands <span class="caminho">Ctrl+Shift+P</span></button></li>
          <li><a href="#" data-url="https://github.com/RichardSpinola/berthline"><span class="ico">&#xea84;</span>Berthline on GitHub</a></li>
        </ul>
      </section>
    </div>
  </div>
</main>
<footer>
  <label><input type="checkbox" id="inicio" ${inicio ? 'checked' : ''}>Show on startup</label>
  <label><input type="checkbox" id="anima" ${mover ? 'checked' : ''} ${process.env.SUITE_ANIMATIONS === '0' ? 'disabled title="Animations are off in the Hub"' : ''}>Animate the boat</label>
</footer>
<script nonce="${nonce}">
const vscode = acquireVsCodeApi();
document.addEventListener('click', e => {
  const b = e.target.closest('[data-cmd],[data-recent],[data-url]');
  if (!b) return;
  e.preventDefault();
  if (b.dataset.cmd) vscode.postMessage({ type: 'cmd', id: b.dataset.cmd });
  else if (b.dataset.recent) vscode.postMessage({ type: 'recent', i: b.dataset.recent });
  else vscode.postMessage({ type: 'link', url: b.dataset.url });
});
// Boat: one small move a second; stops when hidden, when turned off or with reduced motion
const barco = document.querySelector('.barco'), mar = document.getElementById('mar');
const passos = ['translateY(0) rotate(-1deg)', 'translateY(1px) rotate(0deg)', 'translateY(2px) rotate(1deg)', 'translateY(1px) rotate(0deg)'];
const calmo = matchMedia('(prefers-reduced-motion: reduce)');
let passo = 0;
setInterval(() => {
  if (document.hidden || calmo.matches || !mar.classList.contains('anda')) return;
  passo = (passo + 1) % passos.length;
  barco.style.transform = passos[passo];
}, 1000);
document.getElementById('inicio').onchange = e => vscode.postMessage({ type: 'startup', on: e.target.checked });
document.getElementById('anima').onchange = e => {
  document.getElementById('mar').classList.toggle('anda', e.target.checked);
  vscode.postMessage({ type: 'animation', on: e.target.checked });
};
</script>
</body>
</html>`;
}

function ativar(context) {
    context.subscriptions.push(vscode.commands.registerCommand('berthline.welcome', () => abrir(context)));
    vscode.window.registerWebviewPanelSerializer('berthline.welcome', {
        async deserializeWebviewPanel(p) { p.dispose(); abrir(context, false); },
    });
    const sozinho = !vscode.workspace.workspaceFolders?.length && !vscode.window.visibleTextEditors.length;
    if (sozinho && vscode.workspace.getConfiguration('berthline.welcome').get('onStartup', true)) abrir(context, false);
}

module.exports = { ativar };
