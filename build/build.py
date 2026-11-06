#!/usr/bin/env python3
"""Builds the portable package for the current system."""
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
JANELAS = sys.platform == 'win32'
CACHE = RAIZ / 'build/cache'
DESTINO = RAIZ / 'dist' / ('berthline-windows' if JANELAS else 'berthline-linux')
VERSOES = json.loads((RAIZ / 'build/versions.json').read_text())
SEM_VERIFICAR = '--no-signature-check' in sys.argv


def baixar(url, nome):
    CACHE.mkdir(parents=True, exist_ok=True)
    alvo = CACHE / nome
    if not alvo.exists():
        print('download', url, flush=True)
        urllib.request.urlretrieve(url, alvo)
    return alvo


def soma(arquivo):
    h = hashlib.sha256()
    with open(arquivo, 'rb') as f:
        for bloco in iter(lambda: f.read(1 << 20), b''):
            h.update(bloco)
    return h.hexdigest()


def extrair(arquivo, pasta):
    if str(arquivo).endswith('.zip'):
        zipfile.ZipFile(arquivo).extractall(pasta)
    else:
        with tarfile.open(arquivo) as t:
            t.extractall(pasta, filter='tar')


def editor():
    v = VERSOES['editor']
    plataforma = 'win32-x64' if JANELAS else 'linux-x64'
    nome = f"VSCodium-{plataforma}-{v}.{'zip' if JANELAS else 'tar.gz'}"
    url = f'https://github.com/VSCodium/vscodium/releases/download/{v}/{nome}'
    arquivo = baixar(url, nome)
    with urllib.request.urlopen(f'{url}.sha256') as r:
        esperado = r.read().decode().split()[0]
    if soma(arquivo) != esperado:
        sys.exit('editor hash mismatch')
    (DESTINO / 'editor').mkdir()
    extrair(arquivo, DESTINO / 'editor')


def node():
    v = VERSOES['node']
    nome = f'node-v{v}-win-x64.zip' if JANELAS else f'node-v{v}-linux-x64.tar.xz'
    arquivo = baixar(f'https://nodejs.org/dist/v{v}/{nome}', nome)
    with urllib.request.urlopen(f'https://nodejs.org/dist/v{v}/SHASUMS256.txt') as r:
        somas = dict(reversed(l.split()) for l in r.read().decode().splitlines())
    if soma(arquivo) != somas[nome]:
        sys.exit('node hash mismatch')
    temp = CACHE / 'node-temp'
    shutil.rmtree(temp, ignore_errors=True)
    extrair(arquivo, temp)
    shutil.move(str(next(temp.iterdir())), DESTINO / 'node')
    shutil.rmtree(temp, ignore_errors=True)


def vsix():
    alvo = CACHE / 'berthline-tools.vsix'
    CACHE.mkdir(parents=True, exist_ok=True)
    versao = json.loads((RAIZ / 'extension/package.json').read_text(encoding='utf8'))['version']
    manifesto = (RAIZ / 'build/extension.vsixmanifest').read_text()
    with zipfile.ZipFile(alvo, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('extension.vsixmanifest', manifesto.replace('Version="0.1.0"', f'Version="{versao}"'))
        z.write(RAIZ / 'build/[Content_Types].xml', '[Content_Types].xml')
        for f in (RAIZ / 'extension').rglob('*'):
            if f.is_file():
                z.write(f, Path('extension') / f.relative_to(RAIZ / 'extension'))
    return alvo


def instalar(app, nome, pacote):
    cli = DESTINO / 'editor/bin' / ('codium.cmd' if JANELAS else 'codium')
    temp = CACHE / 'cli-user'
    (temp / 'User').mkdir(parents=True, exist_ok=True)
    (temp / 'User/settings.json').write_text(json.dumps({'extensions.verifySignature': not SEM_VERIFICAR}))
    r = subprocess.run([str(cli), f'--user-data-dir={temp}', f"--extensions-dir={DESTINO / 'data' / app / 'extensions'}",
                        '--install-extension', str(pacote), '--force'], capture_output=True, text=True, shell=JANELAS)
    if 'successfully installed' not in r.stdout + r.stderr:
        sys.exit(f'{nome} failed: {(r.stdout + r.stderr)[-400:]}')
    print('ok', app, nome, flush=True)


def hub():
    trabalho = RAIZ / 'build/work'
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed', '--onedir', '--name', 'Hub',
                    '--contents-directory', '_hub', '--distpath', str(trabalho / 'dist'),
                    '--workpath', str(trabalho / 'obj'), '--specpath', str(trabalho), '--icon', str(trabalho / 'berthline.ico'),
                    str(RAIZ / 'hub/hub.py')], check=True)
    shutil.copytree(trabalho / 'dist/Hub', DESTINO, dirs_exist_ok=True)


