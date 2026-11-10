// Shared by the profile extensions (Java, Web): the build copies this folder into each one.
const vscode = require('vscode');

const FERRAMENTAS = process.env.SUITE_TOOLS ?? require('path').join(require('os').homedir(), '.config', 'berthline');

let contexto;
let prefixo = 'ij';
const chave = nome => `${prefixo}.${nome}`;

// Pequenas animações, como as do IntelliJ
function estiloAnimacao(context) {
    const css = `@keyframes ijEntra { from { opacity: 0; transform: translateY(-3px); } to { opacity: 1; transform: none; } }
.suggest-widget.visible, .quick-input-widget, .context-view .monaco-menu-container, .monaco-hover, .notification-toast { animation: ijEntra 110ms ease-out; }
.monaco-list-row, .tabs-container .tab, .action-item .action-label { transition: background-color 90ms ease, color 90ms ease; }`;
    return naJanela(context, `(()=>{const s=document.getElementById('ij-anim')||document.head.appendChild(Object.assign(document.createElement('style'),{id:'ij-anim'}));s.textContent=${JSON.stringify(css)};})()`);
}

// Terminal da execução atual: Run sem sessão de debug, como a janela Run do IntelliJ
let execucao;

function nodeDaSuite() {
    const pronto = process.env.SUITE_NODE;
    if (pronto) return pronto;
    return process.platform === 'win32' ? 'node.exe' : process.execPath;
}

function abrirRun({ nome, cwd, env, aoFim, comando, repetir }) {
    const fs = require('fs'), path = require('path');
    execucao?.terminal.dispose();
    fs.mkdirSync(contexto.globalStorageUri.fsPath, { recursive: true });
    const marca = path.join(contexto.globalStorageUri.fsPath, `fim-${Date.now()}`);
    const node = nodeDaSuite();
    const terminal = vscode.window.createTerminal({
        name: nome ?? 'Run',
        iconPath: new vscode.ThemeIcon('play'),
        cwd,
        env: { ...env, ELECTRON_RUN_AS_NODE: '1' },
        shellPath: node,
        shellArgs: [path.join(__dirname, 'runner.js'), marca, ...comando],
    });
    execucao = { terminal, repetir, marca };
    vscode.commands.executeCommand('setContext', chave('emExecucao'), true);
    aguardarFim(terminal, marca, () => {
        vscode.commands.executeCommand('setContext', chave('emExecucao'), false);
        aoFim?.();
    });
    terminal.show(false);
    vscode.commands.executeCommand('setContext', chave('rodando'), true);
}

function pararExecucao() {
    if (vscode.debug.activeDebugSession) return vscode.commands.executeCommand('workbench.action.debug.stop');
    if (!execucao) return;
    execucao.terminal.sendText('\x03', false);
    // Reforço para terminais em que o Ctrl+C não chega ao programa
    const { marca } = execucao;
    setTimeout(() => {
        if (execucao?.marca === marca && !require('fs').existsSync(marca)) require('fs').writeFileSync(`${marca}.stop`, '');
    }, 1500);
}

function reexecutar() {
    if (vscode.debug.activeDebugSession) return vscode.commands.executeCommand('workbench.action.debug.restart');
    return execucao?.repetir();
}

function aguardarFim(terminal, marca, aoFim) {
    const fs = require('fs');
    const espera = setInterval(() => {
        if (execucao?.terminal !== terminal) return clearInterval(espera);
        if (!fs.existsSync(marca)) return;
        clearInterval(espera);
        fs.rmSync(marca, { force: true });
        aoFim();
    }, 500);
}

