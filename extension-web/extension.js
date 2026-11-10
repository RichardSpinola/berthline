const vscode = require('vscode');
const { ativarComum, abrirRun, nodeDaSuite } = require('./comum/comum');
const previa = require('./previa');
const { inserirBloco } = require('./blocos');

// Web: HTML opens in the preview; JS and TS run in the bundled Node
const LINGUAGENS_WEB = ['html', 'javascript', 'typescript'];

function arquivoWeb() {
    const doc = vscode.window.activeTextEditor?.document;
    return doc && LINGUAGENS_WEB.includes(doc.languageId) ? doc : undefined;
}

async function rodarWeb(doc) {
    await doc.save();
    if (doc.languageId === 'html') return previa.abrir(contexto, { arquivo: doc.uri });
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

let contexto;

function activate(context) {
    contexto = context;
    ativarComum(context, { prefixo: 'web' });
    context.subscriptions.push(
        vscode.commands.registerCommand('web.run', () => { const doc = arquivoWeb(); return doc && rodarWeb(doc); }),
        vscode.commands.registerCommand('web.debug', () => { const doc = arquivoWeb(); return doc && depurarWeb(doc); }),
        vscode.commands.registerCommand('web.preview', uri => previa.abrir(context, { arquivo: uri instanceof vscode.Uri ? uri : vscode.window.activeTextEditor?.document.uri, focar: false })),
        vscode.commands.registerCommand('web.insertBlock', inserirBloco)
    );
    previa.ativar(context);
}

function deactivate() {
    previa.pararTudo();
}

module.exports = { activate, deactivate };
