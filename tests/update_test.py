"""Tests the updater: the swap, a failure in the middle of it, rollback and the settings migration.

Without arguments it uses small fake installs. With a package folder it also updates a real copy of
that package to a repacked "next version", and makes one update fail to see the old version return.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
TEMP = Path(tempfile.mkdtemp(prefix='update-'))
os.environ['SUITE_ROOT'] = str(TEMP / 'unused')
sys.path.insert(0, str(Path(__file__).parent.parent / 'hub'))
import hub  # noqa: E402
import troca  # noqa: E402

falhas = []


def passo(nome, ok, extra=''):
    print('OK  ' if ok else 'FAIL', nome, extra, flush=True)
    if not ok:
        falhas.append(nome)


def escrever(arquivo, texto):
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(texto, encoding='utf8')


def retrato(pasta):
    """Every file under a folder with its content, to compare before and after."""
    return {str(p.relative_to(pasta)): p.read_bytes() if p.is_file() else None for p in sorted(pasta.rglob('*'))}


def instalacao(raiz, versao, programa=''):
    """A small install with the same layout as the real one."""
    escrever(raiz / 'brand.json', json.dumps({'name': 'Berthline', 'version': versao}))
    escrever(raiz / troca.PROGRAMA, programa or f'program {versao}')
    (raiz / troca.PROGRAMA).chmod(0o755)
    escrever(raiz / '_hub/lib.txt', f'lib {versao}')
    escrever(raiz / 'editor/bin/codium', f'editor {versao}')
    escrever(raiz / 'profiles/java/app.json', '{}')
    extensoes = raiz / 'data/java/extensions'
    escrever(extensoes / 'redhat.java-1.0.0/package.json', f'java of {versao}')
    indice = [{'relativeLocation': 'redhat.java-1.0.0'}]
    escrever(extensoes / 'extensions.json', json.dumps(indice))
    escrever(raiz / 'profiles/java/packaged.json', json.dumps(['redhat.java-1.0.0']))
    return raiz


def usar(raiz):
    """What a person leaves behind: settings, projects list, an extension of their own, a stray file."""
    escrever(raiz / 'data/hub.json', '{"setup": true, "java": {"folder": "/aulas"}}')
    escrever(raiz / 'data/java/user/User/settings.json', '{"editor.fontSize": 21}')
    escrever(raiz / 'data/java/user/User/keybindings.json', '[]')
    escrever(raiz / 'data/java/user/workspaceStorage/abc/workspace.json', '{}')
    escrever(raiz / 'data/java/extensions/me.mine-2.0.0/package.json', 'mine')
    indice = json.loads((raiz / 'data/java/extensions/extensions.json').read_text())
    escrever(raiz / 'data/java/extensions/extensions.json', json.dumps(indice + [{'relativeLocation': 'me.mine-2.0.0'}]))
    escrever(raiz / 'notes.txt', 'mine too')


def empacotar(pasta, arquivo, nome):
    if str(arquivo).endswith('.zip'):
        with zipfile.ZipFile(arquivo, 'w', zipfile.ZIP_STORED) as z:
            for f in sorted(pasta.rglob('*')):
                z.write(f, Path(nome) / f.relative_to(pasta))
    else:
        with tarfile.open(arquivo, 'w:gz', compresslevel=1) as t:
            t.add(pasta, nome)
    return arquivo


def preparar(nome, nova_versao='0.3.0'):
    base = TEMP / nome
    raiz = instalacao(base / 'berthline', '0.2.1')
    usar(raiz)
    pacote = empacotar(instalacao(base / 'next', nova_versao), base / f"berthline.{'zip' if troca.JANELAS else 'tar.gz'}", 'berthline')
    return raiz, pacote


def troca_simples():
    raiz, pacote = preparar('plain')
    area_ = troca.preparar_pacote(raiz, pacote, '0.3.0')
    passo('work folder sits beside the install', area_.parent == raiz.parent and area_ != raiz)
    passo('install untouched while preparing', (raiz / 'brand.json').read_text() == json.dumps({'name': 'Berthline', 'version': '0.2.1'}))
    troca.trocar(raiz, area_)
    passo('program replaced', (raiz / troca.PROGRAMA).read_text() == 'program 0.3.0')
    passo('editor replaced', (raiz / 'editor/bin/codium').read_text() == 'editor 0.3.0')
    passo('packaged extension replaced', (raiz / 'data/java/extensions/redhat.java-1.0.0/package.json').read_text() == 'java of 0.3.0')
    passo('own extension carried', (raiz / 'data/java/extensions/me.mine-2.0.0/package.json').read_text() == 'mine')
    indice = [e['relativeLocation'] for e in json.loads((raiz / 'data/java/extensions/extensions.json').read_text())]
    passo('own extension listed', indice == ['redhat.java-1.0.0', 'me.mine-2.0.0'], indice)
    passo('settings kept', (raiz / 'data/java/user/User/settings.json').read_text() == '{"editor.fontSize": 21}')
    passo('hub options kept', '/aulas' in (raiz / 'data/hub.json').read_text())
    passo('workspace storage kept', (raiz / 'data/java/user/workspaceStorage/abc/workspace.json').exists())
    passo('stray file kept', (raiz / 'notes.txt').read_text() == 'mine too')
    passo('old version saved', (area_ / 'old' / troca.PROGRAMA).read_text() == 'program 0.2.1')
    # A newer version rewrites settings on its first start; going back must return them too.
    escrever(raiz / 'data/java/user/User/settings.json', '{"rewritten": true}')
    troca.voltar(raiz, area_)
    passo('rollback returns the program', (raiz / troca.PROGRAMA).read_text() == 'program 0.2.1')
    passo('rollback returns the extensions', (raiz / 'data/java/extensions/redhat.java-1.0.0/package.json').read_text() == 'java of 0.2.1')
    passo('rollback returns the settings', (raiz / 'data/java/user/User/settings.json').read_text() == '{"editor.fontSize": 21}')


def falha_no_meio():
    """The swap stops at every possible step, one run each; the install must come out as it went in."""
    raiz, pacote = preparar('broken')
    total = None
    passo_ = 0
    while total is None or passo_ < total:
        area_ = troca.preparar_pacote(raiz, empacotar_de_novo(pacote), '0.3.0')
        antes = retrato(raiz)
        feitos = []

        def mover(origem, destino):
            if len(feitos) == passo_:
                raise PermissionError(13, 'in use', str(origem))
            feitos.append(origem)
            os.rename(origem, destino)
        try:
            troca.trocar(raiz, area_, mover)
            erro = None
        except troca.Falha as e:
            erro = str(e)
        if total is None:
            total = len(json.loads((area_ / 'plan.json').read_text())['steps'])
        if retrato(raiz) != antes or not erro:
            passo(f'failure at step {passo_ + 1} of {total} leaves the install as it was', False, erro or 'no error raised')
            return
        passo_ += 1
    passo(f'a failure at any of the {total} steps leaves the install as it was', total >= 6, f'{total} steps')
    passo('the failed install still runs the old program', (raiz / troca.PROGRAMA).read_text() == 'program 0.2.1')
    area_ = troca.preparar_pacote(raiz, empacotar_de_novo(pacote), '0.3.0')
    troca.trocar(raiz, area_)
    passo('the same install updates once the fault is gone', (raiz / troca.PROGRAMA).read_text() == 'program 0.3.0')


def empacotar_de_novo(pacote):
    """preparar_pacote consumes nothing outside the work folder, so the same file serves every run."""
    return pacote


def pacotes_ruins():
    raiz, pacote = preparar('bad')
    antes = retrato(raiz)
    for nome, acao in (
        ('wrong version refused', lambda: troca.preparar_pacote(raiz, pacote, '9.9.9')),
        ('damaged package refused', lambda: troca.preparar_pacote(raiz, danificar(pacote))),
        ('package without the editor refused', lambda: troca.preparar_pacote(raiz, sem_editor(), '0.3.0')),
        ('swap without a prepared package refused', lambda: troca.trocar(raiz, troca.area(raiz))),
    ):
        try:
            acao()
            passo(nome, False, 'accepted')
        except troca.Falha as e:
            passo(nome, retrato(raiz) == antes and not (troca.area(raiz) / 'new').exists(), str(e))


def danificar(pacote):
    ruim = pacote.with_name('damaged' + ''.join(pacote.suffixes))
    ruim.write_bytes(pacote.read_bytes()[:200])
    return ruim


def sem_editor():
    pasta = instalacao(TEMP / 'bad/half', '0.3.0')
    shutil.rmtree(pasta / 'editor')
    return empacotar(pasta, TEMP / f"bad/half.{'zip' if troca.JANELAS else 'tar.gz'}", 'berthline')


def migracao():
    base = {'files.autoSave': 'afterDelay', 'editor.fontSize': 13, 'editor.tabSize': 4,
            'workbench.colorCustomizations': {'[Islands Dark]': {'sideBar.background': '#191A1C', 'tab.border': '#191A1C'}},
            'editor.semanticTokenColorCustomizations': {'[Islands Dark]': {'rules': {'property': '#C77DBB'}}}}
    velho = {'files.autoSave': 'onFocusChange', 'editor.fontSize': 16, 'editor.tabSize': 4,
             'workbench.colorCustomizations': {'sideBar.background': '#191A1C', 'tab.border': '#FF0000', 'focusBorder': '#E0641B'},
             'editor.semanticTokenColorCustomizations': {'rules': {'property': '#C77DBB'}}}
    atual = json.loads(json.dumps(velho))
    hub.migrar(atual, base, {})
    cores = atual['workbench.colorCustomizations']
    passo('old autosave default follows the new one', atual['files.autoSave'] == 'afterDelay')
    passo('a changed setting stays', atual['editor.fontSize'] == 16)
    passo('old top-level color leaves', 'sideBar.background' not in cores, cores)
    passo('a color the person changed stays', cores.get('tab.border') == '#FF0000')
    passo('accent color stays', cores.get('focusBorder') == '#E0641B')
    passo('theme colors arrive under their theme', cores.get('[Islands Dark]') == base['workbench.colorCustomizations']['[Islands Dark]'])
    passo('old token rules move under the theme', atual['editor.semanticTokenColorCustomizations'] == base['editor.semanticTokenColorCustomizations'])
    escolhido = {'files.autoSave': 'off'}
    hub.migrar(escolhido, base, {})
    passo('an autosave the person chose stays', escolhido['files.autoSave'] == 'off')
    seguinte = {'editor.tabSize': 4, 'editor.fontSize': 16}
    hub.migrar(seguinte, {**base, 'editor.tabSize': 2, 'editor.fontSize': 14}, base)
    passo('a later default change reaches untouched settings only', seguinte == {'editor.tabSize': 2, 'editor.fontSize': 16}, seguinte)


def certificados():
    contexto = hub.contexto_ssl()
    passo('certificates loaded', contexto.cert_store_stats()['x509_ca'] > 50 or not hub.certifi, contexto.cert_store_stats())
    import ssl
    import urllib.error
    textos = [hub.motivo_rede(urllib.error.URLError(ssl.SSLCertVerificationError(1, 'unable to get local issuer certificate'))),
              hub.motivo_rede(urllib.error.URLError(OSError(-2, 'Name or service not known'))),
              hub.motivo_rede(urllib.error.HTTPError('u', 403, 'rate limit', {}, None)),
              hub.motivo_rede(TimeoutError('timed out'))]
    passo('each network failure has its own message', len(set(textos)) == 4 and 'certificate' in textos[0], textos)


SCRIPT = '''#!/bin/sh
# Stands in for the Hub: version {v}. The helper starts it after the swap.
echo "{v} $@" >> "$(dirname "$0")/data/started.txt"
case "$1" in
  --updated) {novo} ;;
esac
'''


def ajudante():
    """The helper's whole route with stand-in programs: waits, swaps, confirms or goes back."""
    if troca.JANELAS:
        return
    for nome, novo, certo in (('helper-ok', 'echo ok > "$2/ok"', True), ('helper-crash', 'exit 3', False),
                              ('helper-silent', 'sleep 30', False)):
        base = TEMP / nome
        raiz = instalacao(base / 'berthline', '0.2.1', SCRIPT.format(v='0.2.1', novo='true'))
        usar(raiz)
        pacote = empacotar(instalacao(base / 'next', '0.3.0', SCRIPT.format(v='0.3.0', novo=novo)), base / 'berthline.tar.gz', 'berthline')
        area_ = troca.preparar_pacote(raiz, pacote, '0.3.0')
        antes = retrato(raiz)
        vivo = iter([True, True, False, False])
        codigo = troca.aplicar(raiz, area_, 1, lambda pid: next(vivo), espera=3)
        time.sleep(1)
        inicios = (raiz / 'data/started.txt').read_text().splitlines()
        (raiz / 'data/started.txt').unlink()
        if certo:
            passo(f'{nome}: new version stays', codigo == 0 and 'program' not in (raiz / troca.PROGRAMA).read_text()
                  and '0.3.0' in (raiz / troca.PROGRAMA).read_text() and inicios == [f'0.3.0 --updated {area_}'], inicios)
        else:
            passo(f'{nome}: old version returns', codigo == 1 and retrato(raiz) == antes, f'code {codigo}')
            passo(f'{nome}: old version is told why', inicios == [f'0.3.0 --updated {area_}', f'0.2.1 --update-failed {area_}']
                  and (area_ / 'error.txt').read_text().startswith('The new version'), inicios)


