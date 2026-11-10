const vscode = require('vscode');
const path = require('path');
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

// Chromium-based browsers the JavaScript debugger can drive; Firefox can't be, so it is not listed
const NAVEGADORES = ['google-chrome-stable', 'google-chrome', 'chromium', 'chromium-browser', 'microsoft-edge-stable',
    'microsoft-edge', 'brave-browser', 'brave', 'vivaldi-stable', 'vivaldi', 'com.google.Chrome', 'org.chromium.Chromium',
    'com.microsoft.Edge', 'com.brave.Browser', 'com.vivaldi.Vivaldi'];

function navegadorWeb() {
    if (process.platform === 'win32') return { type: 'pwa-msedge' };
    const fs = require('fs'), path = require('path'), os = require('os');
    const pastas = [...(process.env.PATH ?? '').split(path.delimiter), '/var/lib/flatpak/exports/bin', path.join(os.homedir(), '.local/share/flatpak/exports/bin')];
    const escolhido = process.env.SUITE_BROWSER;
    for (const nome of escolhido ? [escolhido, ...NAVEGADORES] : NAVEGADORES) {
        if (path.isAbsolute(nome) && fs.existsSync(nome)) return { type: 'pwa-chrome', runtimeExecutable: nome };
        for (const p of pastas) {
            const exe = path.join(p, nome);
            if (p && fs.existsSync(exe)) return { type: 'pwa-chrome', runtimeExecutable: exe };
        }
    }
    return null;
}

async function depurarWeb(doc) {
    await doc.save();
    const pasta = vscode.workspace.getWorkspaceFolder(doc.uri);
    if (doc.languageId === 'html') {
        const navegador = navegadorWeb();
        if (!navegador) {
            return vscode.window.showWarningMessage('Debugging a page needs Chrome, Chromium, Edge, Brave or Vivaldi, and none was found. '
                + 'For other browsers, use Open in Browser in the preview and their own DevTools.');
        }
        // Debug the page as the preview serves it, so fetch and modules behave like on a real server
        const url = await previa.urlDaPagina(contexto, doc.uri);
        return vscode.debug.startDebugging(pasta, { ...navegador, request: 'launch', name: 'Debug in Browser', webRoot: pasta?.uri.fsPath ?? path.dirname(doc.uri.fsPath),
            ...(url ? { url } : { file: doc.uri.fsPath }) });
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
