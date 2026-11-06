const vscode = require('vscode');
const { ativarComum, abrirRun, nodeDaSuite } = require('./comum/comum');

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

function activate(context) {
    ativarComum(context, { prefixo: 'web' });
    context.subscriptions.push(
        vscode.commands.registerCommand('web.run', () => { const doc = arquivoWeb(); return doc && rodarWeb(doc); }),
        vscode.commands.registerCommand('web.debug', () => { const doc = arquivoWeb(); return doc && depurarWeb(doc); })
    );
}

module.exports = { activate };
