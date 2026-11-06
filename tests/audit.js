// Audits a built package: commands, shortcuts, menus, themes and editor behaviour.
// Usage: node tests/audit.js <package> <java|web>
const fs = require('fs'), os = require('os'), path = require('path'), http = require('http');
const { spawn, spawnSync } = require('child_process');
const { SAIDA, dormir, conectar, fechado } = require('./cdp');

const PACOTE = path.resolve(process.argv[2]);
const APP = process.argv[3] || 'java';
const PORTA = 9334;
const JANELAS = process.platform === 'win32';
const HUB = path.join(PACOTE, JANELAS ? 'Hub.exe' : 'Hub');
const INSEGUROS = /^ij\.(newProject|reload|gitPush|gitPull|safeDelete|openFiles)$/;
const MODIF = { alt: 1, ctrl: 2, shift: 8 };
const MOLDURA = '38,40,44'; // #26282C, the Islands Dark frame set in profiles/base/settings.json
const relatorio = { app: APP, plataforma: process.platform, falhas: [], avisos: [], dados: {} };

const falha = (nome, extra = '') => { relatorio.falhas.push(`${nome} ${extra}`.trim()); console.log('FAIL ', nome, extra); };
const certo = (nome, extra = '') => console.log('OK   ', nome, extra);
const conferir = (nome, ok, extra = '') => (ok ? certo : falha)(nome, extra);
const aviso = (nome, extra = '') => { relatorio.avisos.push(`${nome} ${extra}`.trim()); console.log('NOTE ', nome, extra); };

const rpc = (acao, dados = {}) => new Promise((ok, nao) => {
    const r = http.request({ host: '127.0.0.1', port: 9335, method: 'POST' }, res => {
        let b = '';
        res.on('data', d => b += d);
        res.on('end', () => { const j = JSON.parse(b); j.erro ? nao(new Error(j.erro)) : ok(j.ok); });
    });
    r.on('error', nao);
    r.end(JSON.stringify({ acao, ...dados }));
});

function iniciar(pasta) {
    const usuario = path.join(PACOTE, 'data', APP);
    spawnSync(HUB, ['--trust', pasta], { env: { ...process.env, SUITE_ROOT: PACOTE } });
    spawnSync(HUB, ['--prepare'], { env: { ...process.env, SUITE_ROOT: PACOTE } });
    const exe = ['VSCodium.exe', 'Code.exe', 'codium', 'code'].map(n => path.join(PACOTE, 'editor', n)).find(fs.existsSync);
    const env = { ...process.env, SUITE_TOOLS: path.join(usuario, 'tools'), SUITE_VISUAL: '1', SUITE_ANIMATIONS: '1',
        SUITE_WATERMARK: path.join(usuario, 'watermark.svg'), SUITE_HUB: HUB };
    delete env.ELECTRON_RUN_AS_NODE;
    const args = [`--user-data-dir=${path.join(usuario, 'user')}`, `--extensions-dir=${path.join(usuario, 'extensions')}`,
        `--extensionDevelopmentPath=${path.join(__dirname, 'auditor')}`, `--remote-debugging-port=${PORTA}`, pasta];
    if (!JANELAS) args.unshift('--ozone-platform=x11');
    spawn(exe, args, { env, stdio: 'ignore', detached: true }).unref();
}

async function pronto() {
    for (let i = 0; i < 120; i++) {
        try { await rpc('ajuste', { chave: 'files.autoSave' }); return true; } catch { await dormir(500); }
    }
    return false;
}

const tecla = (h, mods, key, code, vk) => (async () => {
    const modifiers = mods.reduce((t, m) => t + MODIF[m], 0);
    await h.c('Input.dispatchKeyEvent', { type: 'rawKeyDown', key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, modifiers });
    await h.c('Input.dispatchKeyEvent', { type: 'keyUp', key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, modifiers });
})();

