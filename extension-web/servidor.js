// Preview server inside the extension host: serves a folder, or proxies a dev server, on 127.0.0.1.
// Pages get a small client script for reload, CSS swap and inspect. No vscode import, so tests run it in plain Node.
const http = require('http');
const net = require('net');
const fs = require('fs');
const path = require('path');
const { marcar, injetarScript } = require('./html');

const PREFIXO = '/__berthline/';
const TIPOS = {
    '.html': 'text/html; charset=utf-8', '.htm': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
    '.webp': 'image/webp', '.avif': 'image/avif', '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2',
    '.ttf': 'font/ttf', '.otf': 'font/otf', '.mp4': 'video/mp4', '.webm': 'video/webm', '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav', '.txt': 'text/plain; charset=utf-8', '.xml': 'application/xml', '.wasm': 'application/wasm',
    '.map': 'application/json', '.pdf': 'application/pdf',
};
const CLIENTE = fs.readFileSync(path.join(__dirname, 'cliente.js'), 'utf8');
const TAG = `<script src="${PREFIXO}client.js"></script>`;

/**
 * Starts the server. `raiz` is the folder to serve; `alvo` (a URL) switches to proxy mode.
 * `depuracao()` gives the editor's debugging port, so DevTools for the preview can be served from here (see below).
 * Resolves to { porta, url, enviar(msg), fechar() }.
 */
function iniciar({ raiz, alvo, depuracao = () => null }) {
    const clientes = new Set();
    const conexoes = new Set();
    const destino = alvo ? new URL(alvo) : null;

    const servidor = http.createServer((req, res) => {
        const url = new URL(req.url, 'http://x');
        if (url.pathname === `${PREFIXO}client.js`) {
            res.writeHead(200, { 'content-type': TIPOS['.js'], 'cache-control': 'no-store' });
            return res.end(CLIENTE);
        }
        if (url.pathname === `${PREFIXO}events`) {
            res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store', connection: 'keep-alive' });
            res.write(': ok\n\n');
            clientes.add(res);
            req.on('close', () => clientes.delete(res));
            return;
        }
        if (url.pathname.startsWith(`${PREFIXO}devtools/`)) {
            // The DevTools front end, as the editor's debugging port serves it
            const porta = depuracao();
            if (!porta) return erro(res, 404, 'DevTools needs the editor debugging port');
            const caminho = '/devtools/' + url.pathname.slice(`${PREFIXO}devtools/`.length) + url.search;
            return repassar(req, res, new URL(`http://127.0.0.1:${porta}`), caminho, false);
        }
        if (destino) return repassar(req, res, destino);
        servirArquivo(raiz, decodeURIComponent(url.pathname), res);
    });
    servidor.on('connection', s => { conexoes.add(s); s.on('close', () => conexoes.delete(s)); });
    // WebSocket upgrades (Vite and others use them for hot reload) go straight to the dev server
    servidor.on('upgrade', (req, socket, cabeca) => {
        if (req.url.startsWith(`${PREFIXO}devtools-ws/page/`)) return devtoolsWs(req, socket, cabeca);
        if (!destino) return socket.destroy();
        const outro = net.connect(Number(destino.port) || 80, semColchetes(destino.hostname), () => {
            const linhas = [`${req.method} ${req.url} HTTP/${req.httpVersion}`];
            for (let i = 0; i < req.rawHeaders.length; i += 2) {
                const nome = req.rawHeaders[i];
                linhas.push(`${nome}: ${nome.toLowerCase() === 'host' ? destino.host : req.rawHeaders[i + 1]}`);
            }
            outro.write(linhas.join('\r\n') + '\r\n\r\n');
            if (cabeca?.length) outro.write(cabeca);
            outro.pipe(socket).pipe(outro);
        });
        conexoes.add(outro);
        outro.on('close', () => conexoes.delete(outro));
        // Either side closing ends the other, so no half-open socket keeps a server alive
        outro.on('error', () => socket.destroy());
        outro.on('close', () => socket.destroy());
        socket.on('error', () => outro.destroy());
        socket.on('close', () => outro.destroy());
    });

    /**
     * DevTools talks to the page over the editor's debugging port. Chromium refuses that socket from a web page
     * (Origin check), and allowing every origin would let any site drive the editor. So the socket goes through here:
     * only from DevTools served by this server, only to a frame this server shows, and with no Origin header.
     */
    async function devtoolsWs(req, socket, cabeca) {
        const porta = depuracao();
        const id = req.url.slice(`${PREFIXO}devtools-ws/page/`.length);
        const origem = req.headers.origin;
        const meu = `http://127.0.0.1:${servidor.address().port}`;
        let valido = false;
        if (porta && origem === meu && /^[A-F0-9]+$/i.test(id)) {
            try {
                const lista = await (await fetch(`http://127.0.0.1:${porta}/json/list`)).json();
                valido = lista.some(a => a.id === id && a.url.startsWith(`${meu}/`));
            } catch { /* port gone */ }
        }
        if (!valido) {
            socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');
            return;
        }
        const outro = net.connect(porta, '127.0.0.1', () => {
            const linhas = [`GET /devtools/page/${id} HTTP/1.1`];
            for (let i = 0; i < req.rawHeaders.length; i += 2) {
                const nome = req.rawHeaders[i].toLowerCase();
                if (nome === 'origin' || nome === 'host') continue;
                linhas.push(`${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}`);
            }
            linhas.push(`Host: 127.0.0.1:${porta}`);
            outro.write(linhas.join('\r\n') + '\r\n\r\n');
            if (cabeca?.length) outro.write(cabeca);
            outro.pipe(socket).pipe(outro);
        });
        conexoes.add(outro);
        outro.on('close', () => { conexoes.delete(outro); socket.destroy(); });
        outro.on('error', () => socket.destroy());
        socket.on('close', () => outro.destroy());
        socket.on('error', () => outro.destroy());
    }

    const pulso = setInterval(() => { for (const c of clientes) c.write(': ping\n\n'); }, 25000);
    pulso.unref?.();

    return new Promise((ok, nao) => {
        servidor.once('error', nao);
        servidor.listen(0, '127.0.0.1', () => {
            const porta = servidor.address().port;
            ok({
                porta,
                url: `http://127.0.0.1:${porta}/`,
                enviar(msg) { for (const c of clientes) c.write(`data: ${JSON.stringify(msg)}\n\n`); },
                fechar() {
                    clearInterval(pulso);
                    for (const c of clientes) c.end();
                    for (const s of conexoes) s.destroy();
                    return new Promise(f => servidor.close(() => f()));
                },
            });
        });
    });
}

