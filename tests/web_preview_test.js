// Tests the Web preview server and HTML scanner in plain Node (no editor needed).
// Usage: node tests/web_preview_test.js
const assert = require('assert');
const fs = require('fs');
const http = require('http');
const net = require('net');
const os = require('os');
const path = require('path');
const { marcar, linhaDoElemento, injetarScript } = require('../extension-web/html');
const { iniciar, urlDoTexto } = require('../extension-web/servidor');
const { BLOCOS, cssDoBloco } = require('../extension-web/blocos');

let falhas = 0;
async function passo(nome, f) {
    try { await f(); console.log('OK  ', nome); } catch (e) { falhas++; console.log('FAIL', nome, '-', e.message); }
}

const pegar = (url, cab = {}) => new Promise((ok, nao) => {
    http.get(url, { headers: cab }, r => {
        let b = '';
        r.setEncoding('utf8');
        r.on('data', d => b += d);
        r.on('end', () => ok({ status: r.statusCode, tipo: r.headers['content-type'], corpo: b, cab: r.headers }));
    }).on('error', nao);
});

function proximoEvento(url) {
    return new Promise((ok, nao) => {
        const req = http.get(url, r => {
            let b = '';
            r.setEncoding('utf8');
            r.on('data', d => {
                b += d;
                const m = /data: (.*)\n\n/.exec(b);
                if (m) { req.destroy(); ok(JSON.parse(m[1])); }
            });
        });
        req.on('error', e => e.code !== 'ECONNRESET' && nao(e));
    });
}

const PAGINA = `<!doctype html>
<html lang="en">
<head>
  <link rel="stylesheet" href="style.css">
  <script>if (1 < 2 && "<p>") {}</script>
</head>
<body>
  <!-- <section> in a comment -->
  <nav class="a" data-x="1 > 0">
    <a href="#">Home</a>
  </nav>
  <p>One
  <p>Two <img src="x.png"><br/>
  <textarea><b>raw</b></textarea>
</body>
</html>
`;