def marcar():
    """Separa o editor de qualquer VS Code instalado e aplica o nome da marca."""
    marca = json.loads((RAIZ / 'brand.json').read_text())
    arquivo = DESTINO / 'editor/resources/app/product.json'
    produto = json.loads(arquivo.read_text(encoding='utf8'))
    produto.update({
        'nameShort': marca['name'], 'nameLong': marca['name'],
        'dataFolderName': marca['folder'], 'sharedDataFolderName': f"{marca['folder']}-shared",
        'win32DirName': marca['name'], 'win32NameVersion': marca['name'], 'linuxIconName': 'berthline',
    })
    for chave, valor in list(produto.items()):
        if chave.startswith('win32') and isinstance(valor, str) and 'VSCodium' in valor:
            produto[chave] = valor.replace('VSCodium', marca['name'])
    for chave in ('reportIssueUrl', 'releaseNotesUrl', 'documentationUrl', 'requestFeatureUrl'):
        produto.pop(chave, None)
    arquivo.write_text(json.dumps(produto, indent='\t', ensure_ascii=False), encoding='utf8')
    shutil.copy(RAIZ / 'brand.json', DESTINO)
    logos()


def logos():
    """Troca os logos do editor pelos da marca."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    origem = RAIZ / 'hub/assets/hub.svg'
    media = DESTINO / 'editor/resources/app/out/media'
    for nome in ('code-icon.svg', 'vscode-icon.svg'):
        shutil.copy(origem, media / nome)
    desenho = origem.read_text()
    for nome, cor in (('letterpress-dark.svg', '#35383D'), ('letterpress-hcDark.svg', '#35383D'),
                      ('letterpress-light.svg', '#DADADA'), ('letterpress-hcLight.svg', '#DADADA')):
        (media / nome).write_text(re.sub(r'fill="#[0-9A-Fa-f]{6}"', f'fill="{cor}"', desenho))
    imagem = QImage(512, 512, QImage.Format_ARGB32)
    imagem.fill(Qt.transparent)
    pintor = QPainter(imagem)
    QSvgRenderer(str(origem)).render(pintor)
    pintor.end()
    png = DESTINO / 'editor/resources/app/resources/linux/code.png'
    if png.exists():
        imagem.save(str(png))
    trabalho = RAIZ / 'build/work'
    trabalho.mkdir(parents=True, exist_ok=True)
    imagem.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(trabalho / 'berthline.ico'))
    if JANELAS:
        rcedit = baixar('https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe', 'rcedit.exe')
        exe = DESTINO / 'editor/VSCodium.exe'
        subprocess.run([str(rcedit), str(exe), '--set-icon', str(trabalho / 'berthline.ico'),
                        '--set-version-string', 'ProductName', marca_nome(), '--set-version-string', 'FileDescription', marca_nome()], check=True)


def marca_nome():
    return json.loads((RAIZ / 'brand.json').read_text())['name']


def so_hub():
    marcar()
    shutil.rmtree(DESTINO / 'profiles')
    shutil.copytree(RAIZ / 'profiles', DESTINO / 'profiles')
    shutil.copytree(RAIZ / 'hub/assets', DESTINO / 'assets', dirs_exist_ok=True)
    hub()


def main():
    if '--hub-only' in sys.argv:
        return so_hub()
    shutil.rmtree(DESTINO, ignore_errors=True)
    DESTINO.mkdir(parents=True)
    editor()
    node()
    marcar()
    shutil.copytree(RAIZ / 'profiles', DESTINO / 'profiles')
    shutil.copytree(RAIZ / 'hub/assets', DESTINO / 'assets')
    shutil.copy(RAIZ / 'README.md', DESTINO)
    shutil.copy(RAIZ / 'NOTICE', DESTINO)
    hub()
    pacote = vsix()
    for lista in sorted((RAIZ / 'profiles').glob('*/extensions.txt')):
        app = lista.parent.name
        itens = [l.strip() for l in lista.read_text().splitlines() if l.strip()]
        for item in itens:
            instalar(app, item, item)
        if itens:
            instalar(app, 'berthline-tools', pacote)
    if JANELAS:
        (DESTINO / 'Start-Java.bat').write_text('@start "" "%~dp0Hub.exe" --open java\r\n')
        (DESTINO / 'Start-Web.bat').write_text('@start "" "%~dp0Hub.exe" --open web\r\n')
    print('done', DESTINO)


if __name__ == '__main__':
    os.chdir(RAIZ)
    main()
