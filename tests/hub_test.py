"""Drives the Hub window offscreen: trust menu, trusted folders, new project and import."""
import hashlib
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
(RAIZ / 'data/hub.json').write_text('{"setup": true, "checked": 9e12}')
os.environ['SUITE_ROOT'] = str(RAIZ)
os.environ['HOME'] = str(TEMP / 'home')
(TEMP / 'home/.config/VSCodium/User/snippets').mkdir(parents=True)
(TEMP / 'home/.config/VSCodium/User/settings.json').write_text('{"editor.fontSize": 21}')
sys.path.insert(0, str(Path(__file__).parent.parent / 'hub'))
import hub  # noqa: E402

from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QMessageBox, QPushButton  # noqa: E402

falhas = []
abertos = []
hub.abrir_app = lambda app, alvos=(), porta=None, comando_=None: abertos.append((app, [str(a) for a in alvos], comando_))
hub.janelas_editor = lambda pid: set()
hub.etapa_atual = lambda app: 'ready'
hub.TEMPORARIO = None
hub.checar_novidade = lambda: None
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
    passo('window title', painel.windowTitle() == 'Berthline Hub · Cargo', painel.windowTitle())
    painel.miolo.ir(painel.gerais)
    passo('title follows the page', painel.windowTitle() == 'Berthline Hub · Settings', painel.windowTitle())
    painel.miolo.ir(painel.ferramentas)
    passo('panel cannot maximize', painel.minimumSize() == painel.maximumSize()
          and not painel.windowFlags() & Qt.WindowMaximizeButtonHint)
    passo('windows paths collapse', len({hub.chave_caminho(p, True) for p in (
        'C:\\Users\\Ana\\Projects\\loja', 'c:/Users/Ana/Projects/loja', '/c:/users/ana/Projects/loja/')}) == 1)
    passo('other windows folder stays', hub.chave_caminho('C:\\a\\b', True) != hub.chave_caminho('C:\\a\\c', True))
    passo('apps listed', {f.app for f in painel.findChildren(QFrame) if hasattr(f, 'mais')} == {'java', 'web', 'standard'})

    hub.gravar_geral('transitions', False)
    painel.boasvindas('java')
    tela = painel.tela
    passo('welcome per app', tela.windowTitle() == 'Berthline Hub · Java · Projects', tela.windowTitle())
    tela.ir('Learn')
    passo('title follows the tab', tela.windowTitle() == 'Berthline Hub · Java · Learn', tela.windowTitle())
    tela.ir('Projects')
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
    extras(painel)
    print('failed:' if falhas else 'all passed', falhas, flush=True)
    shutil.rmtree(TEMP)
    os._exit(1 if falhas else 0)


def ambiente_do_pacote():
    guardado = dict(os.environ)
    os.environ.update({'LD_LIBRARY_PATH': '/pacote/_hub', 'LD_LIBRARY_PATH_ORIG': '/meu/lib', 'QT_PLUGIN_PATH': '/pacote/plugins',
                       'QML2_IMPORT_PATH': '/pacote/qml', '_PYI_ARCHIVE_FILE': '/pacote/Hub', 'OUTRA': 'fica'})
    sys.frozen = True
    try:
        hub.limpar_ambiente()
        passo('children get a clean environment', os.environ.get('LD_LIBRARY_PATH') == '/meu/lib' and os.environ.get('OUTRA') == 'fica'
              and not {'LD_LIBRARY_PATH_ORIG', 'QT_PLUGIN_PATH', 'QML2_IMPORT_PATH', '_PYI_ARCHIVE_FILE'} & set(os.environ))
    finally:
        del sys.frozen
        os.environ.clear()
        os.environ.update(guardado)


