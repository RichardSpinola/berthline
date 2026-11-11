// Status bar entry for the Git history view: a short "Git Log" in place of "(neo) Git Graph".
const vscode = require('vscode');

function ativar(context) {
    const item = vscode.window.createStatusBarItem('web.gitLog', vscode.StatusBarAlignment.Left, 1);
    item.name = 'Git Log';
    item.text = '$(git-commit) Git Log';
    item.tooltip = 'Show the Git history';
    item.command = 'neo-git-graph.view';
    context.subscriptions.push(item);
    const git = vscode.extensions.getExtension('vscode.git');
    if (!git || !vscode.extensions.getExtension('asispts.neo-git-graph')) return;
    Promise.resolve(git.isActive ? git.exports : git.activate()).then(exp => {
        const api = exp.getAPI(1);
        const mostrar = () => (api.repositories.length ? item.show() : item.hide());
        context.subscriptions.push(api.onDidOpenRepository(mostrar), api.onDidCloseRepository(mostrar));
        mostrar();
    }, () => {});
}

module.exports = { ativar };