async function focarEditor(h) {
    const r = await h.ev(`(()=>{const b=document.querySelector('.editor-instance .monaco-editor .view-lines').getBoundingClientRect();return {x:b.x+300,y:b.y+150}})()`);
    await h.xy(r.x, r.y);
    await dormir(300);
}

async function comandos(h) {
    const todos = new Set(await rpc('comandos'));
    relatorio.dados.comandos = todos.size;

    const atalhos = fs.readFileSync(path.join(PACOTE, `data/${APP}/user/User/keybindings.json`), 'utf8').replace(/^\s*\/\/.*$/gm, '');
    const lista = JSON.parse(atalhos.replace(/,(\s*[\]}])/g, '$1'));
    const vistos = {};
    for (const k of lista) {
        const c = k.command.replace(/^-/, '');
        if (!todos.has(c)) falha('shortcut has no command', `${k.key} -> ${c}`);
        if (!k.command.startsWith('-')) (vistos[`${k.key} | ${k.when ?? ''}`] ??= []).push(c);
    }
    for (const [k, v] of Object.entries(vistos)) if (v.length > 1) falha('shortcut conflict', `${k}: ${v.join(', ')}`);
    relatorio.dados.atalhos = lista.length;

    const nome = APP === 'java' ? 'berthline-tools' : 'berthline-web';
    const nossa = await rpc('contribuicoes', { id: `berthline.${nome}` });
    conferir(`${nome} installed`, !!nossa);
    if (!nossa) return;
    const estranha = APP === 'java' ? 'web' : 'ij';
    conferir('no commands from the other profile', ![...todos].some(c => c.startsWith(`${estranha}.`)));
    const proprios = nossa.commands.map(c => c.command);
    for (const c of proprios) if (!todos.has(c)) falha('command not registered', c);

    const pasta = path.join(PACOTE, `data/${APP}/extensions`, fs.readdirSync(path.join(PACOTE, `data/${APP}/extensions`)).find(n => n.startsWith(`berthline.${nome}`)));
    const arquivoAcoes = path.join(pasta, 'acoes.json');
    // Commands of idle extensions only show up after they activate, so running them is the real check.
    const alvos = fs.existsSync(arquivoAcoes) ? Object.fromEntries(Object.entries(JSON.parse(fs.readFileSync(arquivoAcoes))).map(([c, a]) => [c, a.t])) : {};

    const texto = await h.ev(`document.querySelector('.part.statusbar').innerText`);
    relatorio.dados.statusbar = texto;
    const resultado = {};
    for (const c of proprios) {
        if (INSEGUROS.test(c)) { resultado[c] = 'skipped'; continue; }
        const r = await rpc('executar', { comando: c });
        await dormir(250);
        await tecla(h, [], 'Escape', 'Escape', 27);
        const erro = await h.ev(`[...document.querySelectorAll('.notification-toast .codicon-error')].map(e=>e.closest('.notification-toast').innerText).join(' / ')`);
        if (r.startsWith('error')) falha('command failed', `${c}${alvos[c] ? ` -> ${alvos[c]}` : ''}: ${r}`);
        if (erro) falha('command shows error', `${c}: ${erro.replace(/\s+/g, ' ').slice(0, 140)}`);
        resultado[c] = r;
        await rpc('executar', { comando: 'notifications.clearAll' });
        await rpc('executar', { comando: 'workbench.action.closeQuickOpen' });
        await rpc('executar', { comando: 'workbench.action.closeMessages' });
    }
    relatorio.dados.executados = resultado;
    console.log('commands run', Object.keys(resultado).length, 'timeouts', Object.values(resultado).filter(v => v === 'timeout').length);
    await rpc('executar', { comando: 'workbench.action.closeAllEditors' });
    await rpc('executar', { comando: 'workbench.action.closePanel' });
}

