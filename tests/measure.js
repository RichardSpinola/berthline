// Measures each profile of a built package: startup time, idle memory of the whole process tree, and size on disk.
// Usage: node tests/measure.js <package> [java,web,standard] [idle seconds, default 30]   (MEASURE_RUNS=3 runs per profile, median; MEASURE_PORT)
// Experiments: MEASURE_BASELINE=0 skips the baseline; MEASURE_OVERRIDES=<file.json> merges settings over the profile for the run.
// Each profile is also measured as plain VSCodium with the same extensions (baseline). Memory is also split per process group.
// Writes tests/out/measure.json and prints a Markdown table for the README.
const fs = require('fs'), os = require('os'), path = require('path');
const { spawn, spawnSync, execFileSync } = require('child_process');
const { SAIDA, dormir, conectar, fechado } = require('./cdp');

const PACOTE = path.resolve(process.argv[2]);
const APPS = (process.argv[3] || 'java,web,standard').split(',');
const OCIOSO = Number(process.argv[4] || 30) * 1000;
const RUNS = Number(process.env.MEASURE_RUNS || 3);
const SEM_BASE = process.env.MEASURE_BASELINE === '0';
const AJUSTES = process.env.MEASURE_OVERRIDES; // JSON of settings merged over the profile for one experiment
const PORTA = +process.env.MEASURE_PORT || 9336;
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

