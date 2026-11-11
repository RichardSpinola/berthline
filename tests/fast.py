"""Fast checks that need no package: JSON, syntax, lint and unit tests. Runs in CI on every push.

Usage: python tests/fast.py   (needs node on PATH; ruff is used when installed)
"""
import json
import py_compile
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PULAR = {'node_modules', '.git', 'dist', 'cache', 'work', 'out', '.venv'}
falhas = []


def arquivos(padrao):
    return [f for f in sorted(RAIZ.rglob(padrao)) if not PULAR & set(f.relative_to(RAIZ).parts)]


def etapa(nome, ok, detalhe=''):
    print('OK  ' if ok else 'FAIL', nome, detalhe if not ok else '', flush=True)
    if not ok:
        falhas.append(nome)


def json_valido():
    # Settings and keybindings allow // comment lines, as the Hub reads them
    for f in arquivos('*.json'):
        try:
            json.loads(re.sub(r'^\s*//.*$', '', f.read_text(encoding='utf8'), flags=re.M))
        except ValueError as e:
            etapa(f'json {f.relative_to(RAIZ)}', False, str(e))
    etapa('json files parse', not [n for n in falhas if n.startswith('json ')])


def python():
    ruins = []
    for f in arquivos('*.py'):
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            ruins.append(f'{f.relative_to(RAIZ)}: {e.msg}')
    etapa('python compiles', not ruins, ' / '.join(ruins))
    if shutil.which('ruff'):
        # Real errors only (undefined names, syntax); unused imports are left to review
        r = subprocess.run(['ruff', 'check', '--select', 'F', '--ignore', 'F401', '--output-format', 'concise', 'hub', 'build', 'tests'],
                           cwd=RAIZ, capture_output=True, text=True)
        etapa('ruff', r.returncode == 0, r.stdout[-800:])


def node():
    ruins = []
    for f in arquivos('*.js'):
        r = subprocess.run(['node', '--check', str(f)], capture_output=True, text=True)
        if r.returncode:
            ruins.append(f'{f.relative_to(RAIZ)}: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "error"}')
    etapa('javascript parses', not ruins, ' / '.join(ruins))
    r = subprocess.run(['node', 'tests/web_preview_test.js'], cwd=RAIZ, capture_output=True, text=True, timeout=120)
    etapa('web preview unit tests', r.returncode == 0, (r.stdout + r.stderr)[-800:])


def perfis():
    # Every app.json names the extensions its profile must ship
    for app in arquivos('app.json'):
        lista = app.parent / 'extensions.txt'
        dados = json.loads(app.read_text(encoding='utf8'))
        etapa(f'profile {app.parent.name} has a title', bool(dados.get('title')))
        if lista.exists():
            itens = [l.strip() for l in lista.read_text().splitlines() if l.strip()]
            etapa(f'profile {app.parent.name} pins extension versions', all('@' in i for i in itens),
                  ', '.join(i for i in itens if '@' not in i))


if __name__ == '__main__':
    for passo in (json_valido, python, node, perfis):
        passo()
    print(f'{len(falhas)} failed' if falhas else 'all passed')
    sys.exit(1 if falhas else 0)
