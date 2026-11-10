// Live preview: an editor tab (webview) showing the page from a small server in the extension host.
const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawn } = require('child_process');
const { iniciar, urlDoTexto } = require('./servidor');
const { linhaDoElemento } = require('./html');

const JANELAS = process.platform === 'win32';
const IGNORAR = /[\\/](node_modules|\.git)[\\/]/;
let estado = null; // { painel, servidor, raiz, alvo, inspecionando, ouvintes }
const devs = new Map(); // raiz -> { url, filho, terminal }

function pastaDoProjeto(arquivo) {
    const uri = arquivo ?? vscode.window.activeTextEditor?.document.uri;
    const pasta = uri && vscode.workspace.getWorkspaceFolder(uri);
    if (pasta) return pasta.uri.fsPath;
    if (uri?.scheme === 'file') return path.dirname(uri.fsPath);
    return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

function scriptDev(raiz) {
    try { return JSON.parse(fs.readFileSync(path.join(raiz, 'package.json'), 'utf8')).scripts?.dev ? 'dev' : null; } catch { return null; }
}

function caminhoWeb(raiz, arquivo) {
    if (!arquivo || arquivo.scheme !== 'file' || !/\.html?$/i.test(arquivo.fsPath)) return '/';
    const rel = path.relative(raiz, arquivo.fsPath);
    if (rel.startsWith('..') || path.isAbsolute(rel)) return '/';
    return '/' + rel.split(path.sep).map(encodeURIComponent).join('/');
}

/** Opens the preview beside the editor, or shows the given page in the open one. */
async function abrir(context, { arquivo, focar = false } = {}) {
    const raiz = pastaDoProjeto(arquivo);
    if (!raiz) return vscode.window.showInformationMessage('Open a folder to preview it.');
    if (estado && estado.raiz === raiz) {
        estado.painel.reveal(undefined, !focar);
        if (estado.servidor && !estado.alvo) postar({ type: 'load', url: estado.servidor.url + caminhoWeb(raiz, arquivo).slice(1) });
        return;
    }
    estado?.painel.dispose();
    const painel = vscode.window.createWebviewPanel('berthline.preview', 'Preview', { viewColumn: vscode.ViewColumn.Beside, preserveFocus: !focar }, {
        enableScripts: true,
        localResourceRoots: [vscode.Uri.file(path.join(vscode.env.appRoot, 'out', 'media'))],
    });
    painel.iconPath = vscode.Uri.file(path.join(context.extensionPath, 'media', 'preview.svg'));
    const atual = estado = { painel, raiz, inspecionando: false, ouvintes: [] };
    painel.webview.html = pagina(painel.webview);
    painel.webview.onDidReceiveMessage(m => aoReceber(atual, m), null, atual.ouvintes);
    painel.onDidDispose(() => fechar(atual), null, atual.ouvintes);
    await vscode.commands.executeCommand('setContext', 'web.previewOpen', true);

    let usarDev = false;
    if (scriptDev(raiz)) {
        const chave = `web.dev:${raiz}`;
        let escolha = context.workspaceState.get(chave);
        if (!escolha) {
            escolha = await vscode.window.showInformationMessage(
                'This project has a dev script. Preview it through "npm run dev"?', 'Run npm run dev', 'Serve the files');
            if (escolha) await context.workspaceState.update(chave, escolha);
        }
        usarDev = escolha === 'Run npm run dev';
    }
    if (atual !== estado) return;
    try {
        if (usarDev) {
            postar({ type: 'status', text: 'Starting npm run dev…' });
            atual.alvo = await rodarDev(raiz);
            if (atual !== estado) return;
            atual.servidor = await iniciar({ alvo: atual.alvo });
            postar({ type: 'load', url: atual.servidor.url, dev: atual.alvo });
        } else {
            atual.servidor = await iniciar({ raiz });
            postar({ type: 'load', url: atual.servidor.url + caminhoWeb(raiz, arquivo).slice(1) });
            vigiar(atual);
        }
    } catch (e) {
        if (atual === estado) postar({ type: 'status', text: e.message, erro: true, acao: usarDev ? 'Try again' : null });
    }
    if (atual !== estado) atual.servidor?.fechar();
    else atual.ouvintes.push(vscode.window.onDidChangeTextEditorSelection(e => aoMoverCursor(atual, e)));
}

function postar(msg) {
    estado?.painel.webview.postMessage(msg);
}

/** Saved files reload the page; stylesheets swap in place. */
function vigiar(atual) {
    const vigia = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(atual.raiz, '**/*'));
    let pendentes = [];
    let espera;
    const mudou = uri => {
        if (IGNORAR.test(uri.fsPath)) return;
        pendentes.push(uri.fsPath);
        clearTimeout(espera);
        espera = setTimeout(() => {
            const soCss = pendentes.every(f => f.toLowerCase().endsWith('.css'));
            pendentes = [];
            atual.servidor?.enviar({ type: soCss ? 'css' : 'reload' });
        }, 120);
    };
    vigia.onDidChange(mudou);
    vigia.onDidCreate(mudou);
    vigia.onDidDelete(mudou);
    atual.ouvintes.push(vigia, { dispose: () => clearTimeout(espera) });
}

