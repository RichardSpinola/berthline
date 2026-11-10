// Drives the Web preview in a built package over CDP: auto-open, CSS swap, reload, inspect, widths, closing.
// Usage: node tests/web_preview_ui.js <package> [dev]
const fs = require('fs'), os = require('os'), path = require('path'), http = require('http');
const { spawn, spawnSync } = require('child_process');
const { SAIDA, dormir, conectar, fechado } = require('./cdp');

const PACOTE = path.resolve(process.argv[2]);
const PORTA = 9337;
const HUB = path.join(PACOTE, process.platform === 'win32' ? 'Hub.exe' : 'Hub');
let falhas = 0;
const passo = (nome, ok, extra = '') => { if (!ok) falhas++; console.log(ok ? 'OK   ' : 'FAIL ', nome, extra); };

const obter = url => new Promise((ok, nao) => http.get(url, r => {
    let b = ''; r.on('data', d => b += d); r.on('end', () => ok({ status: r.statusCode, corpo: b }));
}).on('error', nao));

/** Connects to any CDP target (the page inside the preview, or the toolbar webview). */
async function alvo(filtro, ms = 20000) {
    const fim = Date.now() + ms;
    while (Date.now() < fim) {
        const lista = JSON.parse((await obter(`http://127.0.0.1:${PORTA}/json/list`)).corpo);
        for (const t of lista.filter(filtro)) {
            const w = new WebSocket(t.webSocketDebuggerUrl);
            await new Promise((ok, nao) => { w.onopen = ok; w.onerror = nao; });
            let id = 0; const pend = {};
            w.onmessage = m => { const d = JSON.parse(m.data); pend[d.id]?.(d); };
            const c = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; w.send(JSON.stringify({ id: i, method, params })); });
            const ev = async e => (await c('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })).result?.result?.value;
            return { url: t.url, ev, c, fechar: () => w.close() };
        }
        await dormir(400);
    }
    return null;
}

