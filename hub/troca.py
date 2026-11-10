"""Replaces the installed package with a new one, and puts the old one back if anything fails.

The swap itself is only renames inside one disk, so it either finishes or is undone.
Nothing under data/ is touched except data/<app>/extensions, which the package owns.

Steps, and the protocol that every later version has to keep:
  1. The running Hub unpacks the new package next to the install, in `area(raiz)`,
     copies its own program to <area>/helper and runs:  helper/Hub --swap <root> <area> <pid>
     Windows refuses to rename a program that is running, so the copy does the work.
  2. The helper waits for <pid> to end, swaps, and runs:  <root>/Hub --updated <area>
  3. The new Hub migrates the settings and writes <area>/ok. Without that file in time,
     the helper restores the old version and runs:  <root>/Hub --update-failed <area>
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
import zlib
from pathlib import Path

JANELAS = sys.platform == 'win32'
PROGRAMA = 'Hub.exe' if JANELAS else 'Hub'
ESPERA = 120  # seconds the new Hub has to say it started
LIVRE = 3 << 30  # bytes the download, the unpacked copy and the helper need together
AJUSTES = ('hub.json', '*/defaults.json', '*/user/User/settings.json', '*/user/User/keybindings.json')


class Falha(OSError):
    """An update step failed; the text is shown to the person."""


def area(raiz):
    """Work folder beside the install: same disk, so every move is a rename."""
    raiz = Path(raiz)
    return raiz.parent / f'.{raiz.name}-update'


def impedimento(raiz):
    """Why this install cannot update itself, or '' when it can."""
    raiz = Path(raiz)
    if not os.access(raiz, os.W_OK) or not os.access(raiz.parent, os.W_OK):
        return f'{raiz.parent} is read-only for this account.'
    if shutil.disk_usage(raiz.parent).free < LIVRE:
        return f'Less than {LIVRE >> 30} GB free in {raiz.parent}.'
    return ''


def extrair(arquivo, destino):
    """Unpacks the package and returns the folder that holds brand.json."""
    destino = Path(destino)
    destino.mkdir(parents=True)
    try:
        if zipfile.is_zipfile(arquivo):
            with zipfile.ZipFile(arquivo) as z:
                z.extractall(destino)
        else:
            with tarfile.open(arquivo) as t:
                t.extractall(destino, filter='data')
    except (tarfile.TarError, zipfile.BadZipFile, EOFError, ValueError, zlib.error) as e:
        raise Falha(f'The package could not be unpacked: {e}') from e
    achados = [p.parent for p in destino.glob('*/brand.json')]
    if (destino / 'brand.json').exists():
        achados.append(destino)
    if len(achados) != 1:
        raise Falha('The package has an unexpected layout.')
    return achados[0]


def conferir(nova, versao=None):
    """Refuses a package that is not a whole Berthline of the expected version."""
    try:
        marca = json.loads((nova / 'brand.json').read_text(encoding='utf8'))
    except (OSError, ValueError) as e:
        raise Falha('The package has no readable brand.json.') from e
    if versao and marca.get('version') != versao:
        raise Falha(f"The package is version {marca.get('version')}, not {versao}.")
    for nome in (PROGRAMA, '_hub', 'editor', 'profiles', 'data'):
        if not (nova / nome).exists():
            raise Falha(f'The package is missing {nome}.')
    return marca


def ident(pasta):
    """'redhat.java-1.58.0-linux-x64' -> 'redhat.java'"""
    m = re.match(r'(.+?)-\d+\.\d+', pasta)
    return (m.group(1) if m else pasta).lower()


def empacotadas(raiz, app):
    """Extension folders the installed package shipped, or None when it kept no list (0.2.0)."""
    try:
        return set(json.loads((Path(raiz) / 'profiles' / app / 'packaged.json').read_text(encoding='utf8')))
    except (OSError, ValueError):
        return None


def levar_extensoes(raiz, nova):
    """Copies into the new package the extensions the person installed on their own.

    The install is only read here. An extension the new package also ships keeps the package's version.
    """
    for antiga in sorted((Path(raiz) / 'data').glob('*/extensions')):
        app = antiga.parent.name
        destino = Path(nova) / 'data' / app / 'extensions'
        if not destino.is_dir():
            continue
        do_pacote = empacotadas(raiz, app)
        novas = {ident(p.name) for p in destino.iterdir() if p.is_dir()}
        levadas = []
        for pasta in sorted(antiga.iterdir()):
            if not pasta.is_dir() or pasta.name.startswith('.'):
                continue
            if (do_pacote is not None and pasta.name in do_pacote) or ident(pasta.name) in novas:
                continue
            shutil.copytree(pasta, destino / pasta.name, symlinks=True)
            levadas.append(pasta.name)
        if not levadas:
            continue
        try:
            velho = json.loads((antiga / 'extensions.json').read_text(encoding='utf8'))
            novo = json.loads((destino / 'extensions.json').read_text(encoding='utf8'))
        except (OSError, ValueError):
            continue
        novo += [e for e in velho if e.get('relativeLocation') in levadas]
        (destino / 'extensions.json').write_text(json.dumps(novo), encoding='utf8')


def preparar_pacote(raiz, arquivo, versao=None):
    """Unpacks and checks a downloaded package inside the work folder. The install stays as it is."""
    raiz, arquivo = Path(raiz), Path(arquivo)
    area_ = area(raiz)
    if arquivo.parent != area_:
        shutil.rmtree(area_, ignore_errors=True)
    area_.mkdir(parents=True, exist_ok=True)
    try:
        nova = extrair(arquivo, area_ / 'new')
        marca = conferir(nova, versao)
        levar_extensoes(raiz, nova)
    except OSError:
        shutil.rmtree(area_, ignore_errors=True)
        raise
    if arquivo.parent == area_:
        arquivo.unlink()
    (area_ / 'state.json').write_text(json.dumps({'new': str(nova), 'version': marca['version']}), encoding='utf8')
    return area_


def plano(raiz, nova, guarda):
    """The renames of the swap, in order. Only what the new package brings is replaced."""
    passos = []
    nomes = sorted(p.name for p in nova.iterdir() if p.name != 'data')
    for nome in nomes:
        if (raiz / nome).exists():
            passos.append((raiz / nome, guarda / nome))
    for nome in nomes:
        passos.append((nova / nome, raiz / nome))
    for extensoes in sorted((nova / 'data').glob('*/extensions')):
        parte = extensoes.relative_to(nova)
        if (raiz / parte).exists():
            passos.append((raiz / parte, guarda / parte))
        passos.append((extensoes, raiz / parte))
    return passos


def mover(origem, destino):
    for tentativa in range(6):  # on Windows an antivirus or the indexer can hold a file for a moment
        try:
            return os.rename(origem, destino)
        except PermissionError:
            if tentativa == 5:
                raise
            time.sleep(0.5)


def executar(passos, mover_=mover):
    """Runs the renames; on the first failure, undoes the ones already done and raises Falha."""
    feitos, criadas = [], []
    try:
        for origem, destino in passos:
            for pai in reversed([p for p in destino.parents if not p.exists()]):
                pai.mkdir()
                criadas.append(pai)
            mover_(origem, destino)
            feitos.append((origem, destino))
    except OSError as e:
        desfazer(feitos, criadas)
        raise Falha(f'Could not replace {origem.name}: {e}') from e
    return criadas


def desfazer(feitos, criadas=()):
    """Reverses renames, last first. Tries every one before reporting what could not go back."""
    erros = []
    for origem, destino in reversed(feitos):
        try:
            if os.path.lexists(destino) and not os.path.lexists(origem):
                mover(destino, origem)
        except OSError as e:
            erros.append(f'{origem}: {e}')
    for pasta in reversed(criadas):
        try:
            pasta.rmdir()
        except OSError:
            pass
    if erros:
        raise Falha('The old version could not be fully restored: ' + '; '.join(erros))


def guardar_ajustes(raiz, copia):
    """Copies the small files a newer version may rewrite, so a rollback returns them too."""
    dados = Path(raiz) / 'data'
    shutil.rmtree(copia, ignore_errors=True)
    for padrao in AJUSTES:
        for arquivo in dados.glob(padrao):
            alvo = Path(copia) / arquivo.relative_to(dados)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arquivo, alvo)


def restaurar_ajustes(raiz, copia):
    for arquivo in Path(copia).rglob('*'):
        if arquivo.is_file():
            alvo = Path(raiz) / 'data' / arquivo.relative_to(copia)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arquivo, alvo)


def trocar(raiz, area_, mover_=mover):
    """Swaps the install for the unpacked package. Raises Falha with everything back in place."""
    raiz, area_ = Path(raiz), Path(area_)
    try:
        nova = Path(json.loads((area_ / 'state.json').read_text(encoding='utf8'))['new'])
    except (OSError, ValueError, KeyError) as e:
        raise Falha('The update was not prepared.') from e
    guardar_ajustes(raiz, area_ / 'settings')
    passos = plano(raiz, nova, area_ / 'old')
    diario = {'steps': [[str(a), str(b)] for a, b in passos], 'made': []}
    (area_ / 'plan.json').write_text(json.dumps(diario), encoding='utf8')
    diario['made'] = [str(p) for p in executar(passos, mover_)]
    (area_ / 'plan.json').write_text(json.dumps(diario), encoding='utf8')


def voltar(raiz, area_):
    """Undoes a finished swap: the old program, its extensions and the saved settings return."""
    raiz, area_ = Path(raiz), Path(area_)
    diario = json.loads((area_ / 'plan.json').read_text(encoding='utf8'))
    desfazer([(Path(a), Path(b)) for a, b in diario['steps']], [Path(p) for p in diario.get('made', [])])
    restaurar_ajustes(raiz, area_ / 'settings')


def ambiente():
    """A packaged Hub's own library paths must not reach another copy of the program."""
    amb = dict(os.environ)
    original = amb.pop('LD_LIBRARY_PATH_ORIG', None)
    amb.pop('LD_LIBRARY_PATH', None)
    if original:
        amb['LD_LIBRARY_PATH'] = original
    for nome in ['QT_PLUGIN_PATH', 'QML2_IMPORT_PATH', *[n for n in amb if n.startswith('_PYI_')]]:
        amb.pop(nome, None)
    amb['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return amb


def solto(pasta):
    """Popen options for a program that must outlive this one."""
    extra = ({'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if JANELAS
             else {'start_new_session': True})
    return {'cwd': str(pasta), 'env': ambiente(), 'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
            'stderr': subprocess.DEVNULL, **extra}


def iniciar(raiz, area_, pid=None):
    """Hands the swap to a copy of this program and returns at once; the caller must then quit."""
    raiz, area_ = Path(raiz), Path(area_)
    if getattr(sys, 'frozen', False):
        origem = Path(sys.executable).parent
        ajudante = area_ / 'helper'
        shutil.rmtree(ajudante, ignore_errors=True)
        ajudante.mkdir(parents=True)
        shutil.copy2(origem / PROGRAMA, ajudante)
        shutil.copytree(origem / '_hub', ajudante / '_hub', symlinks=True)
        comando = [str(ajudante / PROGRAMA)]
    else:
        comando = [sys.executable, str(Path(__file__).with_name('hub.py'))]
    return subprocess.Popen(comando + ['--swap', str(raiz), str(area_), str(pid or os.getpid())], **solto(area_))


def anotar(area_, texto):
    try:
        with (Path(area_) / 'log.txt').open('a', encoding='utf8') as f:
            f.write(f'{time.strftime("%H:%M:%S")} {texto}\n')
    except OSError:
        pass


def aplicar(raiz, area_, pid, vivo, espera=ESPERA):
    """The helper's whole job. Returns 0 when the new version started, 1 when the old one is back."""
    raiz, area_ = Path(raiz), Path(area_)
    fim = time.time() + 60
    while vivo(pid) and time.time() < fim:
        time.sleep(0.2)
    if vivo(pid):
        return falhou(raiz, area_, 'The Hub did not close.')
    try:
        trocar(raiz, area_)
    except OSError as e:
        return falhou(raiz, area_, str(e))
    anotar(area_, 'swapped')
    try:
        novo = subprocess.Popen([str(raiz / PROGRAMA), '--updated', str(area_)], **solto(raiz))
    except OSError as e:
        motivo = f'The new version did not start: {e}'
    else:
        fim = time.time() + espera
        while time.time() < fim and novo.poll() is None and not (area_ / 'ok').exists():
            time.sleep(0.2)
        if (area_ / 'ok').exists():
            anotar(area_, 'new version confirmed')
            return 0
        motivo = ('The new version did not start in time.' if novo.poll() is None
                  else f'The new version stopped while starting (code {novo.returncode}).')
        if novo.poll() is None:
            novo.kill()
        novo.wait()
    try:
        voltar(raiz, area_)
    except (OSError, ValueError, KeyError) as e:
        motivo = f'{motivo} {e}'
    return falhou(raiz, area_, motivo)


def falhou(raiz, area_, motivo):
    anotar(area_, f'failed: {motivo}')
    try:
        (area_ / 'error.txt').write_text(motivo, encoding='utf8')
        subprocess.Popen([str(raiz / PROGRAMA), '--update-failed', str(area_)], **solto(raiz))
    except OSError as e:
        anotar(area_, f'old version did not start: {e}')
    return 1


def confirmar(area_):
    """Called by the new Hub once it is safe to keep it."""
    (Path(area_) / 'ok').write_text('ok', encoding='utf8')


def limpar(area_, espera=4):
    """Removes the work folder; the helper may still hold its own files for a moment."""
    time.sleep(espera)
    for _ in range(10):
        shutil.rmtree(area_, ignore_errors=True)
        if not Path(area_).exists():
            return
        time.sleep(2)
