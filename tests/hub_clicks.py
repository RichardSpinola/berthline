"""Clicks through a fresh package with the real mouse: Hub, app, New Project, Create."""
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PIL import ImageGrab
from pywinauto import Desktop

PACOTE = Path(sys.argv[1])
SAIDA = Path(sys.argv[2])
SAIDA.mkdir(parents=True, exist_ok=True)


def foto(nome):
    ImageGrab.grab().save(SAIDA / f'hub-{nome}.png')


def controles(pid):
    for janela in Desktop(backend='uia').windows(process=pid):
        yield janela
        yield from janela.descendants()


def achar(pid, nome, segundos=40):
    fim = time.time() + segundos
    while time.time() < fim:
        try:
            for c in controles(pid):
                if re.fullmatch(nome, c.window_text() or ''):
                    return c
        except Exception:  # a window can vanish while it is being read
            pass
        time.sleep(0.5)
    raise SystemExit(f'not found: {nome}\nseen: {sorted({c.window_text() for c in controles(pid)})}')


def clicar(pid, nome):
    alvo = achar(pid, nome)
    print('click', alvo.window_text(), flush=True)
    alvo.click_input()
    time.sleep(1.5)


def fechar_editor():
    filtro = f"Get-Process | Where-Object {{ $_.Path -like '{PACOTE}*' }} | Stop-Process -Force"
    subprocess.run(['powershell', '-NoProfile', '-Command', filtro], check=False)
    time.sleep(3)
    shutil.rmtree(Path.home() / 'Projects/untitled', ignore_errors=True)


def testar(app):
    pasta = app.lower()
    hub = subprocess.Popen([PACOTE / 'Hub.exe'])
    try:
        achar(hub.pid, app, 60)
        foto(f'{pasta}-1-panel')
        clicar(hub.pid, app)
        achar(hub.pid, 'New Project.*')
        foto(f'{pasta}-2-welcome')
        clicar(hub.pid, 'New Project.*')
        achar(hub.pid, 'Create')
        foto(f'{pasta}-3-new-project')
        clicar(hub.pid, 'Create')
        time.sleep(3)
        foto(f'{pasta}-4-boat')
        hub.wait(timeout=150)
    except BaseException:
        foto(f'{pasta}-failed')
        raise
    print(app, 'hub closed', hub.returncode, flush=True)
    time.sleep(6)
    foto(f'{pasta}-5-editor')
    etapa = (PACOTE / f'data/{pasta}/tools/etapa').read_text(encoding='utf8').strip()
    titulos = [j.window_text() for j in Desktop(backend='uia').windows()]
    print(app, 'stage', etapa, 'windows', titulos, flush=True)
    if etapa != 'ready':
        raise SystemExit(f'{app} editor not ready: {etapa}')
    if not any('untitled' in t for t in titulos):
        raise SystemExit(f'{app} project window missing')
    fechar_editor()


if __name__ == '__main__':
    for app_ in ('Java', 'Web', 'Standard'):
        testar(app_)
