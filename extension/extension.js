const vscode = require('vscode');

const FERRAMENTAS = process.env.SUITE_TOOLS ?? require('path').join(require('os').homedir(), '.config', 'berthline');
const ACOES = require('./acoes.json');

const MAIN = /\bstatic\s+void\s+main\s*\(|^\s*(public\s+)?void\s+main\s*\(/;

// Modelos postfix do IntelliJ que a extensão Java não oferece
const POSTFIX = {
    sout: 'System.out.println(E);$0',
    soutv: 'System.out.println("E = " + E);$0',
    serr: 'System.err.println(E);$0',
    souf: 'System.out.printf(E$1);$0',
    return: 'return E;$0',
    par: '(E)$0',
    nn: 'if (E != null) {\n\t$0\n}',
    notnull: 'if (E != null) {\n\t$0\n}',
    fori: 'for (int ${1:i} = 0; $1 < E; $1++) {\n\t$0\n}',
    forr: 'for (int ${1:i} = E - 1; $1 >= 0; $1--) {\n\t$0\n}',
    iter: 'for (var ${1:item} : E) {\n\t$0\n}',
    try: 'try {\n\tE;\n} catch (${1:Exception} ${2:e}) {\n\t$0\n}',
    twr: 'try (var ${1:recurso} = E) {\n\t$0\n}',
    new: 'new E($1)$0',
    castvar: 'var ${2:valor} = (${1:Tipo}) E;$0',
    opt: 'java.util.Optional.ofNullable(E)$0',
    stream: 'java.util.Arrays.stream(E)$0',
    lambda: '() -> E$0',
    arg: '${1:metodo}(E)$0',
    assert: 'assert E;$0',
    switch: 'switch (E) {\n\tcase $1 -> $0\n}',
    synchronized: 'synchronized (E) {\n\t$0\n}',
    inst: 'E instanceof ${1:Tipo}$0',
    format: 'String.format(E$1)$0',
    reqnonnull: 'java.util.Objects.requireNonNull(E)$0'
};
const EXPRESSAO = /((?:"(?:[^"\\]|\\.)*"|\([^()]*\)|[\w$]+(?:\([^()]*\)|\[[^\]]*\])*)(?:\.[\w$]+(?:\([^()]*\)|\[[^\]]*\])*)*)\.(\w*)$/;

function postfix(doc, pos) {
    const m = doc.lineAt(pos.line).text.slice(0, pos.character).match(EXPRESSAO);
    if (!m) return [];
    const inicio = pos.character - m[0].length;
    const faixa = new vscode.Range(pos.line, inicio, pos.line, pos.character);
    return Object.entries(POSTFIX).map(([nome, corpo]) => {
        const item = new vscode.CompletionItem(nome, vscode.CompletionItemKind.Keyword);
        item.insertText = new vscode.SnippetString(corpo.replaceAll('$', '\u0000').replace(/E(?=[^\w]|$)/g, m[1].replaceAll('$', '\\$')).replaceAll('\u0000', '$'));
        item.range = faixa;
        item.filterText = `${m[1]}.${nome}`;
        item.detail = 'Postfix';
        item.sortText = `z${nome}`;
        return item;
    });
}

// Live templates: lista única, com o atalho exato no topo como no IntelliJ
function carregarModelos(context) {
    const fs = require('fs'), path = require('path');
    const arquivo = path.join(context.globalStorageUri.fsPath, '..', '..', 'snippets', 'java.json');
    try {
        const lidos = JSON.parse(fs.readFileSync(arquivo, 'utf8').replace(/^\s*\/\/.*$/gm, ''));
        return Object.values(lidos).flatMap(m => [m.prefix].flat().map(prefixo => ({
            prefixo, descricao: m.description ?? '', corpo: [m.body].flat().join('\n'),
        })));
    } catch {
        return [];
    }
}

function sugerirModelos(modelos, doc, pos) {
    const antes = doc.lineAt(pos.line).text.slice(0, pos.character);
    const palavra = antes.match(/(?:^|[^\w.$])([A-Za-z][\w-]*)$/)?.[1];
    if (!palavra || antes.includes('//') || (antes.match(/"/g)?.length ?? 0) % 2) return [];
    const faixa = new vscode.Range(pos.line, pos.character - palavra.length, pos.line, pos.character);
    return modelos.filter(m => m.prefixo.startsWith(palavra)).map(m => {
        const item = new vscode.CompletionItem({ label: m.prefixo, description: m.descricao }, vscode.CompletionItemKind.Keyword);
        item.insertText = new vscode.SnippetString(m.corpo);
        item.range = faixa;
        item.filterText = m.prefixo;
        item.sortText = `!${m.prefixo}`;
        item.preselect = m.prefixo === palavra;
        return item;
    });
}

// Janela única de New Java Class, como no IntelliJ
const TIPOS_NOVOS = [
    { label: 'Class', icone: 'class', codigo: n => `public class ${n} {\n    \n}\n`, cursor: [1, 4] },
    { label: 'Interface', icone: 'interface', codigo: n => `public interface ${n} {\n    \n}\n`, cursor: [1, 4] },
    { label: 'Record', icone: 'record', codigo: n => `public record ${n}() {\n}\n`, cursor: [0, n => `public record ${n}(`.length] },
    { label: 'Enum', icone: 'enum', codigo: n => `public enum ${n} {\n    \n}\n`, cursor: [1, 4] },
    { label: 'Annotation', icone: 'annotation', codigo: n => `public @interface ${n} {\n    \n}\n`, cursor: [1, 4] },
];

async function pastaDestino(uri) {
    let alvo = uri;
    if (!alvo) {
        const guardado = await vscode.env.clipboard.readText();
        await vscode.commands.executeCommand('copyFilePath').then(undefined, () => {});
        const caminho = (await vscode.env.clipboard.readText()).split('\n')[0];
        await vscode.env.clipboard.writeText(guardado);
        if (caminho !== guardado && require('path').isAbsolute(caminho)) alvo = vscode.Uri.file(caminho);
    }
    const ativo = vscode.window.activeTextEditor?.document.uri;
    alvo ??= (ativo?.scheme === 'file' ? ativo : vscode.workspace.workspaceFolders?.[0]?.uri);
    if (!alvo) return undefined;
    const info = await vscode.workspace.fs.stat(alvo);
    return info.type & vscode.FileType.Directory ? alvo : vscode.Uri.joinPath(alvo, '..');
}

function pacoteDe(pasta) {
    const partes = pasta.fsPath.split(require('path').sep);
    const java = partes.findLastIndex((p, i) => p === 'java' && partes[i - 2] === 'src');
    const raiz = java >= 0 ? java : partes.lastIndexOf('src');
    return raiz >= 0 ? partes.slice(raiz + 1) : [];
}

async function criarClasse(pasta, nome, tipo) {
    const partes = nome.replace(/\.java$/, '').split('.');
    const classe = partes.pop();
    const pacote = [...pacoteDe(pasta), ...partes].join('.');
    const arquivo = vscode.Uri.joinPath(pasta, ...partes, `${classe}.java`);
    const existe = await vscode.workspace.fs.stat(arquivo).then(() => true, () => false);
    if (existe) return `${classe} already exists`;
    const cabecalho = pacote ? `package ${pacote};\n\n` : '';
    await vscode.workspace.fs.writeFile(arquivo, Buffer.from(cabecalho + tipo.codigo(classe)));
    const linha = tipo.cursor[0] + (pacote ? 2 : 0);
    const coluna = typeof tipo.cursor[1] === 'function' ? tipo.cursor[1](classe) : tipo.cursor[1];
    const posicao = new vscode.Position(linha, coluna);
    await vscode.window.showTextDocument(arquivo, { selection: new vscode.Range(posicao, posicao), preview: false });
    return undefined;
}

async function novaClasse(uri) {
    const pasta = await pastaDestino(uri);
    if (!pasta) return vscode.window.showInformationMessage('Open a project first.');
    const janela = vscode.window.createQuickPick();
    janela.title = 'New Java Class';
    janela.placeholder = 'Name';
    janela.sortByLabel = false;
    janela.items = TIPOS_NOVOS.map(tipo => ({
        label: tipo.label,
        alwaysShow: true,
        iconPath: vscode.Uri.file(require('path').join(__dirname, 'icones', `${tipo.icone}_dark.svg`)),
        tipo,
    }));
    janela.onDidChangeValue(() => { janela.title = 'New Java Class'; });
    janela.onDidAccept(async () => {
        const nome = janela.value.trim();
        if (!/^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*(\.java)?$/.test(nome)) {
            janela.title = 'New Java Class: not a valid name';
            return;
        }
        const erro = await criarClasse(pasta, nome, janela.activeItems[0].tipo);
        if (erro) janela.title = `New Java Class: ${erro}`;
        else janela.dispose();
    });
    janela.onDidHide(() => janela.dispose());
    janela.show();
}

// Pequenas animações, como as do IntelliJ
function estiloAnimacao(context) {
    const css = `@keyframes ijEntra { from { opacity: 0; transform: translateY(-3px); } to { opacity: 1; transform: none; } }
.suggest-widget.visible, .quick-input-widget, .context-view .monaco-menu-container, .monaco-hover, .notification-toast { animation: ijEntra 110ms ease-out; }
.monaco-list-row, .tabs-container .tab, .action-item .action-label { transition: background-color 90ms ease, color 90ms ease; }`;
    return naJanela(context, `(()=>{const s=document.getElementById('ij-anim')||document.head.appendChild(Object.assign(document.createElement('style'),{id:'ij-anim'}));s.textContent=${JSON.stringify(css)};})()`);
}

// Java só aceita uma pasta vinda do Explorer; pela paleta não há nenhuma
function marcarFontes(comando, uri) {
    if (!uri) return vscode.window.showInformationMessage('Right-click a folder in the Explorer to use this.');
    return vscode.commands.executeCommand(comando, uri);
}

function executar(comando, uri) {
    const alvo = uri ?? vscode.window.activeTextEditor?.document.uri;
    if (!alvo) return;
    return vscode.commands.executeCommand(comando, alvo);
}

// Terminal da execução atual: Run sem sessão de debug, como a janela Run do IntelliJ
let execucao;

function javaDoEditor() {
    const fs = require('fs'), path = require('path');
    const pasta = path.join(vscode.extensions.getExtension('redhat.java').extensionPath, 'jre');
    return path.join(pasta, fs.readdirSync(pasta)[0], 'bin', process.platform === 'win32' ? 'java.exe' : 'java');
}

async function rodarDireto(uri, opcoes = {}) {
    const alvo = uri ?? vscode.window.activeTextEditor?.document.uri;
    if (!alvo) return;
    const doc = await vscode.workspace.openTextDocument(alvo);
    await doc.save();
    let info, status;
    try {
        status = await vscode.commands.executeCommand('java.workspace.compile', false);
        info = await vscode.commands.executeCommand('java.execute.workspaceCommand', 'java.project.getClasspaths',
            alvo.toString(), JSON.stringify({ scope: 'runtime' }));
    } catch {
        return executar('java.debug.runJavaFile', alvo);
    }
    // Erro em outro arquivo do projeto não impede rodar este
    const comErro = vscode.languages.getDiagnostics(alvo).some(d => d.severity === vscode.DiagnosticSeverity.Error);
    if (status === 0 || comErro) {
        vscode.commands.executeCommand('workbench.panel.markers.view.focus');
        return vscode.window.showErrorMessage('Build failed. Fix the errors and run again.');
    }
    const pacote = doc.getText().match(/^\s*package\s+([\w.]+)\s*;/m)?.[1];
    const classe = require('path').basename(alvo.fsPath, '.java');
    const principal = opcoes.principal ?? (pacote ? `${pacote}.${classe}` : classe);
    const classpath = info.classpaths.join(require('path').delimiter);
    abrirRun({
        nome: opcoes.nome,
        cwd: opcoes.cwd ?? vscode.workspace.getWorkspaceFolder(alvo)?.uri,
        env: opcoes.env,
        aoFim: opcoes.aoFim,
        comando: [javaDoEditor(), ...(opcoes.vm ?? []), '-cp', classpath, principal, ...(opcoes.args ?? [])],
        repetir: () => rodarDireto(alvo, opcoes),
    });
}

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
    vscode.commands.executeCommand('setContext', 'ij.emExecucao', true);
    aguardarFim(terminal, marca, () => {
        vscode.commands.executeCommand('setContext', 'ij.emExecucao', false);
        aoFim?.();
    });
    terminal.show(false);
    vscode.commands.executeCommand('setContext', 'ij.rodando', true);
}

// Web: HTML abre no Live Server; JS e TS rodam no Node da suíte
const LINGUAGENS_WEB = ['html', 'javascript', 'typescript'];

function arquivoWeb() {
    const doc = vscode.window.activeTextEditor?.document;
    return doc && LINGUAGENS_WEB.includes(doc.languageId) ? doc : undefined;
}

async function rodarWeb(doc) {
    await doc.save();
    if (doc.languageId === 'html') return vscode.commands.executeCommand('extension.liveServer.goOnline');
    abrirRun({
        nome: 'Run',
        cwd: vscode.workspace.getWorkspaceFolder(doc.uri)?.uri,
        comando: [nodeDaSuite(), doc.uri.fsPath],
        repetir: () => rodarWeb(doc),
    });
}

function navegadorWeb() {
    return process.platform === 'win32' ? { type: 'pwa-msedge' } : { type: 'pwa-chrome', runtimeExecutable: process.env.SUITE_BROWSER ?? 'vivaldi' };
}

async function depurarWeb(doc) {
    await doc.save();
    const pasta = vscode.workspace.getWorkspaceFolder(doc.uri);
    if (doc.languageId === 'html') {
        return vscode.debug.startDebugging(pasta, { ...navegadorWeb(), request: 'launch', name: 'Debug in Browser', file: doc.uri.fsPath, webRoot: pasta?.uri.fsPath });
    }
    return vscode.debug.startDebugging(pasta, { type: 'pwa-node', request: 'launch', name: 'Debug', program: doc.uri.fsPath, runtimeExecutable: nodeDaSuite(), console: 'integratedTerminal' });
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

// Run Configurations: ficam no launch.json do projeto, as mesmas do Debug
const CONFIG_ESCOLHIDA = 'configEscolhida';
let contexto;

function pastaAtual() {
    const uri = vscode.window.activeTextEditor?.document.uri;
    return (uri && vscode.workspace.getWorkspaceFolder(uri)) ?? vscode.workspace.workspaceFolders?.[0];
}

function todasConfigs(pasta) {
    return vscode.workspace.getConfiguration('launch', pasta?.uri).get('configurations') ?? [];
}

const configEditavel = c => c.type === 'java' && c.request === 'launch' && c.mainClass && !c.mainClass.includes('$');
const configsJava = pasta => todasConfigs(pasta).filter(configEditavel);

function configAtual() {
    const nome = contexto.workspaceState.get(CONFIG_ESCOLHIDA);
    return configsJava(pastaAtual()).find(c => c.name === nome);
}

function partes(valor) {
    if (Array.isArray(valor)) return valor;
    return (valor?.match(/"[^"]*"|'[^']*'|\S+/g) ?? []).map(p => p.replace(/^(["'])(.*)\1$/, '$2'));
}

function opcoesDe(config) {
    const pasta = pastaAtual();
    return {
        nome: config.name,
        principal: config.mainClass,
        args: partes(config.args),
        vm: partes(config.vmArgs),
        env: config.env,
        cwd: config.cwd?.replace('${workspaceFolder}', pasta.uri.fsPath),
    };
}

async function arquivoDe(config) {
    const simples = config.mainClass.split('.').pop();
    const achados = await vscode.workspace.findFiles(`**/${simples}.java`, '{**/target/**,**/build/**,**/out/**}', 20);
    const caminho = config.mainClass.replaceAll('.', '/') + '.java';
    const achado = achados.find(u => u.path.endsWith(`/${caminho}`)) ?? achados[0];
    if (!achado) vscode.window.showErrorMessage(`Main class not found: ${config.mainClass}`);
    return achado;
}

async function rodarSelecionado() {
    const web = arquivoWeb();
    if (web) return rodarWeb(web);
    const config = configAtual();
    if (!config) return rodarDireto();
    const uri = await arquivoDe(config);
    if (uri) return rodarDireto(uri, opcoesDe(config));
}

function depurarSelecionado() {
    const web = arquivoWeb();
    if (web) return depurarWeb(web);
    const config = configAtual();
    if (!config) return executar('java.debug.debugJavaFile');
    return vscode.debug.startDebugging(pastaAtual(), { console: 'integratedTerminal', ...config });
}

// O nome da configuração aparece dentro do próprio botão, como no IntelliJ
function mostrarConfig() {
    vscode.commands.executeCommand('setContext', 'ij.temConfig', configsJava(pastaAtual()).length > 0);
    const nome = JSON.stringify(`${configAtual()?.name ?? 'Current File'} \u25BE`);
    const alvo = 'a.action-label[aria-label^="Run Configurations"]';
    const css = `${alvo} { width: auto !important; max-width: 180px; height: auto !important; padding: 2px 6px !important; background: none !important; } ${alvo}::before { display: none !important; } ${alvo}::after { content: ${nome}; font-family: system-ui, 'Segoe UI', sans-serif !important; font-size: 11px !important; font-weight: 400 !important; line-height: 16px !important; white-space: nowrap; }`;
    return naJanela(contexto, `(()=>{const s=document.getElementById('ij-config')||document.head.appendChild(Object.assign(document.createElement('style'),{id:'ij-config'}));s.textContent=${JSON.stringify(css)};})()`).catch(() => {});
}

async function escolherConfig() {
    const configs = configsJava(pastaAtual());
    const atual = configAtual()?.name;
    const marca = nome => nome === (atual ?? 'Current File') ? '$(check) ' : '';
    const itens = [
        { label: `${marca('Current File')}Current File`, config: null },
        ...configs.map(c => ({ label: `${marca(c.name)}${c.name}`, description: c.mainClass, config: c })),
        { kind: vscode.QuickPickItemKind.Separator, label: '' },
        { label: '$(pulse) Run with Profiler', comando: 'ij.profile' },
        { label: '$(settings-gear) Edit Configurations...', comando: 'ij.editConfigs' },
    ];
    const escolha = await vscode.window.showQuickPick(itens, { placeHolder: 'Run Configurations' });
    if (!escolha) return;
    if (escolha.comando) return vscode.commands.executeCommand(escolha.comando);
    await contexto.workspaceState.update(CONFIG_ESCOLHIDA, escolha.config?.name);
    mostrarConfig();
}

let painelConfigs;

async function editarConfigs() {
    const pasta = pastaAtual();
    if (!pasta) return vscode.window.showInformationMessage('Open a project first.');
    if (painelConfigs) return painelConfigs.reveal();
    const achadas = await vscode.commands.executeCommand('java.execute.workspaceCommand', 'vscode.java.resolveMainClass').then(undefined, () => []);
    const classes = [...new Set((achadas ?? []).map(c => c.mainClass))];
    const painel = painelConfigs = vscode.window.createWebviewPanel('ijRunConfigs', 'Run/Debug Configurations', vscode.ViewColumn.Active, { enableScripts: true });
    painel.onDidDispose(() => { painelConfigs = undefined; });
    const dados = JSON.stringify({ configs: configsJava(pasta), classes, atual: configAtual()?.name }).replaceAll('<', '\\u003c');
    const html = require('fs').readFileSync(require('path').join(__dirname, 'runconfig.html'), 'utf8');
    painel.webview.html = html.replace('<script>', `<script type="application/json" id="dados">${dados}</script>\n<script>`);
    painel.webview.onDidReceiveMessage(async mensagem => {
        if (mensagem.acao === 'salvar') {
            const outras = todasConfigs(pasta).filter(c => !configEditavel(c));
            await vscode.workspace.getConfiguration('launch', pasta.uri).update('configurations', [...outras, ...mensagem.configs], vscode.ConfigurationTarget.WorkspaceFolder);
            await contexto.workspaceState.update(CONFIG_ESCOLHIDA, mensagem.atual);
            mostrarConfig();
        }
        painel.dispose();
    });
}

// Profiler: grava com o Java Flight Recorder do próprio JDK e mostra o resumo ao terminar
async function perfilar(uri) {
    const fs = require('fs'), path = require('path');
    const pasta = contexto.globalStorageUri.fsPath;
    fs.mkdirSync(pasta, { recursive: true });
    const gravacao = path.join(pasta, 'ultimo.jfr');
    const config = uri ? undefined : configAtual();
    const alvo = uri ?? (config ? await arquivoDe(config) : undefined);
    if (config && !alvo) return;
    const base = config ? opcoesDe(config) : {};
    return rodarDireto(alvo, {
        ...base,
        nome: `Profiler: ${base.nome ?? 'Current File'}`,
        vm: [...(base.vm ?? []), `-XX:StartFlightRecording=filename=${gravacao},settings=profile,dumponexit=true`, '-Xlog:jfr*=error'],
        aoFim: () => relatorioPerfil(gravacao),
    });
}

function relatorioPerfil(gravacao) {
    const { execFile } = require('child_process'), path = require('path');
    const jfr = path.join(path.dirname(javaDoEditor()), process.platform === 'win32' ? 'jfr.exe' : 'jfr');
    const secoes = [['Hot methods', 'hot-methods'], ['Memory allocation by class', 'allocation-by-class'], ['GC pauses', 'gc-pauses']];
    const ler = visao => new Promise(pronto => execFile(jfr, ['view', '--width', '130', visao, gravacao], { maxBuffer: 1 << 24 }, (erro, saida) => pronto(erro ? 'No data.' : saida.trim())));
    return Promise.all(secoes.map(([, visao]) => ler(visao))).then(textos => {
        const painel = vscode.window.createWebviewPanel('ijProfiler', 'Profiler', vscode.ViewColumn.Active, {});
        const limpar = s => s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
        const corpo = secoes.map(([titulo], i) => `<h3>${titulo}</h3><pre>${limpar(textos[i])}</pre>`).join('');
        painel.webview.html = `<!doctype html><meta charset="utf-8"><style>body{font:13px var(--vscode-font-family);color:var(--vscode-foreground)}pre{font:12px var(--vscode-editor-font-family);overflow:auto}h3{font-weight:600}</style>${corpo}`;
    });
}

// Watch e Breakpoints somem da fileira para o terminal caber; voltam pelo clique direito no título
async function abrirDebugComTerminal() {
    await moverTerminal('workbench.view.debug');
    if (contexto.globalState.get('debugEnxuto')) return;
    // Só funciona com o Debug já visível
    await new Promise(pronto => setTimeout(pronto, 300));
    for (const id of ['workbench.debug.watchExpressionsView', 'workbench.debug.breakPointsView']) {
        await vscode.commands.executeCommand(`${id}.removeView`).then(undefined, () => {});
    }
    contexto.globalState.update('debugEnxuto', true);
}

const moverTerminal = destino => vscode.commands.executeCommand('vscode.moveViews', { viewIds: ['terminal'], destinationId: destino }).then(undefined, () => {});

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

// Esconde uma vez os painéis que o IntelliJ não tem; voltam pelo clique direito nos títulos
async function esconderPaineis(context) {
    if (context.globalState.get('paineisEscondidos')) return;
    await new Promise(pronto => setTimeout(pronto, 4000));
    for (const id of ['javaProjectExplorer', 'timeline']) {
        await vscode.commands.executeCommand(`${id}.removeView`).then(undefined, () => {});
    }
    context.globalState.update('paineisEscondidos', true);
}

async function irMetodo(direcao) {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;
    const simbolos = await vscode.commands.executeCommand('vscode.executeDocumentSymbolProvider', editor.document.uri);
    const linhas = [];
    const colher = lista => (lista ?? []).forEach(s => {
        if (s.kind === vscode.SymbolKind.Method || s.kind === vscode.SymbolKind.Constructor) linhas.push(s.selectionRange.start);
        colher(s.children);
    });
    colher(simbolos);
    linhas.sort((a, b) => a.line - b.line);
    const atual = editor.selection.active.line;
    const destino = direcao > 0 ? linhas.find(p => p.line > atual) : linhas.reverse().find(p => p.line < atual);
    if (!destino) return;
    editor.selection = new vscode.Selection(destino, destino);
    editor.revealRange(new vscode.Range(destino, destino), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
}

// Antes de apagar, procura o nome da classe nos outros arquivos Java
async function exclusaoSegura(uri) {
    const alvo = uri ?? vscode.window.activeTextEditor?.document.uri;
    if (!alvo) return;
    const nome = alvo.path.split('/').pop().replace(/\.java$/, '');
    const palavra = new RegExp(`\\b${nome.replace(/[^\w$]/g, '')}\\b`);
    const usos = [];
    if (alvo.path.endsWith('.java')) {
        for (const arquivo of await vscode.workspace.findFiles('**/*.java', '**/{out,bin,target,build}/**')) {
            if (arquivo.toString() === alvo.toString()) continue;
            const texto = Buffer.from(await vscode.workspace.fs.readFile(arquivo)).toString('utf8');
            if (palavra.test(texto)) usos.push(vscode.workspace.asRelativePath(arquivo));
        }
    }
    if (usos.length) {
        const lista = usos.slice(0, 6).join(', ');
        const escolha = await vscode.window.showWarningMessage(`${nome} é usado em: ${lista}`, { modal: true }, 'Delete Anyway');
        if (escolha !== 'Delete Anyway') return;
    }
    return vscode.commands.executeCommand('moveFileToTrash', alvo);
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

// Árvore como a do IntelliJ: nome sem .java e o ícone real do tipo
const TIPO_JAVA = /^\s*((?:(?:public|protected|private|abstract|final|sealed|non-sealed|static|strictfp)\s+)*)(class|interface|enum|record|@interface)\s+\w+(?:<[^{]*>)?(\s+extends\s+\w*(?:Exception|Error|Throwable))?/m;
const ICONES = ['class', 'classAbstract', 'exception', 'test', 'interface', 'enum', 'record', 'annotation'];

function tipoJava(conteudo) {
    const achado = conteudo.match(TIPO_JAVA);
    if (!achado) return undefined;
    if (achado[2] === '@interface') return 'annotation';
    if (achado[2] !== 'class') return achado[2];
    if (achado[3]) return 'exception';
    if (/^\s*@(?:org\.junit\.[\w.]*)?Test\b/m.test(conteudo)) return 'test';
    return /\babstract\b/.test(achado[1]) ? 'classAbstract' : 'class';
}

function cssIcones() {
    const fs = require('fs'), path = require('path');
    const base = `.explorer-folders-view [data-ij]::before { content: '' !important; flex: none !important; width: 16px !important; height: 16px !important; margin: auto 6px auto 0 !important; padding: 0 !important; background-repeat: no-repeat !important; background-position: center !important; background-size: 16px !important; }`;
    return base + ICONES.map(nome => {
        const svg = fs.readFileSync(path.join(__dirname, 'icones', `${nome}_dark.svg`)).toString('base64');
        return `.explorer-folders-view [data-ij="${nome}"]::before { background-image: url(data:image/svg+xml;base64,${svg}) !important; }`;
    }).join('');
}

const scriptArvore = css => `(()=>{
if (window.__ijArvore) return;
const estilo = document.head.appendChild(document.createElement('style'));
estilo.textContent = ${JSON.stringify(css)};
const aplicar = () => {
  for (const rotulo of document.querySelectorAll('.explorer-folders-view .monaco-icon-label')) {
    const nome = rotulo.querySelector('.label-name');
    if (!nome) continue;
    const texto = document.createTreeWalker(nome, NodeFilter.SHOW_TEXT).nextNode();
    if (!texto) continue;
    if (texto.data.endsWith('.java')) {
      const curto = texto.data.slice(0, -5);
      texto.data = curto;
      rotulo.dataset.ijNome = curto;
    } else if (rotulo.dataset.ijNome !== texto.data) {
      delete rotulo.dataset.ijNome;
      delete rotulo.dataset.ij;
      continue;
    }
    const letra = window.__ijTipos?.[rotulo.dataset.ijNome];
    if (letra && rotulo.dataset.ij !== letra) rotulo.dataset.ij = letra;
  }
};
window.__ijArvore = aplicar;
let agendado = false;
new MutationObserver(() => {
  if (agendado) return;
  agendado = true;
  requestAnimationFrame(() => { agendado = false; aplicar(); });
}).observe(document.body, { childList: true, subtree: true, characterData: true });
aplicar();
})()`;

async function tiposJava(context) {
    const tipos = {};
    for (const uri of await vscode.workspace.findFiles('**/*.java', '**/{out,target,bin,build}/**', 3000)) {
        const conteudo = Buffer.from(await vscode.workspace.fs.readFile(uri)).toString();
        const tipo = tipoJava(conteudo);
        if (tipo) tipos[require('path').basename(uri.fsPath, '.java')] = tipo;
    }
    return naJanela(context, `window.__ijTipos=${JSON.stringify(tipos)};window.__ijArvore?.()`);
}

function arvoreJava(context) {
    let espera;
    const atualizar = () => {
        clearTimeout(espera);
        espera = setTimeout(() => tiposJava(context).catch(() => {}), 500);
    };
    const vigia = vscode.workspace.createFileSystemWatcher('**/*.java');
    context.subscriptions.push(vigia, vigia.onDidCreate(atualizar), vigia.onDidChange(atualizar), vigia.onDidDelete(atualizar));
    naJanela(context, scriptArvore(cssIcones())).then(() => tiposJava(context)).catch(() => {});
}

// Avisa no rodapé se uma atualização do editor quebrar os ajustes visuais
async function conferirSaude(context) {
    if (process.env.SUITE_VISUAL === '0') return;
    await new Promise(pronto => setTimeout(pronto, 10000));
    const expressao = "!!(document.querySelector('.part.editor') && document.querySelector('.part.sidebar') && window.__ijArvore && document.getElementById('ij-pausa'))";
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
        { label: 'Editor Background…', comando: 'ij.customizeBackground' },
        { label: 'Theme…', comando: 'workbench.action.selectTheme' },
        { label: 'Keymap', comando: 'workbench.action.openGlobalKeybindings' },
        { label: 'Plugins', comando: 'workbench.view.extensions' },
    ];
    const escolha = await vscode.window.showQuickPick(itens, { placeHolder: 'Settings' });
    if (escolha) vscode.commands.executeCommand(escolha.comando);
}

function activate(context) {
    contexto = context;
    const modelos = carregarModelos(context);
    fundoEditor(context).catch(() => {});
    estiloPausa(context).catch(() => {});
    if (process.env.SUITE_ANIMATIONS !== '0') estiloAnimacao(context).catch(() => {});
    marcaDagua(context).catch(() => {});
    arvoreJava(context);
    conferirSaude(context);
    context.subscriptions.push(vscode.workspace.onDidChangeTextDocument(evento => aoDigitar(context, evento)));
    comandoPendente();
    esconderPaineis(context);
    fecharNovidades();
    mostrarConfig();
    for (const [id, acao] of Object.entries(ACOES)) {
        context.subscriptions.push(vscode.commands.registerCommand(id, (...args) =>
            acao.a ? vscode.commands.executeCommand(acao.t, acao.a) : vscode.commands.executeCommand(acao.t, ...args)));
    }
    pintarBreakpoints();
    context.subscriptions.push(
        vscode.debug.onDidChangeBreakpoints(pintarBreakpoints),
        vscode.window.onDidChangeVisibleTextEditors(pintarBreakpoints)
    );

    const rodape = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 1000);
    rodape.command = 'workbench.action.quickOpen';
    caminhoRodape(rodape);
    context.subscriptions.push(rodape, vscode.window.onDidChangeActiveTextEditor(() => caminhoRodape(rodape)));

    context.subscriptions.push(
        vscode.commands.registerCommand('ij.safeDelete', exclusaoSegura),
        vscode.commands.registerCommand('ij.newClass', uri => novaClasse(uri)),
        vscode.commands.registerCommand('ij.newClassTop', () => novaClasse()),
        vscode.commands.registerCommand('ij.markSources', uri => marcarFontes('java.project.addToSourcePath', uri)),
        vscode.commands.registerCommand('ij.unmarkSources', uri => marcarFontes('java.project.removeFromSourcePath', uri)),
        vscode.commands.registerCommand('ij.run', uri => rodarDireto(uri)),
        vscode.commands.registerCommand('ij.runSelected', rodarSelecionado),
        vscode.commands.registerCommand('ij.debugSelected', depurarSelecionado),
        vscode.commands.registerCommand('ij.runConfigs', escolherConfig),
        vscode.commands.registerCommand('ij.editConfigs', editarConfigs),
        vscode.commands.registerCommand('ij.profile', uri => perfilar(uri)),
        vscode.workspace.onDidChangeConfiguration(e => { if (e.affectsConfiguration('launch')) mostrarConfig(); }),
        vscode.commands.registerCommand('ij.stop', pararExecucao),
        vscode.commands.registerCommand('ij.rerun', reexecutar),
        vscode.window.onDidCloseTerminal(fechado => {
            if (fechado !== execucao?.terminal) return;
            execucao = undefined;
            vscode.commands.executeCommand('setContext', 'ij.rodando', false);
            vscode.commands.executeCommand('setContext', 'ij.emExecucao', false);
        }),
        vscode.commands.registerCommand('ij.debug', uri => executar('java.debug.debugJavaFile', uri)),
        vscode.commands.registerCommand('ij.search', () => vscode.commands.executeCommand('workbench.action.quickOpen')),
        vscode.commands.registerCommand('ij.settings', menuConfiguracoes),
        vscode.commands.registerCommand('ij.customizeBackground', () => abrirPainelFundo(context)),
        vscode.commands.registerCommand('ij.nextMethod', () => irMetodo(1)),
        vscode.commands.registerCommand('ij.prevMethod', () => irMetodo(-1)),
        vscode.languages.registerCompletionItemProvider('java', { provideCompletionItems: postfix }, '.'),
        vscode.languages.registerCompletionItemProvider('java', { provideCompletionItems: (doc, pos) => sugerirModelos(modelos, doc, pos) })
    );

    // Executar sem depurar leva o foco ao terminal, para o Scanner receber a digitação
    // Ao parar mostra o Debug; ao continuar volta ao terminal, onde o programa pode esperar entrada
    context.subscriptions.push(vscode.debug.registerDebugAdapterTrackerFactory('java', {
        createDebugAdapterTracker() {
            let espera;
            return {
                onWillReceiveMessage(m) {
                    if (m.type === 'request' && m.command === 'continue') {
                        espera = setTimeout(() => vscode.commands.executeCommand('workbench.action.terminal.focus'), 500);
                    }
                },
                onDidSendMessage(m) {
                    if (m.type === 'event' && m.event === 'stopped') {
                        clearTimeout(espera);
                        abrirDebugComTerminal(); // o próprio comando já abre o Debug; repetir fecharia o painel
                    }
                }
            };
        }
    }));

    context.subscriptions.push(
        vscode.debug.onDidTerminateDebugSession(() => setTimeout(() => { if (!vscode.debug.activeDebugSession) moverTerminal('terminal'); }, 500))
    );
    context.subscriptions.push(vscode.debug.onDidStartDebugSession(sessao => {
        if (sessao.type === 'java' && sessao.configuration.noDebug) {
            setTimeout(() => vscode.commands.executeCommand('workbench.action.terminal.focus'), 800);
        }
    }));

    const controller = vscode.tests.createTestController('javaMainGutter', 'Java Main');
    context.subscriptions.push(controller);

    const iniciar = comando => request => {
        const itens = request.include ?? [...controller.items].map(([, item]) => item);
        executar(comando, itens[0]?.uri);
    };
    controller.createRunProfile('Executar', vscode.TestRunProfileKind.Run, request => {
        const itens = request.include ?? [...controller.items].map(([, item]) => item);
        rodarDireto(itens[0]?.uri);
    }, true);
    controller.createRunProfile('Depurar', vscode.TestRunProfileKind.Debug, iniciar('java.debug.debugJavaFile'), true);

    let esperaAnalise;
    const analisar = doc => {
        if (doc.languageId !== 'java' || doc.uri.scheme !== 'file') return;
        const id = doc.uri.toString();
        const linhas = doc.getText().split('\n');
        const linha = linhas.findIndex(l => MAIN.test(l));
        if (linha < 0) {
            controller.items.delete(id);
            return;
        }
        const nome = doc.uri.path.split('/').pop().replace('.java', '');
        const item = controller.createTestItem(id, `main: ${nome}`, doc.uri);
        item.range = new vscode.Range(linha, 0, linha, 0);
        const classe = linhas.findIndex(l => /\b(class|record|enum|interface)\s+\w+/.test(l));
        if (classe >= 0 && classe !== linha) {
            const filho = controller.createTestItem(`${id}#classe`, nome, doc.uri);
            filho.range = new vscode.Range(classe, 0, classe, 0);
            item.children.add(filho);
        }
        controller.items.add(item);
    };

    vscode.workspace.textDocuments.forEach(analisar);
    context.subscriptions.push(
        vscode.workspace.onDidOpenTextDocument(analisar),
        vscode.workspace.onDidChangeTextDocument(e => {
            clearTimeout(esperaAnalise);
            esperaAnalise = setTimeout(() => analisar(e.document), 800);
        }),
        vscode.workspace.onDidCloseTextDocument(d => controller.items.delete(d.uri.toString()))
    );
}

module.exports = { activate };