/** The toolbar lives in a webview, an out-of-process frame: attach to it through the workbench and find the frame with our buttons. */
async function barraDaPrevia() {
    const lista = JSON.parse((await obter(`http://127.0.0.1:${PORTA}/json/list`)).corpo);
    const w = new WebSocket(lista.find(t => t.type === 'page').webSocketDebuggerUrl);
    await new Promise(ok => { w.onopen = ok; });
    let id = 0; const pend = {}; const sessoes = [];
    w.onmessage = m => {
        const d = JSON.parse(m.data);
        if (d.method === 'Target.attachedToTarget') sessoes.push(d.params);
        pend[d.id]?.(d);
    };
    const c = (method, params = {}, sessionId) => new Promise(r => { const i = ++id; pend[i] = r; w.send(JSON.stringify({ id: i, method, params, sessionId })); });
    await c('Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: false, flatten: true });
    for (let i = 0; i < 20; i++) {
        for (const s of sessoes.filter(s => s.targetInfo.url.startsWith('vscode-webview://'))) {
            const quadros = [];
            const juntar = n => { quadros.push(n.frame); (n.childFrames || []).forEach(juntar); };
            const arvore = await c('Page.getFrameTree', {}, s.sessionId);
            if (!arvore.result) continue;
            juntar(arvore.result.frameTree);
            for (const q of quadros) {
                const ctx = (await c('Page.createIsolatedWorld', { frameId: q.id, worldName: 'teste' }, s.sessionId)).result?.executionContextId;
                if (!ctx) continue;
                const ev = async e => (await c('Runtime.evaluate', { expression: e, contextId: ctx, returnByValue: true }, s.sessionId)).result?.result?.value;
                if (await ev(`!!document.getElementById('inspecionar')`)) return { ev };
            }
        }
        await dormir(500);
    }
    return null;
}

async function mudarTema(h, tema) {
    const arquivo = path.join(PACOTE, 'data/web/user/User/settings.json');
    const s = JSON.parse(fs.readFileSync(arquivo, 'utf8'));
    s['workbench.colorTheme'] = tema;
    fs.writeFileSync(arquivo, JSON.stringify(s, null, 4));
}

const ate = async (f, ms = 10000) => { const t = Date.now(); while (Date.now() - t < ms) { try { if (await f()) return true; } catch { } await dormir(250); } return false; };

const HTML = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Preview test</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <h1>Title</h1>
  <section class="box">
    <h2 id="alvo">Target</h2>
  </section>
</body>
</html>
`;

// A project with "npm run dev": a tiny server that prints its URL like Vite does, and stops when asked
const DEV = `const http = require('http');
const s = http.createServer((req, res) => {
  if (req.url === '/stop') { res.end('bye'); process.exit(0); }
  res.writeHead(200, { 'content-type': 'text/html' });
  res.end('<!doctype html><html><body><h1 id="dev">From dev server</h1></body></html>');
});
s.listen(0, '127.0.0.1', () => console.log('\\n  \\x1b[32mLocal\\x1b[0m:   http://localhost:' + s.address().port + '/\\n'));`;

async function modoDev() {
    const temp = fs.realpathSync.native(fs.mkdtempSync(path.join(os.tmpdir(), 'preview-dev-')));
    const pasta = path.join(temp, 'app');
    fs.mkdirSync(path.join(pasta, 'node_modules'), { recursive: true });
    fs.writeFileSync(path.join(pasta, 'index.html'), '<!doctype html><title>x</title><h1>static</h1>');
    fs.writeFileSync(path.join(pasta, 'dev.js'), DEV);
    fs.writeFileSync(path.join(pasta, 'package.json'), JSON.stringify({ name: 'app', private: true, scripts: { dev: 'node dev.js' } }));
    spawnSync(HUB, ['--trust', pasta], { env: { ...process.env, SUITE_ROOT: PACOTE } });
    spawn(HUB, ['--open', 'web', '--port', String(PORTA), pasta], { env: { ...process.env, SUITE_ROOT: PACOTE }, stdio: 'ignore' });
    const h = await conectar(PORTA);
    passo('offers npm run dev', await h.ate(() => h.acha('.notification-toast .monaco-button', 'Run npm run dev'), 30000));
    await h.foto('preview-5-dev-offer');
    await h.clica('.notification-toast .monaco-button', 'Run npm run dev');
    const pagina = await alvo(t => /^http:\/\/127\.0\.0\.1:\d+\//.test(t.url), 30000);
    passo('preview shows the dev server through the proxy', !!pagina && await ate(async () => await pagina.ev(`document.getElementById('dev')?.textContent`) === 'From dev server'));
    passo('dev page gets the client script', !!pagina && await pagina.ev(`!!window.__berthline`));
    passo('npm run dev terminal', /npm run dev/.test(await h.ev(`[...document.querySelectorAll('.terminal-tab, .single-terminal-tab, .tabs-list .monaco-list-row, .pane-header')].map(e=>e.innerText).join(' ')`)));
    await dormir(800);
    await h.foto('preview-6-dev');
    const destino = await pagina.ev('location.href');
    const dev = /Local.*?(http:\/\/localhost:\d+)/s.exec(await h.terminal() || '')?.[1];
    if (dev) await obter(dev.replace('localhost', '127.0.0.1') + '/stop').catch(() => {});
    const barra = await barraDaPrevia();
    passo('stopped dev server shows a message', !!barra && await ate(async () => /dev server stopped/.test(await barra.ev(`document.getElementById('aviso').style.display !== 'none' && document.getElementById('avisoTexto').textContent`) || '')),
        `dev ${dev} page ${destino}`);
    await h.foto('preview-7-dev-stopped');
    await h.fechar();
    await fechado(PORTA);
    try { fs.rmSync(temp, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 }); } catch { }
    console.log(falhas ? `${falhas} failed` : 'all passed');
    process.exit(falhas ? 1 : 0);
}

(async () => {
    fs.mkdirSync(SAIDA, { recursive: true });
    if (process.argv[3] === 'dev') return modoDev();
    const temp = fs.realpathSync.native(fs.mkdtempSync(path.join(os.tmpdir(), 'preview-ui-')));
    const pasta = path.join(temp, 'site');
    fs.mkdirSync(pasta);
    fs.writeFileSync(path.join(pasta, 'index.html'), HTML);
    fs.writeFileSync(path.join(pasta, 'style.css'), 'h1 { color: rgb(200, 0, 0); }\n');
    spawnSync(HUB, ['--trust', pasta], { env: { ...process.env, SUITE_ROOT: PACOTE } });
    spawn(HUB, ['--open', 'web', '--port', String(PORTA), pasta], { env: { ...process.env, SUITE_ROOT: PACOTE }, stdio: 'ignore' });
    const h = await conectar(PORTA);

    const pagina = await alvo(t => /^http:\/\/127\.0\.0\.1:\d+\//.test(t.url), 40000);
    passo('preview opens by itself beside the editor', !!pagina, pagina?.url);
    if (!pagina) throw new Error('no preview page');
    const base = pagina.url.replace(/[^/]*$/, '');
    passo('lines marked for inspect', await pagina.ev(`document.querySelector('#alvo').dataset.bl`) === '10');

    await pagina.ev('window.__marca = 1');
    fs.writeFileSync(path.join(pasta, 'style.css'), 'h1 { color: rgb(0, 120, 0); }\n');
    passo('CSS swaps without reload', await ate(async () =>
        await pagina.ev(`getComputedStyle(document.querySelector('h1')).color`) === 'rgb(0, 120, 0)' && await pagina.ev('window.__marca') === 1));

    fs.writeFileSync(path.join(pasta, 'index.html'), HTML.replace('Title', 'Changed'));
    passo('HTML save reloads', await ate(async () => await pagina.ev(`document.querySelector('h1')?.textContent`) === 'Changed' && await pagina.ev('window.__marca') === undefined));
    await dormir(800);
    await h.foto('preview-1-dark');

    const toolbar = await barraDaPrevia();
    passo('toolbar reachable', !!toolbar);
    if (toolbar) {
        await toolbar.ev(`document.querySelector('.larguras button[data-w="390"]').click()`);
        passo('phone width', await ate(async () => (await toolbar.ev(`document.getElementById('moldura').style.width`)) === '390px'));
        await dormir(500);
        await h.foto('preview-2-390');
        await toolbar.ev(`document.querySelector('.larguras button[data-w="0"]').click()`);

        await toolbar.ev(`document.getElementById('inspecionar').click()`);
        await dormir(400);
        await pagina.ev(`document.getElementById('alvo').dispatchEvent(new MouseEvent('mousemove', { bubbles: true }))`);
        await dormir(300);
        await h.foto('preview-3-inspect');
        await pagina.ev(`document.getElementById('alvo').click()`);
        passo('inspect click opens the HTML line', await ate(async () =>
            /Ln 11,/.test(await h.ev(`[...document.querySelectorAll('.statusbar-item')].map(e=>e.innerText).join(' ')`)), 5000),
            await h.ev(`[...document.querySelectorAll('.statusbar-item')].map(e=>e.innerText).join(' | ')`));
        // The other way: the cursor on <h1> in the code outlines the h1 in the page
        for (let i = 0; i < 2; i++) await h.tecla('ArrowUp', 'ArrowUp', 38);
        passo('cursor in code outlines the element', await ate(async () => await pagina.ev(`(() => {
            const c = [...document.documentElement.children].find(e => e.tagName === 'DIV' && e.style.position === 'fixed');
            const h1 = document.querySelector('h1').getBoundingClientRect();
            return !!c && c.style.display === 'block' && Math.abs(parseFloat(c.style.top) - h1.top) < 1;
        })()`), 5000));
        await toolbar.ev(`document.getElementById('inspecionar').click()`);
        await h.c('Runtime.evaluate', { expression: '1' });
    }
    await mudarTema(h, 'Default Light Modern');
    await dormir(1500);
    await h.foto('preview-4-light');
    await mudarTema(h, 'Default Dark Modern');

    // Insert Block from the Command Palette, with the cursor on a line of <body>
    await h.tecla('End', 'End', 35);
    await h.tecla('Enter', 'Enter', 13);
    await h.tecla('F1', 'F1', 112);
    await dormir(600);
    await h.escreve('Web: Insert Block');
    await dormir(600);
    await h.tecla('Enter', 'Enter', 13);
    await dormir(800);
    await h.escreve('Footer');
    await dormir(400);
    await h.foto('preview-8-blocks');
    await h.tecla('Enter', 'Enter', 13);
    passo('block CSS appended to style.css', await ate(() => /\/\* Block: Footer \*\/\n\.site-footer \{/.test(fs.readFileSync(path.join(pasta, 'style.css'), 'utf8')), 5000));
    passo('block markup in the page', await ate(async () => !!await pagina.ev(`document.querySelector('footer.site-footer')`), 8000));
    passo('server answers', (await obter(base + 'style.css')).status === 200);
    const x = await h.ev(`(() => { const t = [...document.querySelectorAll('.tab')].find(e => /Preview/.test(e.innerText)); const b = t && t.querySelector('.tab-actions .action-label').getBoundingClientRect(); return b && { x: b.x + b.width / 2, y: b.y + b.height / 2 }; })()`);
    if (x) await h.xy(x.x, x.y);
    await dormir(1500);
    const vivo = await obter(base + 'style.css').then(() => true, () => false);
    passo('server stops when the preview closes', !vivo);

    await h.fechar();
    await fechado(PORTA);
    try { fs.rmSync(temp, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 }); } catch { }
    console.log(falhas ? `${falhas} failed` : 'all passed');
    process.exit(falhas ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
