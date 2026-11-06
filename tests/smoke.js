// Opens each profile from a built package and checks the main flows over CDP.
const fs = require('fs'), os = require('os'), path = require('path'), http = require('http');
const { spawn, spawnSync } = require('child_process');
const { SAIDA, dormir, conectar, fechado } = require('./cdp');

const PACOTE = path.resolve(process.argv[2]);
const SO = process.argv[3] ? process.argv[3].split(',') : ['java', 'web'];
const PORTA = 9333;
const RODAR = '^Run \\(';
const HUB = path.join(PACOTE, process.platform === 'win32' ? 'Hub.exe' : 'Hub');
let falhas = 0;
const passo = (nome, ok, extra = '') => { if (!ok) falhas++; console.log(ok ? 'OK   ' : 'FAIL ', nome, extra); };

async function abrir(perfil, pasta) {
    spawnSync(HUB, ['--trust', pasta], { env: { ...process.env, SUITE_ROOT: PACOTE } });
    const p = spawn(HUB, ['--open', perfil, '--port', String(PORTA), pasta], { env: { ...process.env, SUITE_ROOT: PACOTE }, stdio: 'ignore' });
    p.on('error', e => { throw e; });
    return conectar(PORTA);
}

async function arquivo(h, nome) {
    if (!await h.acha('.explorer-folders-view .monaco-list-row', `^${nome}`)) await h.clica('.explorer-folders-view .monaco-list-row', 'src');
    await dormir(600);
    const ok = await h.clica('.explorer-folders-view .monaco-list-row', `^${nome}`);
    await dormir(1500);
    return ok;
}

async function java(pasta) {
    const h = await abrir('java', pasta);
    await dormir(12000);
    passo('workspace trusted', !/Restricted Mode/.test(await h.status()), await h.status());
    await arquivo(h, 'Main');
    passo('java server ready', await h.ate(async () => /Java: Ready/.test(await h.status()), 120000));
    console.log('status:', await h.status());
    console.log('actions:', await h.ev(`[...document.querySelectorAll('a.action-label')].filter(e=>e.getBoundingClientRect().width>0).map(e=>e.getAttribute('aria-label')).join(' | ')`));
    await dormir(5000);
    passo('visual extras', await h.ev(`!!window.__ijArvore`) && !/partial/.test(await h.status()));
    passo('app watermark', await h.ev(`!!document.getElementById('ij-marca')`));
    await h.foto('java-1-editor');
    console.log('run clicked', await h.clica('a.action-label', RODAR));
    passo('run asks input', await h.ate(async () => /Name\?/.test(await h.terminal()), 40000));
    await dormir(800);
    await h.clica('.terminal-wrapper .xterm');
    await dormir(400);
    await h.escreve('Ana');
    await h.tecla('Enter', 'Enter', 13);
    passo('run reads input', await h.ate(async () => /Hello, Ana!/.test(await h.terminal()), 10000));
    passo('exit code shown', await h.ate(async () => /Process finished with exit code 0/.test(await h.terminal()), 10000));
    await h.foto('java-2-run');
    await arquivo(h, 'Loop');
    await h.clica('a.action-label', RODAR);
    passo('loop runs', await h.ate(async () => /tick 2/.test(await h.terminal()), 40000));
    await h.clica('a.action-label', '^Stop');
    passo('stop ends loop', await h.ate(async () => /Process finished with exit code/.test((await h.terminal()).split('tick').pop()), 10000));
    passo('stop button leaves', await h.ate(async () => !await h.acha('a.action-label', '^Stop'), 6000));
    await h.foto('java-3-stop');

    await arquivo(h, 'Main');
    const gutter = await h.ev(`(()=>{const e=[...document.querySelectorAll('.editor-instance .line-numbers')].find(e=>e.innerText.trim()==='8');const b=e.getBoundingClientRect();return {x:b.left-12,y:b.y+b.height/2}})()`);
    await h.xy(gutter.x, gutter.y);
    await dormir(500);
    await h.clica('a.action-label', '^Debug \\(');
    passo('debug asks input', await h.ate(async () => /Name\?/.test(await h.terminal()), 40000));
    await dormir(800);
    await h.clica('.terminal-wrapper .xterm');
    await dormir(300);
    await h.escreve('Ana');
    await h.tecla('Enter', 'Enter', 13);
    passo('breakpoint hit', await h.ate(async () => /paused on breakpoint/i.test(await h.ev(`document.querySelector('.debug-call-stack-title, .state.label, .session')?.parentElement?.innerText + document.body.innerText.slice(0, 20000)`)) || !!await h.acha('.debug-top-entry, .codicon-debug-stackframe, .debug-breakpoint-stackframe'), 15000));
    await h.foto('java-4-debug');
    await h.clica('a.action-label', '^Stop');
    passo('debug stops', await h.ate(async () => !await h.acha('a.action-label', '^Stop'), 8000));

    await dormir(1500);
    passo('sidebar back on explorer', !!await h.acha('.explorer-folders-view .monaco-list-row', 'src'));
    await h.clica('.explorer-folders-view .monaco-list-row', 'src');
    await dormir(400);
    await h.clica('.explorer-folders-view .monaco-list-row', 'src');
    await dormir(400);
    await h.clica('a.action-label', '^New Java Class');
    await dormir(900);
    await h.escreve('Boat');
    await h.tecla('Enter', 'Enter', 13);
    passo('new java class', await h.ate(() => fs.existsSync(path.join(pasta, 'src/Boat.java')), 6000));
    await h.foto('java-5-class');

    await arquivo(h, 'Quick');
    await h.tecla('F1', 'F1', 112);
    await dormir(800);
    await h.escreve('Run with Profiler');
    await dormir(800);
    await h.tecla('Enter', 'Enter', 13);
    passo('profiler runs', await h.ate(async () => /total \d+/.test(await h.terminal()), 40000));
    passo('profiler report', await h.ate(async () => /Process finished with exit code 0/.test(await h.terminal()), 15000));
    await dormir(5000);
    await h.foto('java-6-profiler');
    await h.fechar();
}