async function teclado(h, arquivo) {
    await rpc('abrir', { arquivo });
    await dormir(800);
    await focarEditor(h);
    const estado = () => rpc('estado');
    for (const [nome, key, code, vk] of [['up', 'ArrowUp', 'ArrowUp', 38], ['down', 'ArrowDown', 'ArrowDown', 40], ['left', 'ArrowLeft', 'ArrowLeft', 37], ['right', 'ArrowRight', 'ArrowRight', 39]]) {
        await rpc('cursor', { linha: 5, coluna: 12 });
        // Shrink only does something after an expand
        if (nome === 'left') {
            await tecla(h, ['shift', 'alt'], 'ArrowRight', 'ArrowRight', 39);
            await tecla(h, ['shift', 'alt'], 'ArrowRight', 'ArrowRight', 39);
            await dormir(500);
        }
        const antes = await estado();
        await tecla(h, ['shift', 'alt'], key, code, vk);
        await dormir(500);
        const depois = await estado();
        const mudou = antes.texto !== depois.texto || JSON.stringify(antes.selecoes) !== JSON.stringify(depois.selecoes);
        const linhas = t => t.split('\n').length;
        conferir(`shift+alt+${nome} does something`, mudou, `lines ${linhas(antes.texto)} -> ${linhas(depois.texto)}, selection ${JSON.stringify(depois.selecoes)}`);
        relatorio.dados[`shift+alt+${nome}`] = { texto: antes.texto !== depois.texto, linhas: linhas(depois.texto) - linhas(antes.texto) };
        if (antes.texto !== depois.texto) await rpc('executar', { comando: 'undo' });
    }
}

async function autosave(h, arquivo) {
    const valor = await rpc('ajuste', { chave: 'files.autoSave' });
    relatorio.dados.autoSave = valor;
    await rpc('abrir', { arquivo });
    await dormir(600);
    await focarEditor(h);
    const original = fs.readFileSync(arquivo, 'utf8');
    await rpc('cursor', { linha: 0, coluna: 0 });
    await h.c('Input.insertText', { text: '// saved\n' });
    await dormir(3000);
    conferir('autosave writes without leaving the window', fs.readFileSync(arquivo, 'utf8') !== original, `files.autoSave=${valor}`);
    await rpc('executar', { comando: 'undo' });
    await rpc('executar', { comando: 'workbench.action.files.save' });
}

async function java(h, pasta) {
    const arquivo = path.join(pasta, 'src/Main.java');
    await rpc('abrir', { arquivo });
    const ok = await h.ate(async () => /Java: Ready/.test(await h.status()), 180000);
    conferir('java server ready', ok);
    await dormir(4000);
    const botoes = await h.ev(`[...document.querySelectorAll('.part.titlebar a.action-label, .editor-actions a.action-label')].filter(e=>e.getBoundingClientRect().width>0).map(e=>e.getAttribute('aria-label')||e.innerText)`);
    relatorio.dados.barra = botoes;
    const rodar = botoes.filter(b => /^Run( Java| or Debug| \()/.test(b));
    conferir('single run button', rodar.length === 1, rodar.join(' | '));
    await h.foto(`audit-${APP}-bar`);

    await rpc('cursor', { linha: 8, coluna: 8 });
    await rpc('executar', { comando: 'editor.action.insertSnippet', args: [{ langId: 'java', name: 'fori' }] });
    await dormir(500);
    const s = await rpc('estado');
    conferir('fori has a single cursor', s.selecoes.length === 1, `${s.selecoes.length} cursors`);
    await rpc('executar', { comando: 'leaveSnippet' });
    await rpc('executar', { comando: 'undo' });
    await rpc('executar', { comando: 'workbench.action.files.save' });

    for (const [nome, seletor] of [['editor', '.editor-instance .view-lines'], ['explorer', '.explorer-folders-view .monaco-list-row']]) {
        const r = await h.ev(`(()=>{const b=document.querySelector(${JSON.stringify(seletor)}).getBoundingClientRect();return {x:b.x+40,y:b.y+12}})()`);
        for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) await h.c('Input.dispatchMouseEvent', { type, x: r.x, y: r.y, button: 'right', buttons: 2, clickCount: 1 });
        await dormir(700);
        relatorio.dados[`menu-${nome}`] = await h.ev(`(()=>{const raizes=[document,...[...document.querySelectorAll('*')].map(e=>e.shadowRoot).filter(Boolean)];return raizes.flatMap(r=>[...r.querySelectorAll('.context-view .action-label, .monaco-menu .action-label')]).map(e=>e.innerText).filter(Boolean)})()`);
        await h.foto(`audit-menu-${nome}`);
        await tecla(h, [], 'Escape', 'Escape', 27);
        await dormir(300);
    }
}

