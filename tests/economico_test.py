"""Economy mode without a window: hook file, apply, undo, RAM threshold. Needs no built package."""
import json
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(tempfile.mkdtemp(prefix='eco-'))
os.environ['SUITE_ROOT'] = str(RAIZ)
os.environ['HOME'] = str(RAIZ / 'home')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).parent.parent / 'hub'))
import economico  # noqa: E402
import hub  # noqa: E402

falhas = []


def passo(nome, ok, extra=''):
    print('OK  ' if ok else 'FAIL', nome, extra)
    if not ok:
        falhas.append(nome)


passo('8 GB machine is not low on RAM', not economico.pouca_ram(7.7))
passo('4 GB machine is low on RAM', economico.pouca_ram(4.0))
passo('unknown RAM is not low', not economico.pouca_ram(None) or economico.ram_total_gib() is not None)

(RAIZ / 'profiles/java').mkdir(parents=True)
(RAIZ / 'data/java').mkdir(parents=True)
passo('no hook file changes nothing', economico.ler_gancho(RAIZ / 'profiles/java') == {'settings': {}, 'memory': ''})
atual = {'a': 1}
hub.gravar_geral('economy', True)
passo('mode on without hook leaves settings alone', hub.modo_economico('java', atual) == '1G' and atual == {'a': 1})

(RAIZ / 'profiles/java/economico.json').write_text(json.dumps({'settings': {'a': 2, 'b': 3}, 'memory': '768M'}))
atual = {'a': 1, 'c': 9}
passo('mode on applies hook memory', hub.modo_economico('java', atual) == '768M')
passo('mode on applies hook settings', atual == {'a': 2, 'b': 3, 'c': 9}, atual)
passo('second run keeps the first values', hub.modo_economico('java', atual) == '768M'
      and json.loads((RAIZ / 'data/java/economico.json').read_text())['a'] == 1)

hub.gravar_geral('economy', False)
passo('mode off restores memory', hub.modo_economico('java', atual) == '1G')
passo('mode off restores settings', atual == {'a': 1, 'c': 9}, atual)
passo('record is removed', not (RAIZ / 'data/java/economico.json').exists())

hub.gravar_geral('economy', True)
hub.modo_economico('java', atual)
atual['a'] = 7  # the person changed it meanwhile
hub.gravar_geral('economy', False)
hub.modo_economico('java', atual)
passo('a key the person changed is kept', atual == {'a': 7, 'c': 9}, atual)

print('FAILURES:' if falhas else 'ALL OK', falhas)
sys.exit(1 if falhas else 0)