async function web(pasta) {
    process.env.ELECTRON_RUN_AS_NODE = '1';
    // Evita abrir o navegador durante o teste
    const ajustes = path.join(PACOTE, 'data/web/user/User');
    fs.mkdirSync(ajustes, { recursive: true });
    fs.writeFileSync(path.join(ajustes, 'settings.json'), '{"liveServer.settings.NoBrowser": true}');
    const h = await abrir('web', pasta);
    await dormir(6000);
    await h.clica('.explorer-folders-view .monaco-list-row', '^app\\.js');
    await dormir(1500);
    await h.foto('web-1-editor');
    await h.clica('a.action-label', RODAR);
    passo('js runs', await h.ate(async () => /fixture 42/.test(await h.terminal()), 20000));
    await h.clica('.explorer-folders-view .monaco-list-row', '^main\\.ts');
    await dormir(1500);
    await h.clica('a.action-label', RODAR);
    passo('ts runs', await h.ate(async () => /typed 42/.test(await h.terminal()), 20000));
    await h.foto('web-2-run');
    await h.clica('.explorer-folders-view .monaco-list-row', '^index\\.html');
    await dormir(1200);
    await h.clica('a.action-label', RODAR);
    passo('live server answers', await h.ate(async () => {
        try {
            return await new Promise(ok => http.get('http://127.0.0.1:5500/index.html', r => { ok(r.statusCode === 200); r.resume(); }).on('error', () => ok(false)));
        } catch { return false; }
    }, 15000));
    await h.fechar();
}

(async () => {
    fs.mkdirSync(SAIDA, { recursive: true });
    const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'suite-'));
    for (const perfil of SO) {
        const pasta = path.join(temp, perfil);
        fs.cpSync(path.join(__dirname, 'fixture', perfil), pasta, { recursive: true });
        console.log('--', perfil);
        await ({ java, web })[perfil](pasta);
        await fechado(PORTA);
        await dormir(1000);
    }
    // The editor can hold the folder for a moment after closing, and this is only cleanup.
    try { fs.rmSync(temp, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 }); } catch (e) { console.log('cleanup skipped', e.code); }
    console.log(falhas ? `${falhas} failed` : 'all passed');
    process.exit(falhas ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
