"""Walks every Hub screen offscreen and uses every control: buttons, menus, lists and dialogs.

Fails on any exception or when a control appears or disappears from tests/hub_controls.txt.
Run with --write to accept the current list. Screenshots land in tests/out/hub.
"""
import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
AQUI = Path(__file__).parent
PACOTE = Path(sys.argv[1]).resolve()
ESCREVER = '--write' in sys.argv
LISTA = AQUI / 'hub_controls.txt'
FOTOS = AQUI / 'out/hub'
FOTOS.mkdir(parents=True, exist_ok=True)
TEMP = Path(tempfile.mkdtemp(prefix='hub-audit-'))
RAIZ = TEMP / 'root'
RAIZ.mkdir()
for nome in ('profiles', 'assets', 'editor'):
    (RAIZ / nome).symlink_to(PACOTE / nome)
shutil.copy(PACOTE / 'brand.json', RAIZ)
for app in ('java', 'web', 'standard'):
    (RAIZ / 'data' / app).mkdir(parents=True)
    (RAIZ / 'data' / app / 'extensions').symlink_to(PACOTE / 'data' / app / 'extensions')
os.environ['SUITE_ROOT'] = str(RAIZ)
os.environ['HOME'] = str(TEMP / 'home')
(TEMP / 'home/Projects/loja/src').mkdir(parents=True)
(TEMP / 'home/Projects/loja/pom.xml').write_text('<project/>')
(TEMP / 'home/Projects/site').mkdir()
(TEMP / 'home/Projects/site/index.html').write_text('<html></html>')
(RAIZ / 'data/hub.json').write_text(json.dumps({'transitions': False, 'recent': [
    {'path': str(TEMP / 'home/Projects/loja'), 'app': 'java'}]}))
sys.path.insert(0, str(AQUI.parent / 'hub'))
import hub  # noqa: E402

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QDesktopServices  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QLabel, QLineEdit, QListWidget, QMenu,
    QMessageBox, QSlider, QSpinBox, QWidget)

erros, vistos, links, avisos = [], [], [], []
dialogos = []
sys.excepthook = lambda t, v, tb: erros.append(''.join(traceback.format_exception(t, v, tb))[-400:])

hub.abrir_app = lambda app, alvos=(), porta=None, comando_=None: None
hub.janelas_editor = lambda pid: set()
hub.etapa_atual = lambda app: 'ready'
hub.TEMPORARIO = None
QApplication.quit = staticmethod(lambda: None)
QDesktopServices.openUrl = staticmethod(lambda u: links.append(u.toString()) or True)
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: '')
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ('', ''))
for metodo in ('information', 'warning', 'critical', 'question'):
    setattr(QMessageBox, metodo, staticmethod(lambda *a, **k: QMessageBox.Cancel))
QMessageBox.exec = lambda self: dialogos.append(('message', self.text())) or QMessageBox.Cancel
QDialog.exec = lambda self: (dialogos.append(('dialog', self)), self.show(), 0)[2]
QMenu.exec = lambda self, *a: dialogos.append(('menu', self)) or None


def esperar(ms=120):
    laco = QEventLoop()
    QTimer.singleShot(ms, laco.quit)
    laco.exec()


def rotulo_de(c):
    texto = ''
    if isinstance(c, QAbstractButton):
        texto = c.text()
    elif isinstance(c, QLineEdit):
        texto = c.placeholderText()
    texto = (texto or c.toolTip() or c.accessibleName() or c.objectName()).strip()
    if str(TEMP) in texto or texto.startswith('~'):
        texto = 'path'
    return f"{type(c).__mro__[0].__name__}:{texto.replace(chr(10), ' ')[:50]}"


def controles(raiz):
    tipos = (QAbstractButton, QComboBox, QLineEdit, QListWidget, QSlider, QSpinBox)
    achados = [c for c in raiz.findChildren(QWidget) if isinstance(c, tipos) and c.isVisibleTo(raiz) and c.isEnabled()
               and not type(c).__name__.startswith('Qt')]
    for f in raiz.findChildren(QFrame):
        if hasattr(f, 'mais'):  # the row's menu only shows on hover
            f.mais.setVisible(True)
            achados.append(f.mais)
    return [c for c in achados if type(c.parent()).__name__ not in ('QComboBox', 'QAbstractSpinBox')
            and not c.objectName().startswith('qt_')]


def medir(raiz, nome):
    for r in raiz.findChildren(QLabel):
        if r.isVisibleTo(raiz) and r.text() and not r.wordWrap() and r.width() and r.sizeHint().width() > r.width() + 1:
            avisos.append(f'{nome}: label clipped: {r.text()[:50]}')
    for b in raiz.findChildren(QAbstractButton):
        if b.isVisibleTo(raiz) and b.text() and b.width() and b.sizeHint().width() > b.width() + 1:
            avisos.append(f'{nome}: button clipped: {b.text()[:50]}')


def foto(raiz, nome):
    esperar(60)
    raiz.grab().save(str(FOTOS / f"{nome.replace('/', '-').replace(' ', '_')}.png"))
    medir(raiz, nome)


def fechar_tudo(painel):
    for w in QApplication.topLevelWidgets():
        if w is not painel and w.isVisible() and not isinstance(w, QMenu):
            w.close()
    dialogos.clear()
    esperar(40)