// Extensões novas abrem uma aba de novidades na primeira vez; fecha sem incomodar
function fecharNovidades() {
    setTimeout(() => {
        for (const grupo of vscode.window.tabGroups.all) {
            for (const aba of grupo.tabs) {
                if (/^What's New/.test(aba.label)) vscode.window.tabGroups.close(aba).then(undefined, () => {});
            }
        }
    }, 6000);
}

// Caminho do arquivo no rodapé, como a barra de navegação do IntelliJ
function caminhoRodape(item) {
    const doc = vscode.window.activeTextEditor?.document;
    if (!doc || doc.uri.scheme !== 'file') {
        item.hide();
        return;
    }
    const partes = vscode.workspace.asRelativePath(doc.uri, true).split('/');
    partes[partes.length - 1] = partes[partes.length - 1].replace(/\.java$/, '');
    item.text = partes.join(' $(chevron-right) ');
    item.show();
}

// Linha com breakpoint fica vermelha, como no IntelliJ
const LINHA_BREAKPOINT = vscode.window.createTextEditorDecorationType({
    isWholeLine: true,
    light: { backgroundColor: '#FAD4D4' },
    dark: { backgroundColor: '#5A2B2F' }
});

function pintarBreakpoints() {
    for (const editor of vscode.window.visibleTextEditors) {
        const faixas = vscode.debug.breakpoints
            .filter(b => b instanceof vscode.SourceBreakpoint && b.enabled && b.location.uri.toString() === editor.document.uri.toString())
            .map(b => b.location.range);
        editor.setDecorations(LINHA_BREAKPOINT, faixas);
    }
}

// Comando pedido pela tela de início para a janela que acabou de abrir
function comandoPendente() {
    const fs = require('fs');
    const arquivo = require('path').join(FERRAMENTAS, 'ao-abrir');
    if (!fs.existsSync(arquivo)) return;
    const comando = fs.readFileSync(arquivo, 'utf8').trim();
    fs.unlinkSync(arquivo);
    if (comando) vscode.commands.executeCommand(comando);
}

// Foto de fundo aplicada só nesta janela do editor, sem alterar arquivos internos
const IMAGEM = require('path').join(FERRAMENTAS, 'fundo.jpg');
const OPCOES = require('path').join(FERRAMENTAS, 'opcoes.json');
const FORCA_PADRAO = 0.1;

function lerOpcoes() {
    try {
        return JSON.parse(require('fs').readFileSync(OPCOES, 'utf8'));
    } catch {
        return {};
    }
}

async function naJanela(context, expressao) {
    const fs = require('fs'), path = require('path');
    const dados = path.resolve(context.globalStorageUri.fsPath, '..', '..', '..');
    const porta = fs.readFileSync(path.join(dados, 'DevToolsActivePort'), 'utf8').split('\n')[0];
    const paginas = await (await fetch(`http://127.0.0.1:${porta}/json/list`)).json();
    let valor;
    for (const pagina of paginas.filter(p => p.type === 'page')) {
        await new Promise(pronto => {
            const ws = new WebSocket(pagina.webSocketDebuggerUrl);
            ws.onopen = () => ws.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate', params: { expression: expressao } }));
            ws.onmessage = mensagem => { ws.close(); valor = JSON.parse(mensagem.data).result?.result?.value; pronto(); };
            ws.onerror = pronto;
        });
    }
    return valor;
}

// Ícone do app, em cinza, na tela vazia do editor
function marcaDagua(context) {
    const fs = require('fs'), arquivo = process.env.SUITE_WATERMARK;
    if (!arquivo || !fs.existsSync(arquivo)) return Promise.resolve();
    const url = `data:image/svg+xml;base64,${fs.readFileSync(arquivo).toString('base64')}`;
    const css = `.editor-group-letterpress, .editor-group-watermark .letterpress { background-image: url(${url}) !important; }`;
    return naJanela(context, `(()=>{const s=document.getElementById('ij-marca')||document.head.appendChild(Object.assign(document.createElement('style'),{id:'ij-marca'}));s.textContent=${JSON.stringify(css)}})()`);
}

function fundoEditor(context) {
    const fs = require('fs');
    const forca = lerOpcoes().fundo ?? FORCA_PADRAO;
    const url = fs.existsSync(IMAGEM) ? `data:image/jpeg;base64,${fs.readFileSync(IMAGEM).toString('base64')}` : '';
    const css = url && `.part.editor .editor-instance::after { content: ''; position: absolute; inset: 0; pointer-events: none; z-index: 30;
        opacity: var(--ij-fundo, ${forca}); background: url(${url}) center / cover no-repeat; }`;
    return naJanela(context, `(()=>{const s=document.getElementById('ij-fundo')||document.head.appendChild(Object.assign(document.createElement('style'),{id:'ij-fundo'}));s.textContent=${JSON.stringify(css)};document.documentElement.style.setProperty('--ij-fundo','${forca}')})()`);
}

function gravarForca(valor) {
    require('fs').writeFileSync(OPCOES, JSON.stringify({ ...lerOpcoes(), fundo: valor }));
}

function paginaFundo(forca) {
    return `<!doctype html><html><head><meta charset="utf-8"><style>
body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 24px; max-width: 460px; }
h2 { font-size: 15px; margin: 0 0 18px; }
label { display: block; margin-bottom: 8px; }
input[type=range] { width: 100%; accent-color: var(--vscode-focusBorder); }
.botoes { margin-top: 20px; display: flex; gap: 8px; }
button { background: transparent; color: inherit; border: 1px solid var(--vscode-panel-border, currentColor); border-radius: 4px; padding: 5px 13px; cursor: pointer; }
button:hover { background: var(--vscode-toolbar-hoverBackground); }
</style></head><body>
<h2>Editor Background</h2>
<label>Strength: <span id="valor">${Math.round(forca * 100)}%</span></label>
<input id="forca" type="range" min="3" max="40" value="${Math.round(forca * 100)}">
<div class="botoes"><button id="escolher">Choose Image…</button><button id="remover">Remove Image</button></div>
<script>
const vscode = acquireVsCodeApi();
const forca = document.getElementById('forca');
forca.addEventListener('input', () => {
    document.getElementById('valor').textContent = forca.value + '%';
    vscode.postMessage({ acao: 'forca', valor: Number(forca.value) / 100 });
});
for (const acao of ['escolher', 'remover']) {
    document.getElementById(acao).addEventListener('click', () => vscode.postMessage({ acao }));
}
</script></body></html>`;
}

async function trocarFundo(context) {
    const [arquivo] = await vscode.window.showOpenDialog({
        title: 'Background image', filters: { Images: ['jpg', 'jpeg', 'png', 'webp', 'bmp'] },
    }) ?? [];
    if (!arquivo) return;
    const { status } = require('child_process').spawnSync(process.env.SUITE_HUB, ['--background', arquivo.fsPath]);
    if (status !== 0) return vscode.window.showErrorMessage('Could not read this image.');
    return fundoEditor(context).catch(avisarReabrir);
}

function avisarReabrir() {
    vscode.window.showInformationMessage('Saved. Close the editor and open a project again to see it.');
}

// Como o IntelliJ: erro só aparece quando a digitação para
const PAUSA_ANALISE = 500;
let digitando = false;
let fimDigitacao;

function estiloPausa(context) {
    const css = '.ij-digitando .squiggly-error, .ij-digitando .squiggly-warning, .ij-digitando .squiggly-info { visibility: hidden; }';
    return naJanela(context, `(()=>{const s=document.getElementById('ij-pausa')||document.head.appendChild(Object.assign(document.createElement('style'),{id:'ij-pausa'}));s.textContent=${JSON.stringify(css)}})()`);
}

function aoDigitar(context, evento) {
    if (evento.document.uri.scheme !== 'file' || !evento.contentChanges.length) return;
    if (!digitando) {
        digitando = true;
        naJanela(context, "document.body.classList.add('ij-digitando')").catch(() => {});
    }
    clearTimeout(fimDigitacao);
    fimDigitacao = setTimeout(() => {
        digitando = false;
        naJanela(context, "document.body.classList.remove('ij-digitando')").catch(() => {});
    }, PAUSA_ANALISE);
}

// Avisa no rodapé se uma atualização do editor quebrar os ajustes visuais
async function conferirSaude(context, saudavel) {
    if (process.env.SUITE_VISUAL === '0') return;
    await new Promise(pronto => setTimeout(pronto, 10000));
    const expressao = `!!(document.querySelector('.part.editor') && document.querySelector('.part.sidebar') && document.getElementById('ij-pausa')) && ${saudavel}`;
    const ok = await naJanela(context, expressao).catch(() => false);
    if (ok) return;
    const aviso = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 0);
    aviso.text = '$(warning) Visual extras: partial';
    aviso.tooltip = 'Visual tweaks are off. Open the editor from the Welcome screen, or the editor update changed something. Your code is safe.';
    aviso.show();
    context.subscriptions.push(aviso);
}

