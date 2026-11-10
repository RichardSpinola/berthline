const vscode = require('vscode');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const inicio = require('./inicio');

// Avisa o Hub em qual etapa o editor está; depois de | vai o texto que aparece na janela de espera
function etapa(nome, detalhe = '') {
    const pasta = process.env.SUITE_TOOLS;
    if (pasta) fs.writeFileSync(path.join(pasta, 'etapa'), detalhe ? `${nome}|${detalhe}` : nome);
}

// Conta as extensões ativas até o número parar de subir
async function esperarExtensoes() {
    const lista = () => vscode.extensions.all.filter(e => !e.id.startsWith('vscode.') && !e.packageJSON?.isBuiltin);
    let antes = -1, parado = 0;
    for (let i = 0; i < 100 && parado < 8; i++) {
        const ativas = lista().filter(e => e.isActive).length;
        etapa('extensions', `Extensions ${ativas} of ${lista().length}`);
        parado = ativas === antes ? parado + 1 : 0;
        antes = ativas;
        await new Promise(pronto => setTimeout(pronto, 250));
    }
}

// Olha a raiz primeiro: logo depois de abrir, a busca do editor pode voltar vazia
async function temJava() {
    for (const pasta of vscode.workspace.workspaceFolders || []) {
        for (const nome of ['pom.xml', 'build.gradle', 'build.gradle.kts']) {
            try {
                await vscode.workspace.fs.stat(vscode.Uri.joinPath(pasta.uri, nome));
                return true;
            } catch { /* not here */ }
        }
    }
    return (await vscode.workspace.findFiles('**/*.java', '**/node_modules/**', 1)).length > 0;
}

async function esperarJava() {
    const java = vscode.extensions.getExtension('redhat.java');
    if (!java) return;
    if (!await temJava()) return;
    etapa('java', 'Starting the Java server');
    const api = await java.activate();
    etapa('java', 'Importing the project');
    await Promise.race([api?.serverReady?.(), new Promise(pronto => setTimeout(pronto, 90000))]);
}

function activate(context) {
    const botao = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 1001);
    botao.text = '$(arrow-left) Hub';
    botao.tooltip = 'Back to Hub';
    botao.command = 'berthline.openHub';
    botao.show();
    context.subscriptions.push(botao, vscode.commands.registerCommand('berthline.openHub', () => {
        const ambiente = { ...process.env };
        // Variáveis do editor fariam a próxima janela abrir como Node e fechar
        for (const chave of Object.keys(ambiente)) {
            if (chave === 'ELECTRON_RUN_AS_NODE' || chave.startsWith('VSCODE_')) delete ambiente[chave];
        }
        if (process.env.SUITE_HUB_ROOT) ambiente.SUITE_ROOT = process.env.SUITE_HUB_ROOT;
        const antes = JSON.parse(process.env.SUITE_HUB_ARGS || '[]');
        const app = process.env.SUITE_APP ? ['--welcome', process.env.SUITE_APP] : [];
        spawn(process.env.SUITE_HUB, [...antes, ...app], { detached: true, stdio: 'ignore', env: ambiente }).unref();
        vscode.commands.executeCommand('workbench.action.closeWindow');
    }));
    inicio.ativar(context);
    esperarExtensoes().then(esperarJava).catch(() => {}).finally(() => etapa('ready'));
}

module.exports = { activate };