/** Which part of the editor a process is, from its command line (and, on Linux, the entry point in its environment). */
// Classified by command line only: utility processes carry no environment we can tell apart.
// The extension host is the node utility that parents the language servers / tsserver / JDT LS.
function grupo(cmd) {
    if (/tsserver/.test(cmd)) return 'tsserver';
    if (/jdt\.ls|equinox\.launcher|jdtls/i.test(cmd)) return 'jdt.ls';
    if (/gradle/i.test(cmd)) return 'gradle';
    if (/extensions[\\/](json|html|css)[^ ]*(Server|server)/.test(cmd)) return 'language servers (json/html/css)';
    if (/--type=gpu-process/.test(cmd)) return 'gpu';
    if (/--type=zygote/.test(cmd)) return 'zygote';
    if (/--type=renderer/.test(cmd)) return 'renderer';
    if (/--type=utility/.test(cmd)) return /NetworkService/.test(cmd) ? 'network' : 'node utility';
    if (!/--type=/.test(cmd) && /codium|VSCodium/i.test(cmd) && /--user-data-dir/.test(cmd)) return 'main';
    return 'other';
}
// procs: [{ pid, pai, cmd, rss, pss }] -> groups, naming the extension host by its children
function agrupar(procs) {
    const nomes = new Map(procs.map(p => [p.pid, grupo(p.cmd)]));
    const filhos = new Set(['tsserver', 'jdt.ls', 'gradle', 'language servers (json/html/css)']);
    for (const p of procs) if (filhos.has(nomes.get(p.pid)) && nomes.get(p.pai) === 'node utility') nomes.set(p.pai, 'extension host');
    // the biggest renderer is the window; the rest are webviews / other pages
    const rend = procs.filter(p => nomes.get(p.pid) === 'renderer').sort((x, y) => y.pss - x.pss);
    for (const p of rend.slice(1)) nomes.set(p.pid, 'webview renderer');
    const grupos = {};
    for (const p of procs) {
        const g = grupos[nomes.get(p.pid)] ??= { n: 0, rss: 0, pss: 0 };
        g.n++; g.rss += p.rss; g.pss += p.pss;
        if (process.env.MEASURE_DEBUG) console.error(p.pid, MB(p.pss), nomes.get(p.pid), p.cmd.slice(-110));
    }
    return grupos;
}
function memoria(raiz) {
    if (JANELAS) {
        const saida = execFileSync('powershell', ['-NoProfile', '-Command',
            'Get-CimInstance Win32_Process | ForEach-Object { "$($_.ProcessId)|$($_.ParentProcessId)|$($_.WorkingSetSize)|$($_.PrivatePageCount)|$($_.CommandLine)" }'], { encoding: 'utf8' });
        const procs = saida.trim().split(/\r?\n/).map(l => { const [pid, pai, ws, priv, ...cmd] = l.trim().split('|'); return { pid: +pid, pai: +pai, ws: +ws, priv: +priv, cmd: cmd.join('|') }; });
        const arvore = descendentes(raiz, procs.map(p => [p.pid, p.pai]));
        const meus = procs.filter(p => arvore.has(p.pid));
        const grupos = agrupar(meus.map(p => ({ pid: p.pid, pai: p.pai, cmd: p.cmd, rss: p.ws, pss: p.priv })));
        return { processos: meus.length, rss: meus.reduce((t, p) => t + p.ws, 0), privada: meus.reduce((t, p) => t + p.priv, 0), grupos };
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
    const procs = [];
    for (const pid of arvore) {
        try {
            const t = fs.readFileSync(`/proc/${pid}/smaps_rollup`, 'utf8');
            const rss = Number(/^Rss:\s+(\d+)/m.exec(t)[1]) * 1024, pss = Number(/^Pss:\s+(\d+)/m.exec(t)[1]) * 1024;
            const cmd = fs.readFileSync(`/proc/${pid}/cmdline`, 'utf8').replace(/\0/g, ' ');
            procs.push({ pid, pai: pares.find(q => q[0] === pid)[1], cmd, rss, pss });
        } catch { /* gone */ }
    }
    const rss = procs.reduce((t, p) => t + p.rss, 0), pss = procs.reduce((t, p) => t + p.pss, 0);
    const grupos = agrupar(procs);
    return { processos: arvore.size, rss, pss, grupos };
}

function descendentes(raiz, pares) {
    const filhos = new Map();
    for (const [pid, pai] of pares) (filhos.get(pai) ?? filhos.set(pai, []).get(pai)).push(pid);
    const vistos = new Set([raiz]);
    const fila = [raiz];
    while (fila.length) for (const f of filhos.get(fila.shift()) ?? []) if (!vistos.has(f)) { vistos.add(f); fila.push(f); }
    return vistos;
}

async function medir(app, base = false) {
    const temp = fs.realpathSync.native(fs.mkdtempSync(path.join(os.tmpdir(), 'measure-')));
    const pasta = path.join(temp, app);
    fs.cpSync(path.join(__dirname, 'fixture', app === 'java' ? 'java' : 'web'), pasta, { recursive: true });
    const env = { ...process.env, SUITE_ROOT: PACOTE };
    spawnSync(HUB, ['--trust', pasta], { env });
    spawnSync(HUB, ['--prepare'], { env });
    delete env.SUITE_ROOT;
    delete env.ELECTRON_RUN_AS_NODE;
    const dados = path.join(PACOTE, 'data', app);
    let usuario = path.join(dados, 'user'), extensoes = path.join(dados, 'extensions');
    if (base) {
        // Baseline: the same editor and the same extensions, but no Berthline settings, keymap, tools or environment
        usuario = path.join(temp, 'user');
        extensoes = path.join(temp, 'extensions');
        fs.cpSync(path.join(dados, 'extensions'), extensoes, { recursive: true });
    } else {
        Object.assign(env, { SUITE_TOOLS: path.join(dados, 'tools'), SUITE_VISUAL: '0', SUITE_ANIMATIONS: '1', SUITE_APP: app,
            SUITE_NODE: path.join(PACOTE, 'node', JANELAS ? 'node.exe' : 'bin/node'), SUITE_WATERMARK: path.join(dados, 'watermark.svg') });
    }
    const arqAjustes = path.join(usuario, 'User', 'settings.json');
    let original = null;
    if (AJUSTES && !base) {
        original = fs.readFileSync(arqAjustes, 'utf8');
        fs.writeFileSync(arqAjustes, JSON.stringify({ ...JSON.parse(original), ...JSON.parse(fs.readFileSync(AJUSTES, 'utf8')) }, null, 4));
    }
    const exe = ['VSCodium.exe', 'codium'].map(n => path.join(PACOTE, 'editor', n)).find(fs.existsSync);
    const args = [`--user-data-dir=${usuario}`, `--extensions-dir=${extensoes}`, `--remote-debugging-port=${PORTA}`, pasta];
    if (base) args.unshift('--disable-workspace-trust');
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
    if (original !== null) fs.writeFileSync(arqAjustes, original);
    fs.rmSync(temp, { recursive: true, force: true });
    return { app, abertura_ms: pronto ? abertura : null, ...mem, extensoes: tamanho(path.join(dados, 'extensions')) };
}

const mediana = v => { const o = v.filter(x => x != null).sort((x, y) => x - y); return o.length ? (o.length % 2 ? o[o.length >> 1] : (o[o.length / 2 - 1] + o[o.length / 2]) / 2) : null; };

/** Median of the numeric fields of several runs, group by group. */
function resumir(runs) {
    const campo = f => mediana(runs.map(f));
    const nomes = [...new Set(runs.flatMap(r => Object.keys(r.grupos)))];
    const grupos = {};
    for (const n of nomes) grupos[n] = { n: campo(r => r.grupos[n]?.n ?? 0), rss: campo(r => r.grupos[n]?.rss ?? 0), pss: campo(r => r.grupos[n]?.pss ?? 0) };
    return { app: runs[0].app, abertura_ms: campo(r => r.abertura_ms), processos: campo(r => r.processos), rss: campo(r => r.rss),
        pss: campo(r => r.pss), privada: campo(r => r.privada), extensoes: runs[0].extensoes, grupos };
}

(async () => {
    fs.mkdirSync(SAIDA, { recursive: true });
    const comum = ['editor', 'node', '_hub'].reduce((t, p) => t + tamanho(path.join(PACOTE, p)), 0);
    const linhas = [];
    for (const app of APPS) {
        // One warm-up run per profile, so the first one doesn't pay for a cold disk cache; then RUNS measured runs, median of each number
        await medir(app);
        const runs = [], bases = [];
        for (let i = 0; i < RUNS; i++) runs.push(await medir(app));
        if (!SEM_BASE) for (let i = 0; i < RUNS; i++) bases.push(await medir(app, true));
        const r = { ...resumir(runs), execucoes: runs.length, baseline: SEM_BASE ? { pss: 0, privada: 0, grupos: {} } : resumir(bases) };
        console.log(JSON.stringify({ app, abertura_ms: r.abertura_ms, pss: MB(r.pss ?? r.privada), baseline_pss: MB(r.baseline.pss ?? r.baseline.privada) }));
        linhas.push(r);
    }
    const resultado = { data: new Date().toISOString().slice(0, 10), sistema: `${os.type()} ${os.release()}`, cpu: os.cpus()[0]?.model,
        ram_total: MB(os.totalmem()), ocioso_s: OCIOSO / 1000, execucoes: RUNS, pacote: tamanho(PACOTE), comum, perfis: linhas };
    fs.writeFileSync(path.join(SAIDA, 'measure.json'), JSON.stringify(resultado, null, 2));
    const campoMem = r => JANELAS ? r.privada : r.pss;
    const mem = JANELAS ? 'Private memory' : 'Memory (PSS)';
    console.log(`\n| Profile | Startup | ${mem} | Plain VSCodium | Processes | Extensions on disk |\n|---|---:|---:|---:|---:|---:|`);
    for (const r of linhas) {
        console.log(`| ${r.app[0].toUpperCase()}${r.app.slice(1)} | ${r.abertura_ms ? (r.abertura_ms / 1000).toFixed(1) + ' s' : 'n/a'} | ${MB(campoMem(r))} MB | ${MB(campoMem(r.baseline))} MB | ${r.processos} | ${MB(r.extensoes)} MB |`);
    }
    console.log('\nPer process (median MB, count):');
    for (const r of linhas) {
        console.log(`${r.app}: ` + Object.entries(r.grupos).sort((a, b) => b[1].pss - a[1].pss).map(([n, g]) => `${n} ${MB(JANELAS ? g.rss : g.pss)} (${g.n})`).join(', '));
        console.log(`${r.app} baseline: ` + Object.entries(r.baseline.grupos).sort((a, b) => b[1].pss - a[1].pss).map(([n, g]) => `${n} ${MB(JANELAS ? g.rss : g.pss)} (${g.n})`).join(', '));
    }
    console.log(`\nWhole package: ${MB(resultado.pacote)} MB on disk (editor, Node and Hub: ${MB(comum)} MB, shared by all profiles).`);
    console.log(`${resultado.sistema}, ${resultado.cpu}, ${resultado.ram_total} MB RAM; median of ${RUNS} runs, memory read after ${resultado.ocioso_s} s idle with the sample project open.`);
})().catch(e => { console.error(e); process.exit(1); });
