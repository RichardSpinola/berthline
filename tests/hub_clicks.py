"""Clicks through a fresh package with the real mouse: Setup, Hub, app, New Project, Create."""
import json
import re
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import ImageGrab
from pywinauto import Desktop
from pywinauto.keyboard import send_keys

PACOTE = Path(sys.argv[1])
SAIDA = Path(sys.argv[2])
SAIDA.mkdir(parents=True, exist_ok=True)
PASTA_JAVA = Path.home() / 'Aulas'
NOMES = {'Berthline Java', 'Berthline Web', 'Berthline Standard', 'Berthline Hub'}


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


def todos(pid, nome):
    """Controls with this exact name from the top of the window down, one per place on screen."""
    achar(pid, nome)
    unicos = {}
    for c in controles(pid):
        if c.window_text() == nome:
            r = c.rectangle()
            unicos[(r.top, r.left)] = c
    return [unicos[k] for k in sorted(unicos)]


def trocar(controle):
    print('click', controle.window_text(), flush=True)
    controle.click_input()
    time.sleep(0.5)


def escrever_pasta(pid, atual, nova):
    achar(pid, 'Project folder')
    campos = []
    for c in controles(pid):
        try:
            if c.iface_value.CurrentValue == atual:
                campos.append(c)
        except Exception:  # most controls have no value
            pass
    if not campos:
        raise SystemExit('project folder field not found')
    min(campos, key=lambda c: c.rectangle().top).click_input()
    send_keys('^a')
    send_keys(nova, with_spaces=True)
    time.sleep(0.5)


def esperar_fechar(pid, titulo, segundos=60):
    fim = time.time() + segundos
    while time.time() < fim:
        try:
            if not any(re.fullmatch(titulo, j.window_text() or '') for j in Desktop(backend='uia').windows(process=pid)):
                return
        except Exception:  # a window can vanish while it is being read
            pass
        time.sleep(0.5)
    raise SystemExit(f'window still open: {titulo}')


def atalhos(pasta):
    return {f.stem for f in pasta.glob('*.lnk')}


def preparar_tudo(pid):
    """Nothing starts ticked. Web gets no shortcut, the Hub stays off the app menu, Java moves folder, all apps go light."""
    achar(pid, 'Set up .*')
    foto('setup-1-first-use')
    desktop = todos(pid, 'Desktop')
    menu = todos(pid, 'Menu')
    if len(desktop) != 4 or len(menu) != 3:
        raise SystemExit(f'setup rows: {len(desktop)} desktop, {len(menu)} menu')
    for caixa in (desktop[0], desktop[2], desktop[3], menu[0], menu[2]):
        trocar(caixa)
    escrever_pasta(pid, '~\\Projects', str(PASTA_JAVA))
    clicar(pid, 'Light')
    foto('setup-2-chosen')
    clicar(pid, 'Finish')
    esperar_fechar(pid, 'Set up .*')  # the shortcuts are written before the window closes
    mesa = Path(subprocess.run(['powershell', '-NoProfile', '-Command', "[Environment]::GetFolderPath('Desktop')"],
                               capture_output=True, text=True, check=True).stdout.strip())
    inicio = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs'
    if atalhos(mesa) & NOMES != NOMES - {'Berthline Web'}:
        raise SystemExit(f'desktop shortcuts: {sorted(atalhos(mesa))}')
    if atalhos(inicio) & NOMES != NOMES - {'Berthline Web', 'Berthline Hub'}:
        raise SystemExit(f'menu shortcuts: {sorted(atalhos(inicio))}')
    for app in ('java', 'web', 'standard'):
        ajustes = json.loads((PACOTE / f'data/{app}/user/User/settings.json').read_text(encoding='utf8'))
        if ajustes.get('workbench.colorTheme') not in ('Islands Light', 'Default Light Modern'):
            raise SystemExit(f'{app} theme: {ajustes.get("workbench.colorTheme")}')
    if not PASTA_JAVA.is_dir():
        raise SystemExit(f'folder not created: {PASTA_JAVA}')


def nomear(pid, nome):
    for c in controles(pid):
        try:
            if c.iface_value.CurrentValue == 'untitled':
                c.click_input()
                send_keys('^a' + nome)
                time.sleep(1)
                return
        except Exception:  # most controls have no value
            pass
    raise SystemExit('project name field not found')


def fechar_editor():
    filtro = f"Get-Process | Where-Object {{ $_.Path -like '{PACOTE}*' }} | Stop-Process -Force"
    subprocess.run(['powershell', '-NoProfile', '-Command', filtro], check=False)
    time.sleep(3)


def testar(app):
    pasta = app.lower()
    hub = subprocess.Popen([PACOTE / 'Hub.exe'])
    try:
        if app == 'Java':  # the first run always opens on Setup
            preparar_tudo(hub.pid)
        achar(hub.pid, app, 60)
        foto(f'{pasta}-1-panel')
        clicar(hub.pid, app)
        achar(hub.pid, 'New Project.*')
        foto(f'{pasta}-2-welcome')
        clicar(hub.pid, 'New Project.*')
        achar(hub.pid, 'Create')
        nomear(hub.pid, f'aula-{pasta}')
        foto(f'{pasta}-3-new-project')
        clicar(hub.pid, 'Create')
        time.sleep(3)
        foto(f'{pasta}-4-boat')
        hub.wait(timeout=150)
    except BaseException:
        foto(f'{pasta}-failed')
        fechar_editor()  # the job waits for every process it started, so nothing may stay open
        raise
    print(app, 'hub closed', hub.returncode, flush=True)
    time.sleep(6)
    foto(f'{pasta}-5-editor')
    etapa = (PACOTE / f'data/{pasta}/tools/etapa').read_text(encoding='utf8').strip()
    titulos = [j.window_text() for j in Desktop(backend='uia').windows()]
    print(app, 'stage', etapa, 'windows', titulos, flush=True)
    if etapa != 'ready':
        raise SystemExit(f'{app} editor not ready: {etapa}')
    if not any(f'aula-{pasta}' in t for t in titulos):
        raise SystemExit(f'{app} project window missing')
    if app == 'Java' and not (PASTA_JAVA / 'aula-java').is_dir():
        raise SystemExit(f'project is not in the chosen folder: {PASTA_JAVA}')
    fechar_editor()


if __name__ == '__main__':
    for app_ in ('Java', 'Web', 'Standard'):
        testar(app_)
