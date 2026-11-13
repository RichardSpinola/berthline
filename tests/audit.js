// Audits a built package: commands, shortcuts, menus, themes and editor behaviour.
// Usage: node tests/audit.js <package> <java|web|standard>
const fs = require('fs'), os = require('os'), path = require('path'), http = require('http');
const { spawn, spawnSync } = require('child_process');
const { SAIDA, dormir, conectar, fechado } = require('./cdp');

const PACOTE = path.resolve(process.argv[2]);
const APP = process.argv[3] || 'java';
const PORTA = +process.env.AUDIT_PORT || 9334; // AUDIT_PORT lets two audits run side by side
const RPC = PORTA + 1;
const JANELAS = process.platform === 'win32';
const HUB = path.join(PACOTE, JANELAS ? 'Hub.exe' : 'Hub');
const INSEGUROS = /^ij\.(newProject|reload|gitPush|gitPull|safeDelete|openFiles)$/;
const MODIF = { alt: 1, ctrl: 2, shift: 8 };
const MOLDURA = '38,40,44'; // #26282C, the Islands Dark frame set in profiles/java/settings.json
const relatorio = { app: APP, plataforma: process.platform, falhas: [], avisos: [], dados: {} };

const falha = (nome, extra = '') => { relatorio.falhas.push(`${nome} ${extra}`.trim()); console.log('FAIL ', nome, extra); };
const certo = (nome, extra = '') => console.log('OK   ', nome, extra);
const conferir = (nome, ok, extra = '') => (ok ? certo : falha)(nome, extra);
const aviso = (nome, extra = '') => { relatorio.avisos.push(`${nome} ${extra}`.trim()); console.log('NOTE ', nome, extra); };

