#!/usr/bin/env python3
"""Builds the portable package for the current system."""
import hashlib
import json
import os
import platform
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
DESTINO = RAIZ / 'dist' / ('code-suite-windows' if JANELAS else 'code-suite-linux')
VERSOES = json.loads((RAIZ / 'build/versions.json').read_text())
PLATAFORMA = 'win32-x64-archive' if JANELAS else 'linux-x64'
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
    with urllib.request.urlopen(f'https://update.code.visualstudio.com/api/versions/{v}/{PLATAFORMA}/stable') as r:
        info = json.load(r)
    extensao = 'zip' if JANELAS else 'tar.gz'
    arquivo = baixar(f'https://update.code.visualstudio.com/{v}/{PLATAFORMA}/stable', f'editor-{v}.{extensao}')
    if soma(arquivo) != info['sha256hash']:
        sys.exit('editor hash mismatch')
    temp = CACHE / 'editor-temp'
    shutil.rmtree(temp, ignore_errors=True)
    extrair(arquivo, temp)
    interna = next(p for p in temp.iterdir()) if not JANELAS else temp
    shutil.move(str(interna), DESTINO / 'editor')
    shutil.rmtree(temp, ignore_errors=True)


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
    alvo = CACHE / 'suite-tools.vsix'
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
    cli = DESTINO / 'editor/bin' / ('code.cmd' if JANELAS else 'code')
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
                    '--workpath', str(trabalho / 'obj'), '--specpath', str(trabalho), str(RAIZ / 'hub/hub.py')], check=True)
    shutil.copytree(trabalho / 'dist/Hub', DESTINO, dirs_exist_ok=True)


def marcar():
    """Separa o editor de qualquer VS Code instalado e aplica o nome da marca."""
    marca = json.loads((RAIZ / 'brand.json').read_text())
    arquivo = DESTINO / 'editor/resources/app/product.json'
    produto = json.loads(arquivo.read_text(encoding='utf8'))
    produto.update({
        'nameShort': marca['name'], 'nameLong': marca['name'],
        'dataFolderName': marca['folder'], 'sharedDataFolderName': f"{marca['folder']}-shared",
    })
    arquivo.write_text(json.dumps(produto, indent='\t', ensure_ascii=False), encoding='utf8')
    shutil.copy(RAIZ / 'brand.json', DESTINO)


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
            instalar(app, 'suite-tools', pacote)
    if JANELAS:
        (DESTINO / 'Start-Java.bat').write_text('@start "" "%~dp0Hub.exe" --open java\r\n')
        (DESTINO / 'Start-Web.bat').write_text('@start "" "%~dp0Hub.exe" --open web\r\n')
    print('done', DESTINO)


if __name__ == '__main__':
    os.chdir(RAIZ)
    main()
