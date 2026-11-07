"""Drives the Hub window offscreen: trust menu, trusted folders, new project and import."""
import json
import os
import shutil
import sqlite3
import subprocess
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
for app in ('java', 'web'):
    (RAIZ / 'data' / app).mkdir(parents=True)
    (RAIZ / 'data' / app / 'extensions').symlink_to(PACOTE / 'data' / app / 'extensions')
os.environ['SUITE_ROOT'] = str(RAIZ)
os.environ['HOME'] = str(TEMP / 'home')
(TEMP / 'home/.config/VSCodium/User/snippets').mkdir(parents=True)
(TEMP / 'home/.config/VSCodium/User/settings.json').write_text('{"editor.fontSize": 21}')
sys.path.insert(0, str(Path(__file__).parent.parent / 'hub'))
import hub  # noqa: E402

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QMessageBox, QPushButton  # noqa: E402

falhas = []
abertos = []
hub.abrir_app = lambda app, alvos=(), porta=None, comando_=None: abertos.append((app, [str(a) for a in alvos], comando_))
hub.janelas_editor = lambda pid: set()
hub.etapa_atual = lambda app: 'ready'
hub.TEMPORARIO = None
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


def botao(pai, texto):
    return next(b for b in pai.findChildren(QPushButton) if b.text() == texto)


def esperar(ms):
    laco = QEventLoop()
    QTimer.singleShot(ms, laco.quit)
    laco.exec()