def esperar(condicao, segundos):
    fim = time.time() + segundos
    while time.time() < fim:
        if condicao():
            return True
        time.sleep(1)
    return False


def encerrar(raiz):
    """Stops every program started from the test copy."""
    if troca.JANELAS:
        filtro = f"Get-Process | Where-Object {{ $_.Path -like '{raiz.parent}*' }} | Stop-Process -Force"
        subprocess.run(['powershell', '-NoProfile', '-Command', filtro], check=False)
    else:
        for p in Path('/proc').glob('[0-9]*'):
            try:
                if str(raiz.parent) in (p / 'cmdline').read_text():
                    os.kill(int(p.name), 9)
            except (OSError, ValueError):
                pass
    time.sleep(2)


def pacote_real(pacote):
    """Updates a copy of the real package with the real program, then makes an update fail."""
    base = TEMP / 'real'
    raiz = base / pacote.name
    print('copying the package', flush=True)
    shutil.copytree(pacote, raiz, symlinks=True)
    atual = json.loads((raiz / 'brand.json').read_text(encoding='utf8'))
    casa = base / 'home'
    casa.mkdir()
    amb = {**os.environ, 'HOME': str(casa), 'USERPROFILE': str(casa)}
    amb.pop('SUITE_ROOT')
    subprocess.run([str(raiz / troca.PROGRAMA), '--prepare'], env=amb, check=True, timeout=120)
    ajustes = raiz / 'data/java/user/User/settings.json'
    dados = json.loads(ajustes.read_text(encoding='utf8'))
    dados.update({'editor.fontSize': 21, 'files.autoSave': 'onFocusChange'})
    dados['workbench.colorCustomizations']['sideBar.background'] = '#191A1C'
    ajustes.write_text(json.dumps(dados), encoding='utf8')
    (raiz / 'data/java/defaults.json').unlink()  # as left by a version that kept no defaults
    opcoes = json.loads((raiz / 'data/hub.json').read_text(encoding='utf8')) if (raiz / 'data/hub.json').exists() else {}
    opcoes.update({'setup': True, 'checked': 9e12, 'transitions': False})
    (raiz / 'data/hub.json').write_text(json.dumps(opcoes), encoding='utf8')
    escrever(raiz / 'data/java/extensions/me.mine-2.0.0/package.json', '{"name": "mine", "publisher": "me", "version": "2.0.0"}')
    empacotadas = troca.empacotadas(raiz, 'java')
    passo('package lists what it shipped', bool(empacotadas) and 'me.mine-2.0.0' not in empacotadas, str(empacotadas)[:80])

    seguinte = base / 'next' / pacote.name
    print('building the next version', flush=True)
    shutil.copytree(pacote, seguinte, symlinks=True)
    (seguinte / 'brand.json').write_text(json.dumps({**atual, 'version': '9.9.9'}), encoding='utf8')
    arquivo = base / hub.pacote_atual()
    empacotar(seguinte, arquivo, pacote.name)
    area_ = troca.area(raiz)
    try:
        subprocess.run([str(raiz / troca.PROGRAMA), '--install-update', str(arquivo)], env=amb, check=True, timeout=600)
        chegou = esperar(lambda: json.loads((raiz / 'brand.json').read_text(encoding='utf8'))['version'] == '9.9.9'
                         and not area_.exists(), 240)
        registro = (area_ / 'log.txt').read_text(encoding='utf8') if (area_ / 'log.txt').exists() else ''
        passo('real package updates itself and clears its work folder', chegou, registro or sorted(p.name for p in raiz.iterdir()))
        dados = json.loads(ajustes.read_text(encoding='utf8'))
        passo('real: changed setting kept', dados.get('editor.fontSize') == 21)
        passo('real: old autosave migrated', dados.get('files.autoSave') == 'afterDelay', dados.get('files.autoSave'))
        passo('real: old top-level color moved', 'sideBar.background' not in dados['workbench.colorCustomizations'])
        passo('real: own extension carried', (raiz / 'data/java/extensions/me.mine-2.0.0/package.json').exists())
        passo('real: packaged extensions present', len(list((raiz / 'data/java/extensions').glob('redhat.java-*'))) == 1)
        passo('real: editor in place', hub.JANELAS or os.access(next((raiz / 'editor').glob('codium'), raiz), os.X_OK))
        encerrar(raiz)

        # Second round: the next version cannot start, so 9.9.9 has to come back whole.
        ruim = base / 'broken' / pacote.name
        shutil.copytree(seguinte, ruim, symlinks=True)
        (ruim / 'brand.json').write_text(json.dumps({**atual, 'version': '10.0.0'}), encoding='utf8')
        shutil.rmtree(ruim / '_hub')
        (ruim / '_hub').mkdir()
        empacotar(ruim, arquivo, pacote.name)
        antes = ajustes.read_text(encoding='utf8')
        subprocess.run([str(raiz / troca.PROGRAMA), '--install-update', str(arquivo)], env=amb, check=True, timeout=600)
        voltou = esperar(lambda: (area_ / 'error.txt').exists() or not area_.exists(), 240) and esperar(
            lambda: json.loads((raiz / 'brand.json').read_text(encoding='utf8'))['version'] == '9.9.9' and (raiz / '_hub').is_dir()
            and any((raiz / '_hub').iterdir()), 30)
        passo('real: a version that cannot start is rolled back', voltou, sorted(p.name for p in raiz.iterdir()))
        passo('real: settings as before the failed update', ajustes.read_text(encoding='utf8') == antes)
        passo('real: own extension still there', (raiz / 'data/java/extensions/me.mine-2.0.0/package.json').exists())
    finally:
        encerrar(raiz)


if __name__ == '__main__':
    try:
        troca_simples()
        falha_no_meio()
        pacotes_ruins()
        migracao()
        certificados()
        ajudante()
        if len(sys.argv) > 1:
            pacote_real(Path(sys.argv[1]).resolve())
    finally:
        shutil.rmtree(TEMP, ignore_errors=True)
    print(f'{len(falhas)} failures')
    sys.exit(1 if falhas else 0)