let painelFundo;

function abrirPainelFundo(context) {
    if (painelFundo) return painelFundo.reveal();
    painelFundo = vscode.window.createWebviewPanel('ijFundo', 'Editor Background', vscode.ViewColumn.Active, { enableScripts: true });
    painelFundo.webview.html = paginaFundo(lerOpcoes().fundo ?? FORCA_PADRAO);
    painelFundo.onDidDispose(() => { painelFundo = undefined; });
    painelFundo.webview.onDidReceiveMessage(({ acao, valor }) => {
        if (acao === 'escolher') return trocarFundo(context);
        if (acao === 'remover') {
            require('fs').rmSync(IMAGEM, { force: true });
            return fundoEditor(context).catch(avisarReabrir);
        }
        gravarForca(valor);
        naJanela(context, `document.documentElement.style.setProperty('--ij-fundo','${valor}')`).catch(avisarReabrir);
    });
}

async function menuConfiguracoes() {
    const itens = [
        { label: 'Settings', comando: 'workbench.action.openSettings' },
        { label: 'Editor Background…', comando: `${prefixo}.customizeBackground` },
        { label: 'Theme…', comando: 'workbench.action.selectTheme' },
        { label: 'Keymap', comando: 'workbench.action.openGlobalKeybindings' },
        { label: 'Plugins', comando: 'workbench.view.extensions' },
    ];
    const escolha = await vscode.window.showQuickPick(itens, { placeHolder: 'Settings' });
    if (escolha) vscode.commands.executeCommand(escolha.comando);
}