(async () => {
    await passo('marks start tags with their 0-based line', () => {
        const m = marcar(PAGINA);
        assert.match(m, /<nav class="a" data-x="1 > 0" data-bl="8">/);
        assert.match(m, /<a href="#" data-bl="9">/);
        assert.match(m, /<p data-bl="12">Two <img src="x.png" data-bl="12"><br data-bl="12"\/>/);
        assert.match(m, /<script>if \(1 < 2 && "<p>"\) \{\}<\/script>/, 'script content untouched');
        assert.doesNotMatch(m, /<section data-bl/, 'comment untouched');
        assert.match(m, /<textarea data-bl="13"><b>raw<\/b><\/textarea>/, 'textarea content untouched');
        assert.doesNotMatch(m, /<html[^>]*data-bl|<head[^>]*data-bl/);
    });

    await passo('finds the innermost element under the cursor', () => {
        const em = t => linhaDoElemento(PAGINA, PAGINA.indexOf(t));
        assert.strictEqual(em('Home'), 9);
        assert.strictEqual(em('</nav>'), 8);
        assert.strictEqual(em('One'), 11);
        assert.strictEqual(em('<!-- <section>'), 6, 'a comment belongs to body');
        assert.strictEqual(linhaDoElemento(PAGINA, 0), -1);
    });

    await passo('script goes before </body>, or at the end', () => {
        assert.strictEqual(injetarScript('<body>x</body>', '<s>'), '<body>x<s></body>');
        assert.strictEqual(injetarScript('<p>x', '<s>'), '<p>x<s>');
    });

    await passo('reads the URL a dev server prints', () => {
        assert.strictEqual(urlDoTexto('\x1b[32m  ➜  \x1b[1mLocal\x1b[22m:   \x1b[36mhttp://localhost:\x1b[1m5173\x1b[22m/\x1b[39m\n'), 'http://localhost:5173/');
        assert.strictEqual(urlDoTexto('ready - started server on 0.0.0.0:3000, url: http://0.0.0.0:3000'), 'http://localhost:3000');
        assert.strictEqual(urlDoTexto('compiling...'), null);
    });

    const raiz = fs.mkdtempSync(path.join(os.tmpdir(), 'bl-preview-'));
    fs.writeFileSync(path.join(raiz, 'index.html'), PAGINA);
    fs.writeFileSync(path.join(raiz, 'style.css'), 'body{color:red}');
    fs.mkdirSync(path.join(raiz, 'sub'));
    fs.writeFileSync(path.join(raiz, 'sub/index.html'), '<p>sub</p>');
    fs.writeFileSync(path.join(path.dirname(raiz), 'bl-secret.txt'), 'secret');
    const s = await iniciar({ raiz });

    await passo('serves marked HTML with the client script on 127.0.0.1', async () => {
        assert.match(s.url, /^http:\/\/127\.0\.0\.1:\d+\/$/);
        const r = await pegar(s.url);
        assert.strictEqual(r.status, 200);
        assert.match(r.corpo, /data-bl="8"/);
        assert.match(r.corpo, /<script src="\/__berthline\/client.js"><\/script><\/body>/);
        assert.strictEqual(r.cab['cache-control'], 'no-store');
        const c = await pegar(s.url + '__berthline/client.js');
        assert.match(c.tipo, /javascript/);
        assert.match(c.corpo, /EventSource/);
    });

    await passo('serves assets, folders and 404s', async () => {
        const css = await pegar(s.url + 'style.css');
        assert.strictEqual(css.corpo, 'body{color:red}');
        assert.match(css.tipo, /text\/css/);
        assert.strictEqual((await pegar(s.url + 'sub')).status, 301);
        assert.match((await pegar(s.url + 'sub/')).corpo, /<p data-bl="0">sub/);
        const nada = await pegar(s.url + 'nothing.png');
        assert.strictEqual(nada.status, 404);
        assert.match(nada.corpo, /client\.js/, 'the 404 page still reloads when the file appears');
    });

    await passo('never leaves the project folder', async () => {
        for (const p of ['../bl-secret.txt', '%2e%2e/bl-secret.txt', '..%2fbl-secret.txt', 'sub/../../bl-secret.txt']) {
            const r = await new Promise((ok, nao) => {
                const c = net.connect(s.porta, '127.0.0.1', () => c.write(`GET /${p} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n`));
                let b = '';
                c.on('data', d => b += d);
                c.on('end', () => ok(b));
                c.on('error', nao);
            });
            assert.doesNotMatch(r, /secret$/m, p);
        }
    });

    await passo('pushes reload and CSS events to open pages', async () => {
        const evento = proximoEvento(s.url + '__berthline/events');
        await new Promise(f => setTimeout(f, 150));
        s.enviar({ type: 'css' });
        assert.deepStrictEqual(await evento, { type: 'css' });
    });

    await passo('stops when closed', async () => {
        await s.fechar();
        await assert.rejects(pegar(s.url));
    });

    // A fake dev server: HTML page, a script, and a WebSocket-like upgrade that echoes
    const dev = http.createServer((req, res) => {
        if (req.url === '/') { res.writeHead(200, { 'content-type': 'text/html', 'content-length': 30 }); res.end('<html><body>dev app</body></html>'.slice(0, 30)); }
        else { res.writeHead(200, { 'content-type': 'text/javascript' }); res.end(`// ${req.headers.host}`); }
    });
    dev.on('upgrade', (req, socket) => {
        socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n');
        socket.on('data', d => socket.write(d));
        socket.on('end', () => socket.end());
    });
    await new Promise(f => dev.listen(0, '127.0.0.1', f));
    const p = await iniciar({ alvo: `http://localhost:${dev.address().port}/` });

    await passo('proxies a dev server and injects the client into its HTML', async () => {
        const r = await pegar(p.url);
        assert.match(r.corpo, /dev app<script src="\/__berthline\/client.js"><\/script>/);
        assert.strictEqual(r.cab['content-length'], undefined);
        const js = await pegar(p.url + 'src/main.js');
        assert.strictEqual(js.corpo, `// localhost:${dev.address().port}`, 'host header points at the dev server');
    });

    await passo('passes WebSocket upgrades through (hot reload)', async () => {
        const eco = await new Promise((ok, nao) => {
            const c = net.connect(p.porta, '127.0.0.1', () => c.write('GET /hmr HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n'));
            let b = '';
            c.on('data', d => {
                b += d;
                if (b.includes('\r\n\r\n') && !b.includes('ping')) c.write('ping');
                if (b.endsWith('ping')) { c.destroy(); ok(b); }
            });
            c.on('error', nao);
        });
        assert.match(eco, /^HTTP\/1.1 101/);
    });

    await passo('reports a dev server that stopped', async () => {
        const fechou = new Promise(f => dev.close(f));
        dev.closeAllConnections();
        await fechou;
        const r = await pegar(p.url, { connection: 'close' });
        assert.strictEqual(r.status, 502);
    });
    await p.fechar();

    await passo('eight blocks, each with markup and CSS', () => {
        assert.strictEqual(BLOCOS.length, 8);
        for (const b of BLOCOS) {
            assert.ok(b.nome && b.html.length && b.css.trim(), b.nome);
            assert.match(b.html.join('\n'), /\$\{?1/, `${b.nome} has tab stops`);
            assert.match(cssDoBloco(b), new RegExp(`/\\* Block: ${b.nome} \\*/`));
        }
    });

    fs.rmSync(raiz, { recursive: true, force: true });
    fs.rmSync(path.join(path.dirname(raiz), 'bl-secret.txt'), { force: true });
    console.log(falhas ? `${falhas} failed` : 'all passed');
    process.exit(falhas ? 1 : 0);
})();
