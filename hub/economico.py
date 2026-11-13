"""Economy mode: lower the editors' memory use with one switch.

The values live in each profile's `profiles/<app>/economico.json`, so the Java and Web areas own them:

    {"settings": {"key": value, ...}, "memory": "768M"}

Both parts are optional, and a missing file changes nothing. The Hub applies the settings on every
open while the mode is on, remembers what each key held before, and puts it back when the mode goes
off (unless the person changed that key in the meantime).
"""
import ctypes
import json
import sys
from pathlib import Path

LIMITE_GIB = 7.0  # a "8 GB" machine reports about 7.7 GiB, so it does not count as low on RAM
AUSENTE = {'__ausente__': True}  # marks a key that did not exist before the mode


def ram_total_gib():
    """Installed RAM in GiB, or None when the system does not say."""
    try:
        if sys.platform == 'win32':
            class Memoria(ctypes.Structure):
                _fields_ = [('tamanho', ctypes.c_ulong), ('uso', ctypes.c_ulong), ('total', ctypes.c_ulonglong),
                            ('livre', ctypes.c_ulonglong), ('pag_total', ctypes.c_ulonglong),
                            ('pag_livre', ctypes.c_ulonglong), ('virt_total', ctypes.c_ulonglong),
                            ('virt_livre', ctypes.c_ulonglong), ('ext', ctypes.c_ulonglong)]
            m = Memoria()
            m.tamanho = ctypes.sizeof(m)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return None
            return m.total / 1024 ** 3
        for linha in Path('/proc/meminfo').read_text(encoding='utf8').splitlines():
            if linha.startswith('MemTotal:'):
                return int(linha.split()[1]) / 1024 ** 2
    except (OSError, ValueError, AttributeError):
        pass
    return None


def pouca_ram(total=None):
    """True when the machine has less than 8 GB; False when unknown."""
    total = ram_total_gib() if total is None else total
    return total is not None and total < LIMITE_GIB


def ler_gancho(pasta_perfil):
    """The profile's economy values: {'settings': dict, 'memory': str or ''}."""
    try:
        dados = json.loads((Path(pasta_perfil) / 'economico.json').read_text(encoding='utf8'))
    except (OSError, ValueError):
        dados = {}
    if not isinstance(dados, dict):
        dados = {}
    ajustes = dados.get('settings')
    memoria = dados.get('memory')
    return {'settings': ajustes if isinstance(ajustes, dict) else {},
            'memory': memoria if isinstance(memoria, str) else ''}


def aplicar(atual, ajustes, antes):
    """Put the economy settings into `atual`, noting in `antes` what each key held."""
    for chave, valor in ajustes.items():
        if chave not in antes:
            antes[chave] = atual.get(chave, AUSENTE)
        atual[chave] = valor


def reverter(atual, ajustes, antes):
    """Undo `aplicar`; a key the person changed since is left as they set it."""
    for chave, anterior in antes.items():
        if atual.get(chave, AUSENTE) == ajustes.get(chave, AUSENTE) or chave not in ajustes:
            if anterior == AUSENTE:
                atual.pop(chave, None)
            else:
                atual[chave] = anterior
    antes.clear()