def roteiro():
    painel = next(w for w in QApplication.topLevelWidgets() if hasattr(w, 'miolo'))
    passo('window title', painel.windowTitle() == 'Berthline Hub', painel.windowTitle())
    passo('windows paths collapse', len({hub.chave_caminho(p, True) for p in (
        'C:\\Users\\Ana\\Projects\\loja', 'c:/Users/Ana/Projects/loja', '/c:/users/ana/Projects/loja/')}) == 1)
    passo('other windows folder stays', hub.chave_caminho('C:\\a\\b', True) != hub.chave_caminho('C:\\a\\c', True))
    passo('apps listed', {f.app for f in painel.findChildren(QFrame) if hasattr(f, 'mais')} == {'java', 'web', 'standard'})

    hub.gravar_geral('transitions', False)
    painel.boasvindas('java')
    tela = painel.tela
    passo('welcome per app', tela.windowTitle() == 'Welcome to Berthline Java', tela.windowTitle())
    passo('panel hidden', not painel.isVisible())
    tela.close()
    passo('close returns to panel', painel.isVisible())
    painel.boasvindas('web', 'Plugins')
    passo('menu goes to plugins', painel.tela.paginas.currentIndex() == 2)
    painel.tela.close()
    painel.boasvindas('java')
    tela = painel.tela
    projetos = tela.paginas.widget(0)

    pasta = TEMP / 'outside/alpha'
    pasta.mkdir(parents=True)
    irma = TEMP / 'outside/beta'
    irma.mkdir()
    abrir = botao(projetos, 'Open')
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
    abrir.click()
    passo('trusted opens directly', len(abertos) == 1)
    hub.aplicar_confianca()
    passo('editor receives folder', str(TEMP / 'outside') in confiaveis_no_editor())
    hub.retirar_confianca(str(TEMP / 'outside'))
    passo('removed from hub', not hub.confiavel(irma))
    passo('removed from editor', str(TEMP / 'outside') not in confiaveis_no_editor())

    abertos.clear()

    def novo():
        d = QApplication.activeModalWidget()
        passo('empty template offered', d.modelos.item(0).text() == 'Empty Project')
        d.nome.setText('demo')
        d.local.setText(str(TEMP))
        d.git.setChecked(True)
        botao(d, 'Create').click()
    QTimer.singleShot(50, novo)
    botao(projetos, 'New Project').click()
    fora = TEMP / 'demo'
    passo('new project opens', abertos and abertos[-1][1] == [str(fora)])
    passo('template copied', (fora / 'src/Main.java').exists())
    passo('git created', (fora / '.git').is_dir())
    passo('new project trusted', hub.confiavel(fora))

    vazio = hub.criar_projeto('standard', 'Empty Project', 'nada', TEMP)
    passo('empty project stays empty', not list(vazio.iterdir()))
    hub.PROJETOS.mkdir(exist_ok=True)
    (hub.PROJETOS / 'loja/src').mkdir(parents=True)
    (hub.PROJETOS / 'loja/src/A.java').write_text('class A {}')
    (hub.PROJETOS / 'site').mkdir()
    (hub.PROJETOS / 'site/index.html').write_text('<p>')
    passo('disk project in java', any(t == 'On this computer' and any(p.name == 'loja' for p, _ in l) for t, l in hub.secoes('java')))
    passo('disk project only in its app', not any(p.name == 'site' for _, l in hub.secoes('java') for p, _ in l))
    passo('panel lists every app', {'java', 'web'} <= {a for _, l in hub.secoes() for _, a in l})

    origem_git = TEMP / 'origem'
    origem_git.mkdir()
    subprocess.run('git init -q && git -c user.name=t -c user.email=t@t commit -q --allow-empty -m x', shell=True, cwd=origem_git, check=True)
    abertos.clear()

    def clonar():
        d = QApplication.activeModalWidget()
        d.url.setText(str(origem_git))
        botao(d, 'Clone').click()
        responder_depois()

    def responder_depois():
        janela = QApplication.activeModalWidget()
        if isinstance(janela, QMessageBox):
            next(b for b in janela.findChildren(QPushButton) if b.text().startswith('Trust folder')).click()
        else:
            QTimer.singleShot(100, responder_depois)
    QTimer.singleShot(50, clonar)
    botao(projetos, 'Clone Repository').click()
    passo('clone opens', abertos and abertos[-1][1] == [str(hub.CLONES / 'origem')], str(abertos[-1:]))
    passo('clone asked for trust', hub.confiavel(hub.CLONES / 'origem'))

    hub.importar('web', hub.CASA / '.config/VSCodium/User')
    passo('import copies', hub.ler_json(hub.pasta_usuario('web') / 'settings.json').get('editor.fontSize') == 21)
    hub.gravar_opcao('web', 'telemetry', True)
    hub.gravar_opcao('web', 'animations', False)
    hub.preparar('web')
    dados = hub.ler_json(hub.pasta_usuario('web') / 'settings.json')
    passo('telemetry always off', dados['telemetry.telemetryLevel'] == 'off')
    passo('import survives prepare', dados.get('editor.fontSize') == 21)
    passo('animations off', dados['workbench.reduceMotion'] == 'on' and dados['editor.smoothScrolling'] is False)
    passo('web accent', dados['workbench.colorCustomizations']['focusBorder'] == '#3B82C4')
    passo('app env', hub.ambiente('web')['SUITE_ANIMATIONS'] == '0')
    passo('watermark gray', 'fill="#35383D"' in (hub.DADOS / 'web/watermark.svg').read_text())
    hub.alternar_extensao('web', 'naumovs.color-highlight', False)
    passo('extension disabled per app', '--disable-extension=naumovs.color-highlight' in hub.comando('web'))
    passo('other app keeps it', not hub.desligadas('java'))
    hub.alternar_extensao('web', 'naumovs.color-highlight', True)
    passo('extension enabled again', '--disable-extension=naumovs.color-highlight' not in hub.comando('web'))
    passo('plugins listed', any(i == 'redhat.java' for i, *_ in hub.plugins('java')))
    passo('themes listed', len(hub.temas('java')) > 3)
    hub.preparar('java')
    dados = hub.ler_json(hub.pasta_usuario('java') / 'settings.json')
    passo('paths resolved', '${SUITE}' not in json.dumps(dados))
    passo('todo tree path', Path(dados.get('todo-tree.ripgrep.ripgrep', '/x')).exists())
    atalho = hub.criar_atalho('java')
    passo('desktop shortcut', '--welcome java' in atalho.read_text() and os.access(atalho, os.X_OK), str(atalho))
    print('failed:' if falhas else 'all passed', falhas, flush=True)
    shutil.rmtree(TEMP)
    os._exit(1 if falhas else 0)


QApplication.exec = lambda *a: (QTimer.singleShot(100, roteiro), QEventLoop().exec())[1]
sys.argv = ['hub']
sys.exit(hub.main())