def extras(painel):
    ambiente_do_pacote()
    # Keymap: a shortcut the person added survives both directions.
    hub.preparar('java')
    arquivo = hub.pasta_usuario('java') / 'keybindings.json'
    propria = {'key': 'ctrl+alt+9', 'command': 'minha.acao'}
    dados = hub.ler_json(arquivo)
    arquivo.write_text(json.dumps(dados + [propria]), encoding='utf8')
    vscode = hub.ler_json(hub.PERFIS / 'java/keymap-vscode.json')
    passo('keymap switches', hub.aplicar_keymap('java', 'vscode') and hub.ler_json(arquivo) == vscode + [propria])
    teclas_vs = {e['key']: e['command'] for e in hub.ler_json(arquivo) if not e['command'].startswith('-')}
    passo('vscode keymap copies lines', teclas_vs['shift+alt+up'] == 'editor.action.copyLinesUpAction'
          and teclas_vs['shift+alt+down'] == 'editor.action.copyLinesDownAction')
    passo('vscode keymap undoes intellij', sum(e['command'].startswith('-') for e in vscode) > 200)
    passo('vscode keymap keeps defaults', not any(e['key'] == 'ctrl+/' for e in vscode))
    hub.aplicar_keymap('java', 'intellij')
    volta = hub.ler_json(arquivo)
    passo('keymap returns with own key', propria in volta and len(volta) == len(dados) + 1)
    passo('intellij keymap moves lines', not any(e in volta for e in vscode)
          and any(e.get('key') == 'alt+shift+up' for e in volta))
    passo('keymap only in java', hub.aplicativos()['java'].get('keymap') and not hub.aplicativos()['web'].get('keymap'))
    hub.gravar_opcao('web', 'keymap', 'vscode')
    passo('web stays out of the choice', hub.keymap_de('web') == 'intellij')
    hub.gravar_opcao('web', 'keymap', 'intellij')
    arquivo.write_text('[{"key": ')
    passo('broken keybindings left alone', not hub.aplicar_keymap('java', 'vscode') and arquivo.read_text() == '[{"key": ')
    arquivo.unlink()
    nomes = [a for a, _ in hub.teclas_app('web')]
    passo('web keymap has no java keys', 'Build' not in nomes and 'Generate' not in nomes)
    passo('java keymap has build', 'Build' in [a for a, _ in hub.teclas_app('java')])

    # Back to Hub reopens the same app's screen.
    amb = hub.ambiente('web')
    passo('back knows the app', amb['SUITE_APP'] == 'web')
    passo('back runs the hub from source', json.loads(amb['SUITE_HUB_ARGS'])[0].endswith('hub.py') and amb['SUITE_HUB_ROOT'] == str(hub.RAIZ))
    atalho = hub.criar_atalho('java')
    passo('source shortcut keeps its root', f'SUITE_ROOT={hub.RAIZ}' in atalho.read_text())

    # Running state comes from the editor's lock file.
    trava = hub.DADOS / 'web/user/code.lock'
    trava.parent.mkdir(parents=True, exist_ok=True)
    trava.write_text(str(os.getpid()))
    passo('running detected', hub.estado_app('web')[0] == 'run')
    trava.write_text('999999999')
    passo('stale lock ignored', hub.estado_app('web')[0] != 'run')
    trava.unlink()

    # Shortcuts go where they were asked to.
    menu = hub.CASA / '.local/share/applications/berthline-web.desktop'
    mesa = hub.area_de_trabalho() / 'berthline-web.desktop'
    menu.unlink(missing_ok=True)
    mesa.unlink(missing_ok=True)
    hub.criar_atalho('web', desktop=False, menu=True)
    passo('menu shortcut only', menu.exists() and not mesa.exists())

    # Setup window.
    pasta = TEMP / 'projetos-web'
    preparo = hub.CLASSES['Preparo'](painel)
    preparo.linhas['web'][3].setText(str(pasta))
    passo('setup offers keymap only in java', preparo.linhas['web'][2] is None and preparo.linhas['standard'][2] is None)
    preparo.linhas['java'][2].botoes['VS Code'].setChecked(True)
    preparo.escolher_tema('Light')
    preparo.concluir()
    passo('setup folder', hub.pasta_projetos('web') == pasta and pasta.is_dir())
    passo('setup keymap', hub.opcao('java', 'keymap') == 'vscode')
    passo('setup theme', hub.ajuste('web', 'workbench.colorTheme') == 'Islands Light' and hub.ajuste('standard', 'workbench.colorTheme') == 'Light Modern')
    passo('setup done', hub.opcoes().get('setup') is True)
    passo('setup returns to panel', painel.isVisible())

    # Updates: comparison, skip and a checked download.
    hub.gravar_geral('update', {'version': hub.versao(), 'notes': ''})
    passo('same version is quiet', hub.novidade() is None)
    hub.gravar_geral('update', {'version': '9.0.0', 'notes': ''})
    passo('newer version shows', hub.novidade() and hub.novidade()['version'] == '9.0.0')
    hub.gravar_geral('skip_version', '9.0.0')
    passo('skipped version is quiet', hub.novidade() is None)
    pacote = TEMP / 'servidor/berthline-linux.tar.gz'
    pacote.parent.mkdir()
    pacote.write_bytes(b'pacote')
    somas = TEMP / 'servidor/SHA256SUMS'
    somas.write_text(f'{hashlib.sha256(b"pacote").hexdigest()}  berthline-linux.tar.gz\n')
    alvo = TEMP / 'baixado/berthline-linux.tar.gz'
    hub.baixar_verificado(pacote.as_uri(), somas.as_uri(), alvo)
    passo('checked download kept', alvo.read_bytes() == b'pacote')
    alvo.unlink()
    somas.write_text(f'{"0" * 64}  berthline-linux.tar.gz\n')
    try:
        hub.baixar_verificado(pacote.as_uri(), somas.as_uri(), alvo)
        passo('bad download refused', False)
    except ValueError:
        passo('bad download refused', not alvo.exists() and not list(alvo.parent.glob('*.part')))

    # Icon pack is chosen per app.
    tema = Path(__file__).parent.parent / 'extension-lite/icons'
    definicoes = json.loads((tema / 'theme.json').read_text())['iconDefinitions'].values()
    passo('icon files are svg', all('xmlns="http://www.w3.org/2000/svg"' in (tema / d['iconPath']).read_text() for d in definicoes))
    hub.gravar_ajuste('web', 'workbench.iconTheme', hub.ICON_THEMES['Berthline'])
    passo('icon pack per app', hub.ajuste('web', 'workbench.iconTheme') == 'berthline-file-icons'
          and hub.ajuste('java', 'workbench.iconTheme') == hub.ICON_THEMES['JetBrains'])


QApplication.exec = lambda *a: (QTimer.singleShot(100, roteiro), QEventLoop().exec())[1]
sys.argv = ['hub']
sys.exit(hub.main())