// A engrenagem do topo já leva a tudo; a do canto só repetia o mesmo botão
function umaEngrenagem(context) {
    const css = '.part.activitybar .action-item:has(.action-label[aria-label^="Manage"]) { display: none !important; }';
    return naJanela(context, `(()=>{const s=document.getElementById('ij-gear')||document.head.appendChild(Object.assign(document.createElement('style'),{id:'ij-gear'}));s.textContent=${JSON.stringify(css)}})()`);
}

function ativarComum(context, opcoes) {
    contexto = context;
    prefixo = opcoes.prefixo;
    // The Web profile keeps the plain VS Code look: only the background and watermark, none of the IntelliJ touches
    const intellij = opcoes.estilo !== 'vscode';
    fundoEditor(context).catch(() => {});
    marcaDagua(context).catch(() => {});
    if (intellij) {
        estiloPausa(context).catch(() => {});
        if (process.env.SUITE_ANIMATIONS !== '0') estiloAnimacao(context).catch(() => {});
        umaEngrenagem(context).catch(() => {});
        conferirSaude(context, opcoes.saudavel ?? 'true');
    }
    comandoPendente();
    fecharNovidades();
    pintarBreakpoints();

    if (intellij) {
        const rodape = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 1000);
        rodape.command = 'workbench.action.quickOpen';
        caminhoRodape(rodape);
        context.subscriptions.push(
            rodape,
            vscode.window.onDidChangeActiveTextEditor(() => caminhoRodape(rodape)),
            vscode.workspace.onDidChangeTextDocument(evento => aoDigitar(context, evento)));
    }
    context.subscriptions.push(
        vscode.debug.onDidChangeBreakpoints(pintarBreakpoints),
        vscode.window.onDidChangeVisibleTextEditors(pintarBreakpoints),
        vscode.commands.registerCommand(chave('stop'), pararExecucao),
        vscode.commands.registerCommand(chave('rerun'), reexecutar),
        vscode.commands.registerCommand(chave('search'), () => vscode.commands.executeCommand('workbench.action.quickOpen')),
        vscode.commands.registerCommand(chave('settings'), menuConfiguracoes),
        vscode.commands.registerCommand(chave('customizeBackground'), () => abrirPainelFundo(context)),
        vscode.window.onDidCloseTerminal(fechado => {
            if (fechado !== execucao?.terminal) return;
            execucao = undefined;
            vscode.commands.executeCommand('setContext', chave('rodando'), false);
            vscode.commands.executeCommand('setContext', chave('emExecucao'), false);
        })
    );
}

module.exports = { ativarComum, abrirRun, naJanela, nodeDaSuite };