let esperaCursor;
function aoMoverCursor(atual, e) {
    const doc = e.textEditor.document;
    if (!atual.inspecionando || doc.languageId !== 'html' || doc.uri.scheme !== 'file') return;
    clearTimeout(esperaCursor);
    esperaCursor = setTimeout(() => {
        const linha = linhaDoElemento(doc.getText(), doc.offsetAt(e.selections[0].active));
        postar({ type: 'highlight', caminho: caminhoWeb(atual.raiz, doc.uri), linha });
    }, 100);
}

async function aoReceber(atual, m) {
    if (atual !== estado) return;
    if (m.type === 'pick') return irParaFonte(atual, m);
    if (m.type === 'pick-none') return vscode.window.setStatusBarMessage('No source line for that element', 3000);
    if (m.type === 'inspect') {
        atual.inspecionando = m.on;
        return vscode.commands.executeCommand('setContext', 'web.inspecting', m.on);
    }
    if (m.type === 'external') {
        // A dev server opens at its own address, so its hot reload talks to it directly
        const url = atual.alvo && m.url.startsWith(atual.servidor?.url) ? new URL(m.url.slice(atual.servidor.url.length), atual.alvo).href : m.url;
        return vscode.env.openExternal(vscode.Uri.parse(url));
    }
    if (m.type === 'window') {
        atual.painel.reveal(undefined, false);
        return vscode.commands.executeCommand('workbench.action.moveEditorToNewWindow');
    }
    if (m.type === 'retry') {
        const arquivo = vscode.window.activeTextEditor?.document.uri;
        atual.painel.dispose();
        return abrir(contexto, { arquivo });
    }
}

async function irParaFonte(atual, m) {
    let arquivo;
    if (m.caminho !== undefined) {
        let rel = decodeURIComponent(m.caminho);
        if (rel.endsWith('/')) rel += 'index.html';
        arquivo = path.join(atual.raiz, rel);
        if (!arquivo.startsWith(atual.raiz)) return;
    } else {
        arquivo = path.resolve(atual.raiz, String(m.arquivo).replace(/^\/@fs/, ''));
    }
    if (!fs.existsSync(arquivo)) return vscode.window.setStatusBarMessage(`Source not found: ${path.basename(arquivo)}`, 3000);
    const doc = await vscode.workspace.openTextDocument(arquivo);
    const coluna = vscode.window.visibleTextEditors.find(e => e.document.uri.scheme === 'file')?.viewColumn ?? vscode.ViewColumn.One;
    const linha = Math.max(0, Math.min(Number(m.linha) || 0, doc.lineCount - 1));
    const texto = doc.lineAt(linha).text;
    const pos = new vscode.Position(linha, texto.length - texto.trimStart().length);
    await vscode.window.showTextDocument(doc, { viewColumn: coluna, selection: new vscode.Range(pos, pos) });
}

function fechar(atual) {
    for (const o of atual.ouvintes) o.dispose();
    atual.servidor?.fechar();
    if (estado === atual) {
        estado = null;
        vscode.commands.executeCommand('setContext', 'web.previewOpen', false);
        vscode.commands.executeCommand('setContext', 'web.inspecting', false);
    }
}

