"""Drives the Hub window offscreen: trust menu, trusted folders, new project and import."""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
PACOTE = Path(sys.argv[1]).resolve()
TEMP = Path(tempfile.mkdtemp(prefix='hub-'))
RAIZ = TEMP / 'root'
RAIZ.mkdir()
for nome in ('profiles', 'assets', 'editor'):
    (RAIZ / nome).symlink_to(PACOTE / nome)
shutil.copy(PACOTE / 'brand.json', RAIZ)
os.environ['SUITE_ROOT'] = str(RAIZ)
os.environ['HOME'] = str(TEMP / 'home')
(TEMP / 'home/.config/VSCodium/User/snippets').mkdir(parents=True)
(TEMP / 'home/.config/VSCodium/User/settings.json').write_text('{"editor.fontSize": 21}')
sys.path.insert(0, str(Path(__file__).parent.parent / 'hub'))
import hub  # noqa: E402

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton  # noqa: E402

falhas = []
abertos = []
hub.abrir_app = lambda app, alvos=(), porta=None: abertos.append((app, [str(a) for a in alvos]))
QApplication.quit = staticmethod(lambda: None)


def passo(nome, ok, extra=''):
    print('OK  ' if ok else 'FAIL', nome, extra)
    if not ok:
        falhas.append(nome)


def banco():
    return hub.CASA / '.berthline-shared/sharedStorage/state.vscdb'


def confiaveis_no_editor():
    con = sqlite3.connect(banco())
    return [i['uri']['path'] for i in json.loads(con.execute(
        "SELECT value FROM ItemTable WHERE key='content.trust.model.key'").fetchone()[0])['uriTrustInfo']]


def responder(texto):
    def clicar():
        janela = QApplication.activeModalWidget()
        botao = next(b for b in janela.findChildren(QPushButton) if b.text().startswith(texto))
        botao.click()
    QTimer.singleShot(50, clicar)


def roteiro():
    j = next(w for w in QApplication.topLevelWidgets() if hasattr(w, 'paginas'))
    projetos = j.paginas.widget(1)
    ajustes = j.ajustes

    pasta = TEMP / 'outside/alpha'
    pasta.mkdir(parents=True)
    irma = TEMP / 'outside/beta'
    irma.mkdir()
    abrir = next(c for c in projetos.findChildren(QPushButton) if c.text() == 'Open Folder')
    from PySide6.QtWidgets import QFileDialog
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(pasta))

    responder('Cancel')
    abrir.click()
    passo('cancel opens nothing', not abertos)
    passo('cancel trusts nothing', not hub.confiavel(pasta))

    responder('Open restricted')
    abrir.click()
    passo('restricted opens', len(abertos) == 1)
    passo('restricted stays untrusted', not hub.confiavel(pasta))

    responder('Trust folder')
    abrir.click()
    passo('trust opens', len(abertos) == 2)
    passo('trust saved', hub.confiavel(pasta))
    passo('sibling still untrusted', not hub.confiavel(irma))

    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(irma))
    responder('Trust all')
    abrir.click()
    passo('parent trusted covers sibling', hub.confiavel(irma) and hub.confiavel(pasta))

    abertos.clear()
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(pasta))
    QTimer.singleShot(200, lambda: passo('no prompt when trusted', QApplication.activeModalWidget() is None))
    abrir.click()
    passo('trusted opens directly', len(abertos) == 1)

    ajustes.listar()
    hub.aplicar_confianca()
    passo('editor receives folder', str(TEMP / 'outside') in confiaveis_no_editor())
    hub.retirar_confianca(str(TEMP / 'outside'))
    passo('removed from hub', not hub.confiavel(irma))
    passo('removed from editor', str(TEMP / 'outside') not in confiaveis_no_editor())

    fora = hub.criar_projeto('web', 'TypeScript', 'demo', TEMP)
    passo('new project trusted', hub.confiavel(fora))
    passo('template copied', (fora / 'main.ts').exists())

    origem = hub.CASA / '.config/VSCodium/User'
    hub.importar('web', origem)
    passo('import copies', hub.ler_json(hub.pasta_usuario('web') / 'settings.json').get('editor.fontSize') == 21)
    passo('import keeps original', (origem / 'settings.json').read_text() == '{"editor.fontSize": 21}')

    ajustes.app.setCurrentIndex(ajustes.app.findData('web'))
    ajustes.telemetria.setChecked(True)
    hub.preparar('web')
    dados = hub.ler_json(hub.pasta_usuario('web') / 'settings.json')
    passo('telemetry per app', dados['telemetry.telemetryLevel'] == 'all' and hub.opcao('java', 'telemetry') is False)
    passo('import survives prepare', dados.get('editor.fontSize') == 21)
    hub.preparar('java')
    dados = hub.ler_json(hub.pasta_usuario('java') / 'settings.json')
    passo('paths resolved', '${SUITE}' not in json.dumps(dados))
    passo('todo tree path', Path(dados.get('todo-tree.ripgrep.ripgrep', '/x')).exists())
    passo('window title', j.windowTitle() == 'Berthline Hub', j.windowTitle())
    QTimer.singleShot(0, lambda: (print('failed:' if falhas else 'all passed', falhas), shutil.rmtree(TEMP), os._exit(1 if falhas else 0)))


QApplication.exec = lambda *a: (QTimer.singleShot(100, roteiro), __import__('PySide6.QtCore').QtCore.QEventLoop().exec())[1]
sys.argv = ['hub']
sys.exit(hub.main())