def usar(c, nome):
    if isinstance(c, QCheckBox):
        c.click()
        c.click()
    elif isinstance(c, QAbstractButton):
        menu = c.menu() if hasattr(c, 'menu') else None
        if menu:
            acoes = [a for a in menu.actions() if not a.isSeparator()]
            for acao in acoes:
                vistos.append(f"{nome}/QAction:{acao.text()}")
            return acoes
        c.click()
    elif isinstance(c, QComboBox):
        for i in range(c.count()):
            c.setCurrentIndex(i)
    elif isinstance(c, QLineEdit):
        c.setText('abc')
        c.setText('')
    elif isinstance(c, QListWidget):
        for i in range(min(c.count(), 3)):
            c.setCurrentRow(i)
    elif isinstance(c, (QSlider, QSpinBox)):
        c.setValue(c.minimum())
        c.setValue(c.maximum())
    return []


def varrer_janela(raiz, nome):
    """Lists a dialog's controls and uses the ones that can't leave it."""
    foto(raiz, nome)
    for c in controles(raiz):
        vistos.append(f'{nome}/{rotulo_de(c)}')
        texto = c.text() if isinstance(c, QAbstractButton) else ''
        if texto not in ('Create', 'Clone', 'OK', 'Cancel', 'Close'):
            usar(c, nome)
            esperar(40)


def varrer(nome, ir, painel):
    raiz = ir()
    esperar()
    foto(raiz, nome)
    quantos = len(controles(raiz))
    for i in range(quantos):
        raiz = ir()
        esperar(50)
        lista = controles(raiz)
        if i >= len(lista):
            break
        c = lista[i]
        rotulo = rotulo_de(c)
        vistos.append(f'{nome}/{rotulo}')
        antes = len(erros)
        acoes = usar(c, nome)
        esperar()
        for acao in acoes:
            acao.trigger()
            esperar(60)
            aberto(nome, f'{rotulo}/{acao.text()}')
            raiz = ir()
        aberto(nome, rotulo)
        if len(erros) > antes:
            print('FAIL', nome, rotulo, erros[-1].splitlines()[-1])
        fechar_tudo(painel)


def aberto(nome, rotulo):
    for tipo, d in list(dialogos):
        if tipo == 'dialog':
            varrer_janela(d, f"{nome}/{d.windowTitle() or rotulo}")
            d.close()
        elif tipo == 'menu':
            for acao in d.actions():
                if not acao.isSeparator():
                    vistos.append(f'{nome}/{rotulo}/QAction:{acao.text()}')
                    acao.trigger()
                    esperar(40)
    dialogos.clear()


def pequenas(painel):
    """The waiting and opening windows, with their click to skip."""
    for app in ('java', 'web', 'standard'):
        fechar_tudo(painel)
        p = hub.CLASSES['Partida'](app, '', True)
        pulou = []
        p.pular = lambda: pulou.append(1)
        p.show()
        esperar(120)
        foto(p, f'{app}-wait')
        p.etapa('extensions')
        foto(p, f'{app}-wait-extensions')
        p.mouseReleaseEvent(None)
        if not pulou:
            erros.append(f'{app}: click did not skip the wait')
        p.aviso('Still loading in the background')
        foto(p, f'{app}-wait-timeout')
        p.close()
    feito = []
    a = hub.CLASSES['Abertura'](lambda: feito.append(1))
    a.barco.viagem = .55
    a.show()
    esperar(120)
    foto(a, 'opening')
    a.mouseReleaseEvent(None)
    esperar(300)
    if not feito:
        erros.append('click did not skip the opening')


def roteiro():
    painel = next(w for w in QApplication.topLevelWidgets() if type(w).__name__ == 'Painel' and w.isVisible())

    def pagina(p):
        def ir():
            fechar_tudo(painel)
            if not painel.isVisible():
                painel.show()
            painel.miolo.ir(p)
            esperar(40)
            return painel
        return ir

    def boas(app, titulo):
        def ir():
            fechar_tudo(painel)
            painel.boasvindas(app, titulo)
            esperar(40)
            return painel.tela
        return ir

    telas = [('hub-cargo', pagina(painel.ferramentas)), ('hub-projects', pagina(painel.projetos)),
             ('hub-settings', pagina(painel.gerais))]
    for app in ('java', 'web', 'standard'):
        for titulo in ('Projects', 'Customize', 'Plugins', 'Learn'):
            telas.append((f'{app}-{titulo.lower()}', boas(app, titulo)))
    for nome, ir in telas:
        print('--', nome, flush=True)
        varrer(nome, ir, painel)

    pequenas(painel)
    atual = sorted(set(vistos))
    conhecidos = LISTA.read_text(encoding='utf8').splitlines() if LISTA.exists() else []
    novos, sumidos = sorted(set(atual) - set(conhecidos)), sorted(set(conhecidos) - set(atual))
    if ESCREVER:
        LISTA.write_text('\n'.join(atual) + '\n', encoding='utf8')
    else:
        for x in novos:
            print('FAIL new control without review:', x)
        for x in sumidos:
            print('FAIL control disappeared:', x)
    for a in sorted(set(avisos)):
        print('NOTE', a)
    print('links', sorted(set(links)))
    print(f'{len(atual)} controls, {len(set(erros))} errors')
    for e in sorted(set(erros))[:12]:
        print('ERROR', e)
    ruim = erros or (not ESCREVER and (novos or sumidos))
    print('failed' if ruim else 'all passed', flush=True)
    shutil.rmtree(TEMP, ignore_errors=True)
    os._exit(1 if ruim else 0)


QApplication.exec = lambda *a: (QTimer.singleShot(200, roteiro), QEventLoop().exec())[1]
sys.argv = ['hub']
sys.exit(hub.main())