/** Runs `npm run dev` in a terminal tab and resolves with the first local URL it prints. */
function rodarDev(raiz) {
    const vivo = devs.get(raiz);
    if (vivo?.url) return Promise.resolve(vivo.url);
    return new Promise((ok, nao) => {
        const escrever = new vscode.EventEmitter();
        const terminou = new vscode.EventEmitter();
        const node = process.env.SUITE_NODE ? path.dirname(process.env.SUITE_NODE) : null;
        const env = { ...process.env };
        delete env.ELECTRON_RUN_AS_NODE;
        env.npm_config_update_notifier = 'false';
        const chavePath = Object.keys(env).find(k => k.toUpperCase() === 'PATH') ?? 'PATH';
        if (node) env[chavePath] = node + path.delimiter + (env[chavePath] ?? '');
        const instalar = !fs.existsSync(path.join(raiz, 'node_modules'));
        const comando = instalar ? 'npm install && npm run dev' : 'npm run dev';
        const registro = { url: null, filho: null };
        let saida = '';
        const limite = setTimeout(() => nao(new Error('npm run dev printed no local address in 90 seconds. See its terminal.')), 90000);
        const pty = {
            onDidWrite: escrever.event,
            onDidClose: terminou.event,
            open() {
                escrever.fire(`\x1b[2m> ${comando}\x1b[0m\r\n`);
                const filho = registro.filho = spawn(comando, { cwd: raiz, env, shell: true, detached: !JANELAS, windowsHide: true });
                const ler = d => {
                    const t = d.toString();
                    escrever.fire(t.replace(/\r?\n/g, '\r\n'));
                    if (registro.url) return;
                    saida = (saida + t).slice(-4000);
                    const url = urlDoTexto(saida);
                    if (url) { registro.url = url; clearTimeout(limite); ok(url); }
                };
                filho.stdout.on('data', ler);
                filho.stderr.on('data', ler);
                filho.on('error', e => escrever.fire(`${e.message}\r\n`));
                filho.on('exit', codigo => {
                    escrever.fire(`\r\n\x1b[2mnpm run dev ended (exit code ${codigo ?? 'none'})\x1b[0m\r\n`);
                    devs.delete(raiz);
                    clearTimeout(limite);
                    nao(new Error('npm run dev stopped before printing an address. See its terminal.'));
                    if (estado?.alvo && estado.raiz === raiz) postar({ type: 'status', text: 'The dev server stopped.', erro: true, acao: 'Start again' });
                });
            },
            close() { matar(registro.filho); },
            handleInput(d) {
                if (d === '\x03') matar(registro.filho);
                else registro.filho?.stdin.write(d);
            },
        };
        registro.terminal = vscode.window.createTerminal({ name: 'npm run dev', pty, iconPath: new vscode.ThemeIcon('server-process') });
        registro.terminal.show(true);
        devs.set(raiz, registro);
    });
}

function matar(filho) {
    if (!filho || filho.exitCode !== null) return;
    if (JANELAS) spawn('taskkill', ['/pid', String(filho.pid), '/T', '/F'], { windowsHide: true });
    else try { process.kill(-filho.pid, 'SIGTERM'); } catch { filho.kill(); }
}

function pararTudo() {
    for (const r of devs.values()) matar(r.filho);
    devs.clear();
    estado?.painel.dispose();
}

function pagina(webview) {
    const nonce = crypto.randomBytes(16).toString('base64');
    const fonte = webview.asWebviewUri(vscode.Uri.file(path.join(vscode.env.appRoot, 'out', 'media', 'codicon.ttf')));
    return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; frame-src http://127.0.0.1:*; font-src ${webview.cspSource}; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>
@font-face { font-family: codicon; src: url("${fonte}") format("truetype"); }
html, body { height: 100%; margin: 0; padding: 0; overflow: hidden; }
body { display: flex; flex-direction: column; color: var(--vscode-foreground); background: var(--vscode-editor-background);
  font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); }
.barra { display: flex; align-items: center; gap: 2px; height: 34px; padding: 0 6px; flex: none;
  border-bottom: 1px solid var(--vscode-editorGroupHeader-tabsBorder, var(--vscode-panel-border, transparent)); }
.ico { font: normal normal normal 16px/1 codicon; display: inline-block; }
button.acao { display: flex; align-items: center; justify-content: center; width: 24px; height: 24px; padding: 0;
  border: 1px solid transparent; border-radius: 5px; color: var(--vscode-icon-foreground); background: none; cursor: pointer; }
button.acao:hover { background: var(--vscode-toolbar-hoverBackground); }
button.acao:focus-visible, .larguras button:focus-visible { outline: 1px solid var(--vscode-focusBorder); outline-offset: -1px; }
button.acao[aria-pressed="true"] { color: var(--vscode-inputOption-activeForeground); background: var(--vscode-inputOption-activeBackground);
  border-color: var(--vscode-inputOption-activeBorder, transparent); }
input.url { flex: 1; min-width: 60px; height: 24px; box-sizing: border-box; margin: 0 4px; padding: 0 6px;
  color: var(--vscode-input-foreground); background: var(--vscode-input-background);
  border: 1px solid var(--vscode-input-border, transparent); border-radius: 2px; font: inherit; }
