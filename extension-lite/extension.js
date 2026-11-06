const vscode = require('vscode');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

// Avisa o Hub em qual etapa o editor está, para a animação terminar na hora certa
function etapa(nome) {
    const pasta = process.env.SUITE_TOOLS;
    if (pasta) fs.writeFileSync(path.join(pasta, 'etapa'), nome);
}

async function esperarJava() {
    const java = vscode.extensions.getExtension('redhat.java');
    if (!java) return;
    const arquivos = await vscode.workspace.findFiles('{**/*.java,**/pom.xml,**/build.gradle,**/build.gradle.kts}', '**/node_modules/**', 1);
    if (!arquivos.length) return;
    etapa('java');
    const api = await java.activate();
    await Promise.race([api?.serverReady?.(), new Promise(pronto => setTimeout(pronto, 90000))]);
}

function activate(context) {
    const botao = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 1001);
    botao.text = '$(arrow-left) Hub';
    botao.tooltip = 'Back to Hub';
    botao.command = 'berthline.openHub';
    botao.show();
    context.subscriptions.push(botao, vscode.commands.registerCommand('berthline.openHub', () => {
        spawn(process.env.SUITE_HUB, [], { detached: true, stdio: 'ignore' }).unref();
    }));
    esperarJava().catch(() => {}).finally(() => etapa('ready'));
}

module.exports = { activate };
