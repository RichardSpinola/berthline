"""Qt allows one application object per process. Making a shortcut icon (as `--updated` does before the
window opens) must not leave a QGuiApplication that stops the Hub's QApplication from being created."""
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(tempfile.mkdtemp(prefix='qapp-'))
os.environ['SUITE_ROOT'] = str(RAIZ)
os.environ['HOME'] = str(RAIZ / 'home')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
AQUI = Path(__file__).parent.parent
sys.path.insert(0, str(AQUI / 'hub'))
import hub  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

hub.ASSETS = AQUI / 'hub/assets'
falhas = []


def passo(nome, ok, extra=''):
    print('OK  ' if ok else 'FAIL', nome, extra)
    if not ok:
        falhas.append(nome)


icone = hub.imagem_icone('hub', 'png')
passo('icon is written', icone.is_file() and icone.stat().st_size > 0)
passo('the process app is a QApplication', type(QGuiApplication.instance()) is QApplication, type(QGuiApplication.instance()))
try:
    janela_app = hub.app_qt()
    passo('the window reuses it', janela_app is QApplication.instance())
except RuntimeError as e:
    passo('the window can get its QApplication', False, e)
print('FAILURES:' if falhas else 'ALL OK', falhas)
sys.exit(1 if falhas else 0)