input.url:focus { outline: 1px solid var(--vscode-focusBorder); outline-offset: -1px; }
.larguras { display: flex; gap: 1px; margin: 0 4px; }
.larguras button { height: 22px; padding: 0 6px; border: 1px solid transparent; border-radius: 3px; background: none; cursor: pointer;
  color: var(--vscode-descriptionForeground); font: inherit; font-size: 11px; font-variant-numeric: tabular-nums; }
.larguras button:hover { background: var(--vscode-toolbar-hoverBackground); }
.larguras button[aria-pressed="true"] { color: var(--vscode-inputOption-activeForeground); background: var(--vscode-inputOption-activeBackground);
  border-color: var(--vscode-inputOption-activeBorder, transparent); }
.sep { width: 1px; height: 16px; margin: 0 4px; background: var(--vscode-editorGroupHeader-tabsBorder, var(--vscode-panel-border)); opacity: .8; }
.palco { position: relative; flex: 1; overflow: hidden; }
.palco.medida { background: var(--vscode-editorGroup-emptyBackground, var(--vscode-sideBar-background)); }
.moldura { position: absolute; top: 0; left: 0; height: 100%; transform-origin: 0 0; }
iframe { display: block; width: 100%; height: 100%; border: 0; background: #fff; }
.palco.medida .moldura { box-shadow: 0 0 0 1px var(--vscode-panel-border, rgba(128,128,128,.35)); }
.escala { position: absolute; right: 8px; bottom: 6px; padding: 1px 6px; border-radius: 3px; font-size: 11px;
  color: var(--vscode-descriptionForeground); background: var(--vscode-editorWidget-background); display: none; }
.aviso { position: absolute; inset: 0; display: none; flex-direction: column; align-items: center; justify-content: center; gap: 12px;
  padding: 24px; text-align: center; color: var(--vscode-descriptionForeground); background: var(--vscode-editor-background); }
.aviso.erro .texto { color: var(--vscode-errorForeground); }
.aviso button { padding: 4px 12px; border: 1px solid var(--vscode-button-border, transparent); border-radius: 2px; cursor: pointer;
  color: var(--vscode-button-foreground); background: var(--vscode-button-background); font: inherit; }
.aviso button:hover { background: var(--vscode-button-hoverBackground); }
@media (max-width: 420px) { .larguras { display: none; } }
</style>
</head>
<body>
<div class="barra" role="toolbar" aria-label="Preview">
  <button class="acao" id="recarregar" title="Reload"><span class="ico">&#xeb37;</span></button>
  <input class="url" id="url" spellcheck="false" aria-label="Address">
  <div class="larguras" role="group" aria-label="Width">
    <button data-w="0" aria-pressed="true" title="Fit the editor">Fit</button>
    <button data-w="390" aria-pressed="false" title="Phone, 390 px">390</button>
    <button data-w="768" aria-pressed="false" title="Tablet, 768 px">768</button>
    <button data-w="1280" aria-pressed="false" title="Laptop, 1280 px">1280</button>
  </div>
  <div class="sep"></div>
  <button class="acao" id="inspecionar" aria-pressed="false" title="Inspect: click an element to open its line (Esc to stop)"><span class="ico">&#xebd1;</span></button>
  <button class="acao" id="janela" title="Move to New Window"><span class="ico">&#xeb23;</span></button>
  <button class="acao" id="externo" title="Open in Browser"><span class="ico">&#xeb14;</span></button>
</div>
<div class="palco" id="palco">
  <div class="moldura" id="moldura"><iframe id="quadro" title="Page preview"></iframe></div>
  <div class="escala" id="escala"></div>
  <div class="aviso" id="aviso"><div class="texto" id="avisoTexto"></div><button id="avisoAcao"></button></div>
</div>
<script nonce="${nonce}">
const vscode = acquireVsCodeApi();
const $ = id => document.getElementById(id);
const quadro = $('quadro'), palco = $('palco'), moldura = $('moldura'), url = $('url');
let st = vscode.getState() || { url: '', largura: 0, inspecionar: false, status: null };
const salvar = () => vscode.setState(st);

function medir() {
  const w = st.largura, livre = palco.clientWidth, alto = palco.clientHeight;
  palco.classList.toggle('medida', !!w);
  if (!w) { Object.assign(moldura.style, { width: '100%', height: '100%', left: '0px', transform: '' }); $('escala').style.display = 'none'; return; }
  const k = Math.min(1, livre / w);
  Object.assign(moldura.style, { width: w + 'px', height: (alto / k) + 'px', left: Math.max(0, (livre - w * k) / 2) + 'px', transform: k < 1 ? 'scale(' + k + ')' : '' });
  $('escala').textContent = w + ' px' + (k < 1 ? ' · ' + Math.round(k * 100) + '%' : '');
  $('escala').style.display = 'block';
}
new ResizeObserver(medir).observe(palco);

function marcarLargura() {
  for (const b of document.querySelectorAll('.larguras button')) b.setAttribute('aria-pressed', String(Number(b.dataset.w) === st.largura));
  medir();
}
function aviso(s) {
  st.status = s; salvar();
  $('aviso').style.display = s ? 'flex' : 'none';
  if (!s) return;
  $('aviso').classList.toggle('erro', !!s.erro);
  $('avisoTexto').textContent = s.text;
  $('avisoAcao').style.display = s.acao ? '' : 'none';
  $('avisoAcao').textContent = s.acao || '';
}
function carregar(u) {
  st.url = u; salvar();
  url.value = u;
  aviso(null);
  quadro.src = u;
}
function paraPagina(msg) { quadro.contentWindow && quadro.contentWindow.postMessage({ berthline: true, ...msg }, '*'); }
function inspecionar(on) {
  st.inspecionar = on; salvar();
  $('inspecionar').setAttribute('aria-pressed', String(on));
  paraPagina({ type: 'inspect', on });
  vscode.postMessage({ type: 'inspect', on });
}

$('recarregar').onclick = () => { if (st.url) quadro.src = st.url; };
$('externo').onclick = () => st.url && vscode.postMessage({ type: 'external', url: st.url });
$('janela').onclick = () => vscode.postMessage({ type: 'window' });
$('inspecionar').onclick = () => inspecionar(!st.inspecionar);
$('avisoAcao').onclick = () => vscode.postMessage({ type: 'retry' });
for (const b of document.querySelectorAll('.larguras button')) b.onclick = () => { st.largura = Number(b.dataset.w); salvar(); marcarLargura(); };
url.addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    let v = url.value.trim();
    if (!v) return;
    if (v.startsWith('/')) v = new URL(v, st.url || 'http://127.0.0.1/').href;
    else if (!/^https?:\\/\\//.test(v)) v = 'http://' + v;
    carregar(v);
    quadro.focus();
  } else if (e.key === 'Escape') { url.value = st.url; quadro.focus(); }
});
url.addEventListener('focus', () => url.select());

