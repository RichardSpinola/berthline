// Test only: lets tests/audit.js drive the editor API over a local port.
const http = require('http');
const vscode = require('vscode');

const editor = () => vscode.window.activeTextEditor;

const acoes = {
    comandos: () => vscode.commands.getCommands(true),
    contribuicoes: ({ id }) => vscode.extensions.getExtension(id)?.packageJSON.contributes ?? null,
    temas: () => vscode.extensions.all.flatMap(e => e.packageJSON.contributes?.themes ?? [])
        .map(t => ({ id: t.id ?? t.label, tipo: t.uiTheme })),
    ajuste: ({ chave }) => vscode.workspace.getConfiguration().get(chave),
    ajustar: async ({ chave, valor }) => {
        await vscode.workspace.getConfiguration().update(chave, valor, vscode.ConfigurationTarget.Global);
        return true;
    },
    executar: async ({ comando, args = [], limite = 2500 }) => {
        const tempo = new Promise(ok => setTimeout(() => ok('timeout'), limite));
        const fim = vscode.commands.executeCommand(comando, ...args).then(() => 'ok', e => `error: ${e.message}`);
        return Promise.race([fim, tempo]);
    },
    abrir: async ({ arquivo }) => {
        const d = await vscode.workspace.openTextDocument(arquivo);
        await vscode.window.showTextDocument(d);
        return true;
    },
    cursor: ({ linha, coluna }) => {
        const p = new vscode.Position(linha, coluna);
        editor().selection = new vscode.Selection(p, p);
        return true;
    },
    sugestoes: async ({ linha, coluna, gatilho }) => {
        const lista = await vscode.commands.executeCommand('vscode.executeCompletionItemProvider', editor().document.uri, new vscode.Position(linha, coluna), gatilho);
        return lista.items.map(i => ({ rotulo: i.label.label ?? i.label, ordem: i.sortText ?? '' }));
    },
    erros: ({ arquivo }) => vscode.languages.getDiagnostics(vscode.Uri.file(arquivo)).filter(d => d.severity === 0).map(d => d.message),
    estado: () => {
        const e = editor();
        return e && { texto: e.document.getText(), sujo: e.document.isDirty,
            selecoes: e.selections.map(s => [s.start.line, s.start.character, s.end.line, s.end.character]) };
    },
};

exports.activate = () => {
    http.createServer((req, res) => {
        let corpo = '';
        req.on('data', d => corpo += d);
        req.on('end', async () => {
            let saida;
            try {
                const { acao, ...dados } = JSON.parse(corpo);
                saida = { ok: await acoes[acao](dados) };
            } catch (e) {
                saida = { erro: e.message };
            }
            res.end(JSON.stringify(saida));
        });
    }).listen(9335, '127.0.0.1');
};