const rpc = (acao, dados = {}) => new Promise((ok, nao) => {
    const r = http.request({ host: '127.0.0.1', port: RPC, method: 'POST' }, res => {
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
        SUITE_WATERMARK: path.join(usuario, 'watermark.svg'), SUITE_HUB: HUB, AUDIT_RPC_PORT: String(RPC) };
    delete env.ELECTRON_RUN_AS_NODE;
    const args = [`--user-data-dir=${path.join(usuario, 'user')}`, `--extensions-dir=${path.join(usuario, 'extensions')}`,
        `--extensionDevelopmentPath=${path.join(__dirname, 'auditor')}`, `--remote-debugging-port=${PORTA}`, pasta];
    // AUDIT_OZONE=headless runs without a window on screen
    if (!JANELAS) args.unshift(`--ozone-platform=${process.env.AUDIT_OZONE || 'x11'}`);
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
        // A removal ("-cmd") never runs anything; it only drops a binding an extension adds,
        // often for a command that registers later or belongs to a language this app lacks (VS Code keymap)
        const c = k.command;
        if (!c.startsWith('-') && !todos.has(c)) falha('shortcut has no command', `${k.key} -> ${c}`);
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
        if (process.env.AUDIT_VERBOSE) console.log('run', c);
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
    // Debug can start a real session (a browser where one is installed); the status bar would keep its debugging colour
    for (let i = 0; i < 3; i++) {
        await rpc('executar', { comando: 'workbench.action.debug.stop' }).catch(() => {});
        await dormir(500);
    }
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
    // "Run (Shift+F10)" with IntelliJ keys, plain "Run" with VS Code keys
    const rodar = botoes.filter(b => /^Run( Java| or Debug| \(|$)/.test(b));
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
    // The dialog first looks up the target folder through the clipboard, which can take a while;
    // typing before it shows sends the name to whatever has focus (the search view, once)
    const aberto = await h.ate(async () => /New Java Class/.test(await h.ev(`(()=>{const w=document.querySelector('.quick-input-widget');return w&&w.style.display!=='none'?w.querySelector('.quick-input-title')?.innerText??'':''})()`)), 10000);
    if (!aberto) falha('new class dialog opens', texto);
    await h.ev(`document.querySelector('.quick-input-box input')?.focus()`);
    await dormir(200);
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

// True when the label for this file, in the tabs or the tree, shows the icon of this type
const iconeDe = (h, onde, arquivo, tipo) => h.ev(`(()=>{
const e=[...document.querySelectorAll(${JSON.stringify(onde)})].find(e=>e.classList.contains(${JSON.stringify(`${arquivo}.java-name-file-icon`)}));
if(!e)return false;
const v=getComputedStyle(document.documentElement).getPropertyValue(${JSON.stringify(`--ij-icone-${tipo}`)}).trim();
return !!v&&getComputedStyle(e,'::before').backgroundImage.replace(/"/g,'')===v})()`);

// Opens a file that may still be on its way: right after a rename the editor can answer
// "Unable to resolve nonexistent file" for a moment. Returns '' or the last reason it could not open.
async function abrirQuando(h, arquivo, limite = 20000) {
    let motivo = '';
    const abriu = await h.ate(async () => {
        if (!fs.existsSync(arquivo)) { motivo = 'not on disk yet'; return false; }
        try { await rpc('abrir', { arquivo }); return true; } catch (e) { motivo = e.message; return false; }
    }, limite);
    return abriu ? '' : motivo || 'could not open';
}

async function iconesReais(h, pasta) {
    const ABA = '.tabs-container .tab .monaco-icon-label', ARVORE = '.explorer-folders-view .monaco-icon-label';
    for (const nome of ['one', 'two']) fs.mkdirSync(path.join(pasta, 'src', nome), { recursive: true });
    const umItem = path.join(pasta, 'src/one/Item.java'), doisItem = path.join(pasta, 'src/two/Item.java');
    fs.writeFileSync(umItem, 'public class Item {\n}\n');
    fs.writeFileSync(doisItem, 'public enum Item {\n    A\n}\n');
    await dormir(1500);
    await rpc('abrir', { arquivo: umItem });
    const umaAba = async tipo => iconeDe(h, ABA, 'item', tipo);
    conferir('tab shows the class icon', await h.ate(() => umaAba('class'), 5000));
    await rpc('executar', { comando: 'workbench.action.closeAllEditors' });
    await rpc('abrir', { arquivo: doisItem });
    conferir('same name in another package keeps its own icon', await h.ate(() => umaAba('enum'), 5000));
    await rpc('executar', { comando: 'workbench.action.closeAllEditors' });
    await rpc('abrir', { arquivo: umItem });
    fs.writeFileSync(umItem, 'public interface Item {\n}\n');
    const inicio = Date.now();
    conferir('icon follows a type change, no reload', await h.ate(() => umaAba('interface'), 8000), `${Date.now() - inicio} ms`);
    const nomes = await h.ev(`[...document.querySelectorAll('.tabs-container .tab .label-name')].map(e=>e.innerText)`);
    conferir('tab hides .java', nomes.length > 0 && nomes.every(n => !n.endsWith('.java')), nomes.join(' | '));
    fs.renameSync(path.join(pasta, 'src/Oops.java'), path.join(pasta, 'src/Failure.java'));
    conferir('icon follows a rename', await h.ate(() => iconeDe(h, ARVORE, 'failure', 'exception'), 8000));
    fs.writeFileSync(path.join(pasta, 'src/Fresh.java'), 'public record Fresh(int a) {\n}\n');
    conferir('new file gets its icon', await h.ate(() => iconeDe(h, ARVORE, 'fresh', 'record'), 8000));
    await rpc('executar', { comando: 'workbench.action.closeAllEditors' });
    const antes = path.join(pasta, 'src/two'), depois = path.join(pasta, 'src/three'), movido = path.join(depois, 'Item.java');
    await rpc('renomear', { de: antes, para: depois });
    if (!await h.ate(() => fs.existsSync(movido) && !fs.existsSync(antes), 10000)) {
        // The Java extension can hold the rename behind a question that nobody answers here
        aviso('package rename did not land through the editor', 'renamed on disk instead');
        if (fs.existsSync(antes) && !fs.existsSync(depois)) fs.renameSync(antes, depois);
    }
    const falha = await abrirQuando(h, movido);
    conferir('icon survives a package rename', !falha && await h.ate(() => umaAba('enum'), 5000), falha);
    await rpc('executar', { comando: 'workbench.action.closeAllEditors' });
    for (const nome of ['Main', 'Pet', 'Shape', 'Color', 'Point', 'Failure']) await rpc('abrir', { arquivo: path.join(pasta, `src/${nome}.java`) });
    await dormir(800);
    await h.foto('audit-java-tabs');
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
    const limpo = (await rpc('estado')).texto;
    for (const [escrito, esperado] of [['sout', 'System.out.println(name);'], ['var', 'var valor = name;']]) {
        await rpc('cursor', { linha: 5, coluna: 0 });
        await dormir(400); // the cursor moves through the extension host, after the call returns
        // Real key presses: this is what opens and filters the list for a person
        for (const text of `name.${escrito}`) {
            await h.c('Input.dispatchKeyEvent', { type: 'keyDown', text, key: text, unmodifiedText: text });
            await h.c('Input.dispatchKeyEvent', { type: 'keyUp', key: text });
            await dormir(120);
        }
        const noTopo = () => h.ev(`document.querySelector('.suggest-widget.visible .monaco-list-row.focused')?.getAttribute('aria-label') ?? ''`);
        await h.ate(async () => (await noTopo()).startsWith(escrito), 5000);
        const topo = await noTopo();
        await tecla(h, [], 'Enter', 'Enter', 13);
        await dormir(600);
        const pronto = (await rpc('estado')).texto.split('\n')[5];
        conferir(`postfix .${escrito} writes the code`, pronto.includes(esperado), `${pronto.trim()} (list top: ${topo})`);
        await rpc('executar', { comando: 'leaveSnippet' });
        await tecla(h, [], 'Escape', 'Escape', 27);
        await rpc('texto', { texto: limpo });
        await rpc('executar', { comando: 'workbench.action.files.save' });
        await dormir(400);
    }
    await rpc('cursor', { linha: 5, coluna: 0 });
    await dormir(400);
    await h.c('Input.insertText', { text: '        so' });
    await dormir(1200);
    const modelos = (await rpc('sugestoes', { linha: 5, coluna: 10 })).sort((a, b) => a.ordem.localeCompare(b.ordem)).map(s => s.rotulo);
    conferir('sout comes first', modelos[0] === 'sout', modelos.slice(0, 5).join(' | '));
    await rpc('texto', { texto: limpo });
    await rpc('executar', { comando: 'workbench.action.files.save' });
}

async function exportar(h, pasta) {
    await rpc('abrir', { arquivo: path.join(pasta, 'src/Main.java') });
    await dormir(800);
    const botoes = await h.ev(`[...document.querySelectorAll('.part.titlebar a.action-label, .editor-actions a.action-label')].map(e=>e.getAttribute('aria-label')||'')`);
    conferir('build button in the bar', botoes.some(b => b.startsWith('Build and Export')));
    const escolher = async nome => {
        await rpc('executar', { comando: 'ij.build', limite: 800 });
        await dormir(700);
        await h.c('Input.insertText', { text: nome });
        await dormir(300);
        await tecla(h, [], 'Enter', 'Enter', 13);
    };
    await escolher('Build Project');
    conferir('build reports success', await h.ate(async () => /Build finished/.test(await h.ev(`document.querySelector('.part.statusbar').innerText`)), 15000),
        `compile ${await rpc('compilar')}; ${(await rpc('todosErros')).join(' / ').slice(0, 300)}`);
    const quebrado = path.join(pasta, 'src/Broken.java');
    fs.writeFileSync(quebrado, 'public class Broken {\n    int x = ;\n}\n');
    await dormir(3000);
    await escolher('Rebuild Project');
    conferir('build reports failure', await h.ate(async () => /Build failed/.test(await h.ev(`[...document.querySelectorAll('.notification-toast')].map(e=>e.innerText).join(' ')`)), 20000));
    await rpc('executar', { comando: 'notifications.clearAll' });
    fs.rmSync(quebrado);
    await dormir(3000);
    await rpc('executar', { comando: 'ij.build', limite: 800 });
    await dormir(700);
    await h.foto('audit-java-build');
    await h.c('Input.insertText', { text: 'Export' });
    await dormir(300);
    await tecla(h, [], 'Enter', 'Enter', 13);
    const jar = path.join(pasta, `${path.basename(pasta)}.jar`);
    // The wizard asks for the main class only when it can't tell; Loop also has one and never ends, so name Main
    const pergunta = await h.ate(async () => /main/i.test(await h.ev(`document.querySelector('.quick-input-title')?.innerText ?? ''`)) || fs.existsSync(jar), 20000);
    if (pergunta && !fs.existsSync(jar)) {
        await h.foto('audit-java-export');
        // The build task opens a terminal and can take focus from the wizard
        console.log('wizard focus', await h.ev(`document.activeElement?.className ?? ''`));
        await h.ev(`document.querySelector('.quick-input-box input')?.focus()`);
        await h.c('Input.insertText', { text: 'Main' });
        await dormir(500);
        await tecla(h, [], 'Enter', 'Enter', 13);
    }
    // The last step lists what goes in the jar; the defaults are fine
    for (let i = 0; i < 6 && !fs.existsSync(jar); i++) {
        await dormir(1500);
        if (await h.ev(`document.querySelector('.quick-input-widget')?.style.display !== 'none'`)) await tecla(h, [], 'Enter', 'Enter', 13);
    }
    conferir('jar exported', await h.ate(() => fs.existsSync(jar), 15000), jar);
    const jre = path.join(PACOTE, `data/${APP}/extensions`, fs.readdirSync(path.join(PACOTE, `data/${APP}/extensions`)).find(n => n.startsWith('redhat.java')), 'jre');
    const javaBin = path.join(jre, fs.readdirSync(jre)[0], 'bin', JANELAS ? 'java.exe' : 'java');
    const saida = spawnSync(javaBin, ['-jar', jar], { input: 'Ana\n', encoding: 'utf8', timeout: 15000 });
    conferir('exported jar runs', /Hello, Ana!/.test(saida.stdout), (saida.stdout + saida.stderr).slice(0, 160));
    await rpc('executar', { comando: 'workbench.action.closeAllEditors' });
}

async function botoes(h, pasta) {
    await dormir(1000);
    const canto = await h.ev(`[...document.querySelectorAll('.part.activitybar .action-label')].filter(e=>e.getBoundingClientRect().width>0).map(e=>e.getAttribute('aria-label')||'')`);
    // Java hides the corner gear (the title bar has one); Web keeps the VS Code layout
    if (APP === 'java') conferir('one settings button', !canto.some(b => b.startsWith('Manage')), canto.join(' | '));
    if (APP === 'java') {
        const barra = () => h.ev(`[...document.querySelectorAll('.part.statusbar .statusbar-item')].filter(e=>e.getBoundingClientRect().width>0).map(e=>e.id+'='+e.innerText.trim())`);
        const antes = await barra();
        conferir('no remote indicator', !antes.some(b => b.startsWith('status.host')), antes.join(' | '));
        conferir('no Git Log outside Git', !antes.some(b => b.includes('Git Log')), antes.join(' | '));
        // In a Git project Git Graph's item reads "Git Log"
        spawnSync('git', ['init', '-q'], { cwd: pasta });
        const git = await h.ate(async () => (await barra()).some(b => /Git Log$/.test(b)), 8000);
        const depois = await barra();
        conferir('Git Log in a Git project', git && !depois.some(b => b.includes('Git Graph')), depois.join(' | '));
        fs.rmSync(path.join(pasta, '.git'), { recursive: true, force: true });
    }
    await rpc('executar', { comando: 'workbench.view.explorer' });
    await dormir(600);
    await h.foto(`audit-${APP}-buttons`);
}

async function barraWeb(h, pasta) {
    // A plain page script, like a first project: no false type errors, no ESLint library warning
    const pagina = path.join(pasta, 'page.js');
    fs.writeFileSync(pagina, 'const card = document.querySelector(".card");\nconst button = card.querySelector("button");\nbutton.addEventListener("click", () => button.setAttribute("aria-expanded", card.classList.toggle("open")));\n');
    await rpc('abrir', { arquivo: pagina });
    await h.ate(async () => /JavaScript/.test(await h.status()), 15000);
    await dormir(6000);
    const erros = await rpc('erros', { arquivo: pagina });
    conferir('plain page script has no type errors', !erros.length, erros.join(' / ').slice(0, 200));
    const avisos = await h.ev(`[...document.querySelectorAll('.notification-toast')].map(e=>e.innerText).join(' / ')`);
    conferir('no ESLint library warning', !/ESLint library/.test(avisos), avisos.replace(/\s+/g, ' ').slice(0, 160));
    const ids = await h.ev(`[...document.querySelectorAll('.statusbar-item')].filter(e=>e.getBoundingClientRect().width>0).map(e=>e.id)`);
    for (const [id, nome] of [['status.host', 'remote indicator'], ['chat.statusBarEntry', 'Copilot Sign In'], ['asispts.neo-git-graph', '(neo) Git Graph']])
        conferir(`status bar hides ${nome}`, !ids.includes(id), ids.join(' | '));
    if (spawnSync('git', ['init', '-q', pasta]).status === 0)
        conferir('status bar shows Git Log in a repository', await h.ate(async () => /Git Log/.test(await h.status()), 20000), await h.status());
    await h.foto(`audit-${APP}-statusbar`);
}

// Standard is the plain editor: only the Hub button and its extension, nothing from the other profiles
async function padrao(h) {
    const todos = new Set(await rpc('comandos'));
    relatorio.dados.comandos = todos.size;
    const nossa = await rpc('contribuicoes', { id: 'berthline.berthline-hub' });
    conferir('berthline-hub installed', !!nossa);
    for (const c of nossa?.commands ?? []) if (!todos.has(c.command)) falha('command not registered', c.command);
    conferir('no commands from other profiles', ![...todos].some(c => /^(ij|web)\./.test(c)));
    conferir('no other berthline extension', !await rpc('contribuicoes', { id: 'berthline.berthline-tools' }) && !await rpc('contribuicoes', { id: 'berthline.berthline-web' }));
    const teclas = path.join(PACOTE, 'data/standard/user/User/keybindings.json');
    const lista = fs.existsSync(teclas) ? JSON.parse(fs.readFileSync(teclas, 'utf8').replace(/^\s*\/\/.*$/gm, '').replace(/,(\s*[\]}])/g, '$1') || '[]') : [];
    conferir('editor keys untouched', !lista.length, `${lista.length} bindings`);
    const barra = await h.ev(`[...document.querySelectorAll('.part.statusbar .statusbar-item')].filter(e=>e.getBoundingClientRect().width>0).map(e=>e.innerText.trim())`);
    conferir('back to Hub in the status bar', barra.some(b => /Hub$/.test(b)), barra.join(' | '));
    const canto = await h.ev(`[...document.querySelectorAll('.part.activitybar .action-label')].filter(e=>e.getBoundingClientRect().width>0).map(e=>e.getAttribute('aria-label')||'')`);
    conferir('corner gear kept', canto.some(b => b.startsWith('Manage')), canto.join(' | '));
    conferir('seti icons', await rpc('ajuste', { chave: 'workbench.iconTheme' }) === 'vs-seti');
    // The person may pick another theme in the Hub; what matters is that it exists, or the editor falls back silently
    const tema = await rpc('ajuste', { chave: 'workbench.colorTheme' });
    conferir('colour theme exists', (await rpc('temas')).some(t => t.id === tema), tema);
    await rpc('executar', { comando: 'workbench.view.explorer' });
    await dormir(600);
    await h.foto('audit-standard-buttons');
}

async function temas(h) {
    const lista = await rpc('temas');
    relatorio.dados.temas = lista.length;
    // Without a window manager (Xvfb) the window can lose focus; the inactive title colours are not what we measure
    await h.c('Emulation.setFocusEmulationEnabled', { enabled: true });
    await h.c('Page.bringToFront');
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
    const arquivo = path.join(pasta, { java: 'src/Main.java', web: 'app.js', standard: 'hello.py' }[APP]);
    for (const etapa of [
        () => APP === 'java' ? java(h, pasta) : null,
        () => APP === 'java' ? exportar(h, pasta) : null, // needs the clean fixture, before other steps add files
        () => APP === 'web' ? barraWeb(h, pasta) : null,
        () => APP === 'standard' ? padrao(h) : botoes(h, pasta),
        () => APP === 'standard' ? null : comandos(h),
        () => APP === 'java' ? teclado(h, arquivo) : null,
        () => APP === 'java' ? criacao(h, pasta) : null,
        () => APP === 'java' ? iconesReais(h, pasta) : null,
        () => APP === 'java' ? gerar(h, pasta) : null,
        () => APP === 'java' ? sugestoes(h, pasta) : null,
        () => APP === 'standard' ? null : autosave(h, arquivo), // Standard keeps the editor's own autosave (off)
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