// Fills the New Java Class dialog the way a person does: name first, then arrows to pick the type.
async function novoTipo(h, pasta, texto, descidas) {
    await rpc('executar', { comando: 'ij.newClassTop', limite: 800 });
    await dormir(500);
    await h.c('Input.insertText', { text: texto });
    await dormir(300);
    for (let i = 0; i < descidas; i++) await tecla(h, [], 'ArrowDown', 'ArrowDown', 40);
    await dormir(200);
    if (texto.startsWith('Dog')) await h.foto('audit-java-new-type');
    await tecla(h, [], 'Enter', 'Enter', 13);
    return path.join(pasta, 'src', `${texto.split(' ')[0]}.java`);
}

const texto = arquivo => fs.existsSync(arquivo) ? fs.readFileSync(arquivo, 'utf8') : '';

async function criacao(h, pasta) {
    await rpc('abrir', { arquivo: path.join(pasta, 'src/Main.java') });
    const cao = await novoTipo(h, pasta, 'Dog extends Pet implements Runnable', 0);
    const herdou = await h.ate(async () => /sound\(\)/.test(texto(cao)) && /run\(\)/.test(texto(cao)) && /Dog\(String/.test(texto(cao)), 25000);
    conferir('new class fills what the parent requires', herdou, texto(cao).replace(/\s+/g, ' ').slice(0, 200));
    for (const [nome, descidas, marca] of [['Base', 1, 'abstract class'], ['Shape', 2, 'interface'], ['Color', 3, 'FIRST("first")'], ['Point', 4, 'String name, int value'], ['Oops', 5, 'extends Exception'], ['App', 6, 'static void main'], ['Note', 7, '@interface']]) {
        const arquivo = await novoTipo(h, pasta, nome, descidas);
        conferir(`new type ${nome}`, await h.ate(async () => texto(arquivo).includes(marca), 4000));
    }
    await dormir(5000);
    for (const nome of ['Dog', 'Base', 'Shape', 'Color', 'Point', 'Oops', 'App', 'Note']) {
        const erros = await rpc('erros', { arquivo: path.join(pasta, `src/${nome}.java`) });
        conferir(`${nome} compiles`, !erros.length, erros.join(' / ').slice(0, 160));
    }
    await rpc('executar', { comando: 'workbench.view.explorer' });
    await dormir(800);
    await h.foto('audit-java-icons');
    await rpc('executar', { comando: 'workbench.action.closeAllEditors' });
}

async function gerar(h, pasta) {
    await rpc('abrir', { arquivo: path.join(pasta, 'src/Sum.java') });
    await dormir(4000);
    await rpc('cursor', { linha: 3, coluna: 0 });
    await rpc('executar', { comando: 'ij.generate', limite: 3000 });
    await dormir(800);
    const itens = await h.ev(`[...document.querySelectorAll('.quick-input-list .monaco-list-row')].map(e=>e.innerText.trim())`);
    relatorio.dados.generate = itens;
    await h.foto('audit-java-generate');
    for (const nome of ['Constructor', 'Getter', 'Setter', 'Getter and Setter', 'equals() and hashCode()', 'toString()', 'Override or Implement Methods']) {
        conferir(`generate offers ${nome}`, itens.some(i => i.startsWith(`${nome}…`)), itens.join(' | '));
    }
    await h.c('Input.insertText', { text: 'toString' });
    await dormir(300);
    await tecla(h, [], 'Enter', 'Enter', 13);
    await dormir(1200);
    await h.foto('audit-java-generate-fields');
    await tecla(h, [], 'Enter', 'Enter', 13);
    conferir('generate writes toString', await h.ate(async () => /toString\(\)/.test((await rpc('estado')).texto), 6000));
    await rpc('executar', { comando: 'undo' });
    await rpc('executar', { comando: 'workbench.action.files.save' });
}

async function sugestoes(h, pasta) {
    const arquivo = path.join(pasta, 'src/Sum.java');
    await rpc('abrir', { arquivo });
    await dormir(800);
    await rpc('cursor', { linha: 5, coluna: 0 });
    await h.c('Input.insertText', { text: '        name.' });
    await dormir(1500);
    const pontos = (await rpc('sugestoes', { linha: 5, coluna: 13, gatilho: '.' })).map(s => s.rotulo);
    for (const p of ['var', 'sout', 'for', 'if', 'null']) conferir(`postfix .${p}`, pontos.includes(p));
    conferir('members stay in the list', pontos.some(p => p.startsWith('length')), pontos.slice(0, 6).join(' | '));
    await rpc('executar', { comando: 'editor.action.triggerSuggest' });
    await dormir(1500);
    await h.foto('audit-java-suggest');
    const lista = await h.ev(`[...document.querySelectorAll('.suggest-widget .monaco-list-row')].map(e=>e.getAttribute('aria-label')||'')`);
    conferir('members come before postfix', !/^var\b/.test(lista[0] ?? ''), lista.slice(0, 3).join(' | '));
    await tecla(h, [], 'Escape', 'Escape', 27);
    await rpc('executar', { comando: 'undo' });
    await rpc('executar', { comando: 'workbench.action.files.save' });
    await dormir(800);
    for (const [escrito, esperado] of [['sout', 'System.out.println(name);'], ['var', 'var valor = name;']]) {
        await rpc('cursor', { linha: 5, coluna: 0 });
        await h.c('Input.insertText', { text: `        name.${escrito}` });
        await rpc('executar', { comando: 'editor.action.triggerSuggest' });
        await dormir(1500);
        await tecla(h, [], 'Enter', 'Enter', 13);
        await dormir(600);
        const pronto = (await rpc('estado')).texto.split('\n')[5];
        conferir(`postfix .${escrito} writes the code`, pronto.includes(esperado), pronto.trim());
        await rpc('executar', { comando: 'leaveSnippet' });
        await rpc('executar', { comando: 'undo' });
        await rpc('executar', { comando: 'undo' });
        await rpc('executar', { comando: 'workbench.action.files.save' });
        await dormir(600);
        if ((await rpc('estado')).texto.split('\n')[5].includes('name.')) await rpc('executar', { comando: 'undo' });
    }
    await rpc('cursor', { linha: 5, coluna: 0 });
    await h.c('Input.insertText', { text: '        so' });
    await dormir(1200);
    const modelos = (await rpc('sugestoes', { linha: 5, coluna: 10 })).sort((a, b) => a.ordem.localeCompare(b.ordem)).map(s => s.rotulo);
    conferir('sout comes first', modelos[0] === 'sout', modelos.slice(0, 5).join(' | '));
    await rpc('executar', { comando: 'undo' });
    await rpc('executar', { comando: 'workbench.action.files.save' });
}

async function temas(h) {
    const lista = await rpc('temas');
    relatorio.dados.temas = lista.length;
    const medir = `(()=>{
const lum=c=>{const v=c.map(x=>{x/=255;return x<=.03928?x/12.92:((x+.055)/1.055)**2.4});return .2126*v[0]+.7152*v[1]+.0722*v[2]};
const rgb=s=>(s.match(/[\\d.]+/g)||[]).map(Number);
const fundo=e=>{while(e){const c=rgb(getComputedStyle(e).backgroundColor);if(c.length<4||c[3]>0)return c.slice(0,3);e=e.parentElement}return [255,255,255]};
const partes={title:'.part.titlebar',activity:'.part.activitybar',side:'.part.sidebar',editor:'.part.editor .monaco-editor-background',status:'.part.statusbar',panel:'.part.panel'};
const tinta={activity:'--vscode-activityBar-foreground',status:'--vscode-statusBar-foreground'};
const cor=(e,v)=>{if(!v)return rgb(getComputedStyle(e).color).slice(0,3);const p=document.querySelector('.monaco-workbench').appendChild(document.createElement('i'));p.style.color='var('+v+')';const c=rgb(getComputedStyle(p).color).slice(0,3);p.remove();return c};
const r={};for(const[k,s]of Object.entries(partes)){const e=document.querySelector(s);if(!e||!e.getBoundingClientRect().width)continue;const b=fundo(e),t=cor(e,tinta[k]),l=lum(b),m=lum(t);r[k]={rgb:b.join(','),fundo:+l.toFixed(3),contraste:+(((Math.max(l,m)+.05)/(Math.min(l,m)+.05)).toFixed(1))}}
return r})()`;
    const original = await rpc('ajuste', { chave: 'workbench.colorTheme' });
    for (const t of lista) {
        await rpc('ajustar', { chave: 'workbench.colorTheme', valor: t.id });
        await dormir(1200);
        const r = await h.ev(medir);
        const claro = t.tipo === 'vs' || t.tipo === 'hc-light';
        // Light themes paint these two dark on purpose (Light+ uses #007ACC), so only our own frame colour counts there
        const nativas = ['activity', 'status'];
        const erradas = Object.entries(r).filter(([k, v]) => {
            if (v.contraste < 3) return true;
            if (claro && nativas.includes(k)) return v.rgb === MOLDURA;
            return claro ? v.fundo < 0.3 : v.fundo > 0.6;
        });
        conferir(`theme ${t.id}`, !erradas.length, erradas.map(([k, v]) => `${k} ${JSON.stringify(v)}`).join(', '));
        await h.foto(`audit-${APP}-theme-${t.id.replace(/\W+/g, '-')}`);
    }
    await rpc('ajustar', { chave: 'workbench.colorTheme', valor: original });
}

(async () => {
    fs.mkdirSync(SAIDA, { recursive: true });
    const base = fs.realpathSync.native(fs.mkdtempSync(path.join(os.tmpdir(), 'audit-')));
    const pasta = path.join(base, APP);
    fs.cpSync(path.join(__dirname, 'fixture', APP), pasta, { recursive: true });
    iniciar(pasta);
    const h = await conectar(PORTA);
    if (!await pronto()) throw new Error('auditor did not start');
    await dormir(5000);
    const arquivo = path.join(pasta, APP === 'java' ? 'src/Main.java' : 'app.js');
    for (const etapa of [
        () => APP === 'java' ? java(h, pasta) : null,
        () => comandos(h),
        () => APP === 'java' ? teclado(h, arquivo) : null,
        () => APP === 'java' ? criacao(h, pasta) : null,
        () => APP === 'java' ? gerar(h, pasta) : null,
        () => APP === 'java' ? sugestoes(h, pasta) : null,
        () => autosave(h, arquivo),
        () => temas(h),
    ]) {
        try { await etapa(); } catch (e) { falha('audit step crashed', e.message); }
    }
    fs.writeFileSync(path.join(SAIDA, `audit-${APP}.json`), JSON.stringify(relatorio, null, 2));
    await h.fechar();
    await fechado(PORTA);
    console.log(relatorio.falhas.length ? `${relatorio.falhas.length} failed` : 'all passed');
    process.exit(relatorio.falhas.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