window.addEventListener('message', e => {
  const m = e.data;
  if (e.source === quadro.contentWindow) {
    if (!m || !m.berthline) return;
    if (m.type === 'ready') {
      if (document.activeElement !== url) url.value = m.url;
      st.url = m.url; salvar();
      if (st.inspecionar) paraPagina({ type: 'inspect', on: true });
    } else if (m.type === 'inspect-off') inspecionar(false);
    else vscode.postMessage(m);
    return;
  }
  if (m.type === 'load') carregar(m.url);
  else if (m.type === 'status') aviso(m);
  else if (m.type === 'highlight') paraPagina(m);
});

marcarLargura();
$('inspecionar').setAttribute('aria-pressed', String(st.inspecionar));
if (st.status) aviso(st.status);
else if (st.url) carregar(st.url);
if (st.inspecionar) vscode.postMessage({ type: 'inspect', on: true });
</script>
</body>
</html>`;
}

let contexto;
function ativar(context) {
    contexto = context;
    context.subscriptions.push({ dispose: pararTudo });
    vscode.window.registerWebviewPanelSerializer?.('berthline.preview', {
        // A preview left open last time comes back with a fresh server
        async deserializeWebviewPanel(painel) {
            painel.dispose();
            if (!estado) abrir(context);
        },
    });
    const raiz = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const auto = vscode.workspace.getConfiguration('web.preview').get('openOnStartup', true);
    if (auto && raiz && fs.existsSync(path.join(raiz, 'index.html')) && !estado) {
        const indice = vscode.Uri.file(path.join(raiz, 'index.html'));
        // With nothing open yet, index.html goes on the left so the preview really sits beside it
        const editor = vscode.window.activeTextEditor
            ? Promise.resolve()
            : vscode.window.showTextDocument(indice, { viewColumn: vscode.ViewColumn.One, preview: false }).then(() => {}, () => {});
        editor.then(() => abrir(context, { arquivo: indice }));
    }
}

module.exports = { ativar, abrir, pararTudo, estado: () => estado };
