"""Clicks through a fresh package with the real mouse: Hub, Java, New Project, Create."""
import re
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


def main():
    hub = subprocess.Popen([PACOTE / 'Hub.exe'])
    try:
        achar(hub.pid, 'Java', 60)
        foto('1-panel')
        clicar(hub.pid, 'Java')
        achar(hub.pid, 'New Project.*')
        foto('2-welcome')
        clicar(hub.pid, 'New Project.*')
        achar(hub.pid, 'Create')
        foto('3-new-project')
        clicar(hub.pid, 'Create')
        time.sleep(3)
        foto('4-boat')
        hub.wait(timeout=150)
    except BaseException:
        foto('failed')
        raise
    print('hub closed', hub.returncode, flush=True)
    time.sleep(6)
    foto('5-editor')
    etapa = (PACOTE / 'data/java/tools/etapa').read_text(encoding='utf8').strip()
    print('stage', etapa, flush=True)
    if etapa != 'ready':
        raise SystemExit(f'editor not ready: {etapa}')
    titulos = [j.window_text() for j in Desktop(backend='uia').windows()]
    print('windows', titulos, flush=True)
    if not any('untitled' in t for t in titulos):
        raise SystemExit('project window missing')


if __name__ == '__main__':
    main()