function servirArquivo(raiz, caminho, res) {
    const base = path.resolve(raiz);
    let arquivo = path.resolve(base, '.' + path.posix.normalize('/' + caminho));
    if (arquivo !== base && !arquivo.startsWith(base + path.sep)) return erro(res, 403, 'Outside the project folder');
    fs.stat(arquivo, (e, info) => {
        if (!e && info.isDirectory()) {
            if (!caminho.endsWith('/')) {
                res.writeHead(301, { location: caminho + '/' });
                return res.end();
            }
            arquivo = path.join(arquivo, 'index.html');
        }
        fs.readFile(arquivo, (e2, dados) => {
            if (e2) return erro(res, 404, `Not found: ${caminho}`);
            const ext = path.extname(arquivo).toLowerCase();
            const tipo = TIPOS[ext] ?? 'application/octet-stream';
            if (ext === '.html' || ext === '.htm') {
                const texto = injetarScript(marcar(dados.toString('utf8')), TAG);
                res.writeHead(200, { 'content-type': tipo, 'cache-control': 'no-store' });
                return res.end(texto);
            }
            res.writeHead(200, { 'content-type': tipo, 'cache-control': 'no-store', 'content-length': dados.length });
            res.end(dados);
        });
    });
}

function erro(res, codigo, texto) {
    const pagina = `<!doctype html><meta charset="utf-8"><title>${codigo}</title>
<body style="font:13px system-ui,sans-serif;color:#888;padding:24px">${texto.replace(/[<&]/g, c => ({ '<': '&lt;', '&': '&amp;' })[c])}${TAG}`;
    res.writeHead(codigo, { 'content-type': TIPOS['.html'], 'cache-control': 'no-store' });
    res.end(pagina);
}

function repassar(req, res, destino, caminho = req.url, injetar = true) {
    const cabecalhos = { ...req.headers, host: destino.host, 'accept-encoding': 'identity' };
    const pedido = http.request({ hostname: semColchetes(destino.hostname), port: destino.port || 80, path: caminho, method: req.method, headers: cabecalhos }, resp => {
        const tipo = String(resp.headers['content-type'] ?? '');
        if (!injetar || !tipo.includes('text/html')) {
            res.writeHead(resp.statusCode, resp.headers);
            return resp.pipe(res);
        }
        const partes = [];
        resp.on('data', p => partes.push(p));
        resp.on('end', () => {
            const texto = injetarScript(Buffer.concat(partes).toString('utf8'), TAG);
            const cab = { ...resp.headers, 'cache-control': 'no-store' };
            delete cab['content-length'];
            delete cab['content-encoding'];
            delete cab['transfer-encoding'];
            res.writeHead(resp.statusCode, cab);
            res.end(texto);
        });
    });
    pedido.on('error', e => erro(res, 502, `The dev server did not answer (${e.code ?? e.message}).`));
    req.pipe(pedido);
}

const semColchetes = h => h.replace(/^\[|\]$/g, '');

/** Finds the first local URL a dev server prints, ignoring colour codes. */
function urlDoTexto(texto) {
    const limpo = texto.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '');
    const m = /https?:\/\/(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0):\d+[^\s'"]*/.exec(limpo);
    return m ? m[0].replace('0.0.0.0', 'localhost') : null;
}

module.exports = { iniciar, urlDoTexto };
