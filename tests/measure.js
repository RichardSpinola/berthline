// Measures each profile of a built package: startup time, idle memory of the whole process tree, and size on disk.
// Usage: node tests/measure.js <package> [java,web,standard] [idle seconds, default 30]
// Writes tests/out/measure.json and prints a Markdown table for the README.
const fs = require('fs'), os = require('os'), path = require('path');
const { spawn, spawnSync, execFileSync } = require('child_process');
const { SAIDA, dormir, conectar, fechado } = require('./cdp');

const PACOTE = path.resolve(process.argv[2]);
const APPS = (process.argv[3] || 'java,web,standard').split(',');
const OCIOSO = Number(process.argv[4] || 30) * 1000;
const PORTA = 9336;
const JANELAS = process.platform === 'win32';
const HUB = path.join(PACOTE, JANELAS ? 'Hub.exe' : 'Hub');
const MB = n => Math.round(n / 1048576);

function tamanho(alvo) {
    let total = 0;
    const st = fs.lstatSync(alvo, { throwIfNoEntry: false });
    if (!st) return 0;
    if (!st.isDirectory()) return st.size;
    for (const n of fs.readdirSync(alvo)) total += tamanho(path.join(alvo, n));
    return total;
}

/** Memory of a process and all its children: RSS sum and, on Linux, PSS (shared pages split fairly). */
function memoria(raiz) {
    if (JANELAS) {
        const saida = execFileSync('powershell', ['-NoProfile', '-Command',
            'Get-CimInstance Win32_Process | ForEach-Object { "$($_.ProcessId) $($_.ParentProcessId) $($_.WorkingSetSize) $($_.PrivatePageCount)" }'], { encoding: 'utf8' });
        const procs = saida.trim().split(/\r?\n/).map(l => l.trim().split(/\s+/).map(Number));
        const arvore = descendentes(raiz, procs.map(([pid, pai]) => [pid, pai]));
        const meus = procs.filter(p => arvore.has(p[0]));
        return { processos: meus.length, rss: meus.reduce((t, p) => t + p[2], 0), privada: meus.reduce((t, p) => t + p[3], 0) };
    }
    const pares = [];
    for (const n of fs.readdirSync('/proc')) {
        if (!/^\d+$/.test(n)) continue;
        try {
            const stat = fs.readFileSync(`/proc/${n}/stat`, 'utf8');
            pares.push([Number(n), Number(stat.slice(stat.lastIndexOf(')') + 2).split(' ')[1])]);
        } catch { /* gone */ }
    }
    const arvore = descendentes(raiz, pares);
    let rss = 0, pss = 0;
    for (const pid of arvore) {
        try {
            const t = fs.readFileSync(`/proc/${pid}/smaps_rollup`, 'utf8');
            rss += Number(/^Rss:\s+(\d+)/m.exec(t)[1]) * 1024;
            pss += Number(/^Pss:\s+(\d+)/m.exec(t)[1]) * 1024;
        } catch { /* gone */ }
    }
    return { processos: arvore.size, rss, pss };
}

function descendentes(raiz, pares) {
    const filhos = new Map();
    for (const [pid, pai] of pares) (filhos.get(pai) ?? filhos.set(pai, []).get(pai)).push(pid);
    const vistos = new Set([raiz]);
    const fila = [raiz];
    while (fila.length) for (const f of filhos.get(fila.shift()) ?? []) if (!vistos.has(f)) { vistos.add(f); fila.push(f); }
    return vistos;
}

async function medir(app) {
    const temp = fs.realpathSync.native(fs.mkdtempSync(path.join(os.tmpdir(), 'measure-')));
    const pasta = path.join(temp, app);
    fs.cpSync(path.join(__dirname, 'fixture', app === 'java' ? 'java' : 'web'), pasta, { recursive: true });
    const env = { ...process.env, SUITE_ROOT: PACOTE };
    spawnSync(HUB, ['--trust', pasta], { env });
    spawnSync(HUB, ['--prepare'], { env });
    delete env.SUITE_ROOT;
    delete env.ELECTRON_RUN_AS_NODE;
    const dados = path.join(PACOTE, 'data', app);
    Object.assign(env, { SUITE_TOOLS: path.join(dados, 'tools'), SUITE_VISUAL: '0', SUITE_ANIMATIONS: '1', SUITE_APP: app,
        SUITE_NODE: path.join(PACOTE, 'node', JANELAS ? 'node.exe' : 'bin/node'), SUITE_WATERMARK: path.join(dados, 'watermark.svg') });
    const exe = ['VSCodium.exe', 'codium'].map(n => path.join(PACOTE, 'editor', n)).find(fs.existsSync);
    const args = [`--user-data-dir=${path.join(dados, 'user')}`, `--extensions-dir=${path.join(dados, 'extensions')}`,
        `--remote-debugging-port=${PORTA}`, pasta];
    if (!JANELAS) args.unshift('--ozone-platform=x11');
    const inicio = Date.now();
    const filho = spawn(exe, args, { env, stdio: 'ignore', detached: !JANELAS });
    const h = await conectar(PORTA);
    const pronto = await h.ate(() => h.ev(`!!document.querySelector('.part.statusbar .statusbar-item') && !!document.querySelector('.explorer-folders-view .monaco-list-row')`), 60000);
    const abertura = Date.now() - inicio;
    await dormir(OCIOSO);
    const mem = memoria(filho.pid);
    await h.fechar();
    await fechado(PORTA);
    fs.rmSync(temp, { recursive: true, force: true });
    return { app, abertura_ms: pronto ? abertura : null, ...mem, extensoes: tamanho(path.join(dados, 'extensions')) };
}

(async () => {
    fs.mkdirSync(SAIDA, { recursive: true });
    const comum = ['editor', 'node', '_hub'].reduce((t, p) => t + tamanho(path.join(PACOTE, p)), 0);
    const linhas = [];
    for (const app of APPS) {
        // One warm-up run per profile, so the first one doesn't pay for a cold disk cache
        await medir(app);
        const r = await medir(app);
        console.log(JSON.stringify(r));
        linhas.push(r);
    }
    const resultado = { data: new Date().toISOString().slice(0, 10), sistema: `${os.type()} ${os.release()}`, cpu: os.cpus()[0]?.model,
        ram_total: MB(os.totalmem()), ocioso_s: OCIOSO / 1000, pacote: tamanho(PACOTE), comum, perfis: linhas };
    fs.writeFileSync(path.join(SAIDA, 'measure.json'), JSON.stringify(resultado, null, 2));
    const mem = JANELAS ? 'Private memory' : 'Memory (PSS)';
    console.log(`\n| Profile | Startup | ${mem} | Processes | Extensions on disk |\n|---|---:|---:|---:|---:|`);
    for (const r of linhas) {
        console.log(`| ${r.app[0].toUpperCase()}${r.app.slice(1)} | ${r.abertura_ms ? (r.abertura_ms / 1000).toFixed(1) + ' s' : 'n/a'} | ${MB(JANELAS ? r.privada : r.pss)} MB | ${r.processos} | ${MB(r.extensoes)} MB |`);
    }
    console.log(`\nWhole package: ${MB(resultado.pacote)} MB on disk (editor, Node and Hub: ${MB(comum)} MB, shared by all profiles).`);
    console.log(`${resultado.sistema}, ${resultado.cpu}, ${resultado.ram_total} MB RAM; memory read after ${resultado.ocioso_s} s idle with the sample project open.`);
})().catch(e => { console.error(e); process.exit(1); });
