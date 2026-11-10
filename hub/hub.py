"""Hub of the suite: opens each profile and keeps its settings."""
import ctypes
import hashlib
import json
import math
import ntpath
import os
import posixpath
import re
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

import troca

try:
    import certifi
except ImportError:  # run from source without it: the system's certificates still apply
    certifi = None

JANELAS = sys.platform == 'win32'
RAIZ = Path(os.environ.get('SUITE_ROOT') or (sys.executable if getattr(sys, 'frozen', False) else __file__)).resolve()
RAIZ = RAIZ if RAIZ.is_dir() else RAIZ.parent
DADOS = RAIZ / 'data'
PERFIS = RAIZ / 'profiles'
OPCOES = DADOS / 'hub.json'
ASSETS = RAIZ / 'assets'
CASA = Path.home()
PROJETOS = CASA / 'Projects'
CLONES = CASA / 'Cloned'
TEMPORARIO = tempfile.gettempdir()
MEMORIAS = ['768M', '1G', '2G', '3G']
PADRAO = {'ai': False, 'visual': True, 'animations': True, 'memory': '1G', 'keymap': 'intellij', 'folder': ''}
# Defaults of older versions that a later one replaced; a setting still equal to one was never touched.
LEGADO = {'files.autoSave': 'onFocusChange'}
COM_TEMAS = ('workbench.colorCustomizations', 'editor.semanticTokenColorCustomizations')
ICON_THEMES = {'Berthline': 'berthline-file-icons', 'JetBrains': 'jetbrains-file-icon-theme-auto'}
THEMES = {'Dark': ('Islands Dark', 'Default Dark Modern'), 'Light': ('Islands Light', 'Default Light Modern')}
# keybindings.json files written by 0.2.1 that nobody edited; they move to the new profile's keys
TECLAS_ANTIGAS = {'web': {'1e7c9eca21f71844c91092c8e84bfc83bf2279bace9ead88001a6f45780d0cd9'}}
INTELLIJ_KEYS = (
    ('Search Everywhere', 'Shift Shift'), ('Run', 'Shift+F10'), ('Debug', 'Shift+F9'), ('Rerun', 'Ctrl+5'),
    ('Stop', 'Ctrl+2'), ('Build', 'Ctrl+9'), ('Toggle Breakpoint', 'Ctrl+8'), ('Step Over', 'F8'),
    ('Step Into', 'F7'), ('Resume', 'F9'), ('Context Actions', 'Alt+Enter'), ('Generate', 'Alt+Insert'),
    ('Rename', 'Shift+F6'), ('File Structure', 'Ctrl+0'), ('Recent Files', 'Ctrl+E'), ('Terminal', 'Alt+F12'),
)
VSCODE_KEYS = (
    ('Command Palette', 'Ctrl+Shift+P'), ('Quick Open', 'Ctrl+P'), ('Run Without Debugging', 'Ctrl+F5'), ('Debug', 'F5'),
    ('Stop', 'Shift+F5'), ('Build', 'Ctrl+Shift+B'), ('Toggle Breakpoint', 'F9'), ('Step Over', 'F10'), ('Step Into', 'F11'),
    ('Quick Fix', 'Ctrl+.'), ('Rename', 'F2'), ('Go to Symbol', 'Ctrl+Shift+O'), ('Copy Line Up', 'Shift+Alt+Up'),
    ('Copy Line Down', 'Shift+Alt+Down'), ('Terminal', 'Ctrl+`'),
)
JAVA_ONLY_KEYS = ('Build', 'Generate')
ALERTA = '#E0524F'  # errors: the flag's red, lifted to read on the dark background
LAMPADAS = {'run': '#3FA66B', 'ready': '#5A5F66', 'prep': '#E0A030', 'att': '#C8102E'}


def marca():
    try:
        return json.loads((RAIZ / 'brand.json').read_text(encoding='utf8'))
    except (OSError, ValueError):
        return {'name': 'Berthline', 'hub': 'Berthline Hub', 'tagline': '', 'folder': '.berthline'}


def aplicativos():
    saida = {}
    for f in PERFIS.glob('*/app.json'):
        saida[f.parent.name] = json.loads(f.read_text(encoding='utf8'))
    return dict(sorted(saida.items(), key=lambda x: x[1].get('order', 99)))


def versao():
    return marca().get('version', '')


def versao_editor():
    try:
        return json.loads((RAIZ / 'editor/resources/app/product.json').read_text(encoding='utf8'))['version']
    except (OSError, KeyError, ValueError):
        return ''


def opcoes():
    try:
        return json.loads(OPCOES.read_text(encoding='utf8'))
    except (OSError, ValueError):
        return {}


def opcao(app, chave):
    return opcoes().get(app, {}).get(chave, PADRAO[chave])


def gravar_opcao(app, chave, valor):
    tudo = opcoes()
    tudo.setdefault(app, {})[chave] = valor
    OPCOES.parent.mkdir(parents=True, exist_ok=True)
    OPCOES.write_text(json.dumps(tudo, indent=2), encoding='utf8')


def pastas_confiaveis():
    return [Path(p) for p in opcoes().get('trusted', [str(PROJETOS)])]


def confiavel(pasta):
    alvo = Path(pasta).resolve()
    return any(alvo == p or p in alvo.parents for p in pastas_confiaveis())


def gravar_confiaveis(pastas):
    tudo = opcoes()
    tudo['trusted'] = sorted({str(p) for p in pastas})
    OPCOES.parent.mkdir(parents=True, exist_ok=True)
    OPCOES.write_text(json.dumps(tudo, indent=2), encoding='utf8')


def caminho_real(caminho):
    """Devolve o caminho como o editor o vê, sem nomes curtos do Windows."""
    if not JANELAS:
        return Path(caminho).resolve()
    # Path.resolve trocaria uma unidade mapeada por um caminho de rede, que o editor recusa.
    absoluto = os.path.abspath(caminho)
    saida = ctypes.create_unicode_buffer(32768)
    tamanho = ctypes.windll.kernel32.GetLongPathNameW(absoluto, saida, len(saida))
    return Path(saida.value if 0 < tamanho < len(saida) else absoluto)


def confiar(pasta):
    gravar_confiaveis(pastas_confiaveis() + [caminho_real(pasta)])


def caminho_uri(pasta):
    texto = Path(pasta).as_posix()
    return texto if texto.startswith('/') else f'/{texto}'


def estado_confianca(atualizar):
    """Altera a lista de pastas confiáveis guardada pelo próprio editor, comum a todos os apps."""
    banco = CASA / f"{marca()['folder']}-shared/sharedStorage/state.vscdb"
    banco.parent.mkdir(parents=True, exist_ok=True)
    chave = 'content.trust.model.key'
    with sqlite3.connect(banco, timeout=2) as con:
        con.execute('CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)')
        linha = con.execute('SELECT value FROM ItemTable WHERE key = ?', (chave,)).fetchone()
        dados = json.loads(linha[0]) if linha else {'uriTrustInfo': []}
        dados['uriTrustInfo'] = atualizar(dados.get('uriTrustInfo', []))
        con.execute('INSERT INTO ItemTable (key, value) VALUES (?, ?)', (chave, json.dumps(dados)))


def sem_novidades(app):
    """Evita a aba de novidades que o Bookmarks abre no primeiro uso."""
    achados = list((DADOS / app / 'extensions').glob('alefragnani.bookmarks-*'))
    if not achados:
        return
    versao = json.loads((achados[0] / 'package.json').read_text(encoding='utf8'))['version']
    banco = pasta_usuario(app) / 'globalStorage/state.vscdb'
    banco.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(banco, timeout=2) as con:
        con.execute('CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)')
        con.execute('INSERT OR IGNORE INTO ItemTable (key, value) VALUES (?, ?)', (
            'alefragnani.Bookmarks', json.dumps({'Bookmarks.version': versao, 'Bookmarks.whatsNew.shown': versao})))


def aplicar_confianca():
    novos = {caminho_uri(p) for p in pastas_confiaveis()}

    def atualizar(itens):
        conhecidos = {i['uri'].get('path') for i in itens}
        return itens + [{'uri': {'$mid': 1, 'path': p, 'scheme': 'file'}, 'trusted': True} for p in novos - conhecidos]
    estado_confianca(atualizar)


def retirar_confianca(pasta):
    gravar_confiaveis([p for p in pastas_confiaveis() if p != Path(pasta)])
    alvo = caminho_uri(pasta)
    estado_confianca(lambda itens: [i for i in itens if i['uri'].get('path') != alvo])


def ler_json(arquivo):
    try:
        return json.loads(re.sub(r'^\s*//.*$', '', Path(arquivo).read_text(encoding='utf8'), flags=re.M))
    except (OSError, ValueError):
        return {}


def caminhos(valor):
    if isinstance(valor, str):
        return valor.replace('${SUITE}', RAIZ.as_posix())
    if isinstance(valor, dict):
        return {k: caminhos(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [caminhos(v) for v in valor]
    return valor


def modelo(app):
    info = aplicativos()[app]
    ajustes = ler_json(PERFIS / 'base/settings.json') if info.get('base') else {}
    ajustes.update(ler_json(PERFIS / app / 'settings.json'))
    return ajustes


def pasta_usuario(app):
    return DADOS / app / 'user' / 'User'


def pasta_projetos(app):
    return Path(opcao(app, 'folder') or PROJETOS)


def arquivos_teclas(app):
    """The profile's shortcut files, base first."""
    origens = [PERFIS / 'base'] if aplicativos()[app].get('base') else []
    origens.append(PERFIS / app)
    return [o / 'keybindings.json' for o in origens if (o / 'keybindings.json').exists()]


def tema_de(app, claro_ou_escuro):
    """The app's own theme for Dark or Light: Islands where the profile ships it, the editor's otherwise."""
    islands = str(modelo(app).get('workbench.colorTheme', '')).startswith('Islands')
    return THEMES[claro_ou_escuro][0 if islands else 1]


def keymap_de(app):
    """Only profiles that offer the choice can use IntelliJ keys; the rest keep the editor's own."""
    return opcao(app, 'keymap') if aplicativos()[app].get('keymap') else 'vscode'


def teclas_app(app):
    """Shortcuts the Learn screen lists; each one exists in that app."""
    lista = INTELLIJ_KEYS if keymap_de(app) == 'intellij' else VSCODE_KEYS
    return [t for t in lista if aplicativos()[app].get('memory') or t[0] not in JAVA_ONLY_KEYS]


def aplicar_keymap(app, nome):
    """Switches keymap keeping the shortcuts the person added. False if their file can't be read."""
    arquivo = pasta_usuario(app) / 'keybindings.json'
    atual = ler_json(arquivo) if arquivo.exists() else []
    if not isinstance(atual, list):
        return False
    teclas = arquivos_teclas(app)
    perfil = [e for t in teclas for e in ler_json(t)]
    vscode = ler_json(PERFIS / app / 'keymap-vscode.json')
    proprias = [e for e in atual if e not in perfil and e not in vscode]
    gravar_opcao(app, 'keymap', nome)
    if not arquivo.exists() and nome == 'intellij':
        return True
    if nome == 'intellij':
        texto = juntar_teclas(teclas)
        if proprias:
            extra = ',\n'.join(json.dumps(e, ensure_ascii=False) for e in proprias)
            texto = f"{texto[:texto.rindex(']')].rstrip()},\n{extra}\n]\n"
    else:
        texto = json.dumps(vscode + proprias, indent=4, ensure_ascii=False) + '\n'
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(texto, encoding='utf8')
    return True


def juntar_teclas(arquivos):
    """Une listas de atalhos sem perder os comentários."""
    textos = [a.read_text(encoding='utf8') for a in arquivos]
    return '[\n' + ',\n'.join(t[t.index('[') + 1:t.rindex(']')].strip('\n') for t in textos) + '\n]\n'


def migrar(atual, base, anterior):
    """Brings a newer profile's defaults to settings the person never changed.

    `anterior` holds the defaults written last time; before 0.2.1 none were kept, so LEGADO stands in.
    Colors that an old version wrote for every theme move under the theme they were made for.
    """
    for chave, valor in base.items():
        if chave not in atual:
            continue
        if chave in COM_TEMAS and isinstance(valor, dict) and isinstance(atual[chave], dict):
            meu = atual[chave]
            for nome, bloco in valor.items():
                if not (nome.startswith('[') and isinstance(bloco, dict)):
                    continue
                for k, v in bloco.items():
                    if k in meu and meu[k] == v:
                        del meu[k]
                meu.setdefault(nome, bloco)
            continue
        velho = anterior[chave] if chave in anterior else LEGADO.get(chave, valor)
        if velho != valor and atual[chave] == velho:
            atual[chave] = valor


def preparar(app):
    """Grava o perfil a cada abertura, mantendo o que a pessoa mudou."""
    usuario = pasta_usuario(app)
    usuario.mkdir(parents=True, exist_ok=True)
    aplicar_confianca()
    sem_novidades(app)
    ferramentas(app).mkdir(parents=True, exist_ok=True)
    marca_dagua(app)
    arquivo = usuario / 'settings.json'
    atual = ler_json(arquivo) if arquivo.exists() else {}
    base = modelo(app)
    padroes = DADOS / app / 'defaults.json'
    migrar(atual, caminhos(base), ler_json(padroes))
    padroes.write_text(json.dumps(caminhos(base), ensure_ascii=False), encoding='utf8')
    for chave, valor in base.items():
        if chave not in atual or '${SUITE}' in json.dumps(valor):
            atual[chave] = caminhos(valor)
    atual['telemetry.telemetryLevel'] = 'off'
    atual['chat.disableAIFeatures'] = not opcao(app, 'ai')
    atual['update.mode'] = 'none'
    info = aplicativos()[app]
    if info.get('accent'):
        cor = info['accent']
        atual['workbench.colorCustomizations'] = {
            **atual.get('workbench.colorCustomizations', {}), 'focusBorder': cor, 'progressBar.background': cor,
            'button.background': cor, 'badge.background': cor, 'activityBarBadge.background': cor,
            'panelTitle.activeBorder': cor, 'tab.activeBorderTop': cor, 'statusBarItem.remoteBackground': cor,
        }
    movimento = opcao(app, 'animations')
    atual['workbench.reduceMotion'] = 'auto' if movimento else 'on'
    atual['editor.smoothScrolling'] = movimento
    atual['workbench.list.smoothScrolling'] = movimento
    atual['editor.cursorSmoothCaretAnimation'] = 'explicit' if movimento else 'off'
    if aplicativos()[app].get('base') and ripgrep():
        atual['todo-tree.ripgrep.ripgrep'] = str(ripgrep())
    args = atual.get('java.jdt.ls.vmargs')
    if args:
        atual['java.jdt.ls.vmargs'] = re.sub(r'-Xmx\S+', f"-Xmx{opcao(app, 'memory')}", args)
    arquivo.write_text(json.dumps(atual, indent=4, ensure_ascii=False), encoding='utf8')
    origens = [PERFIS / 'base'] if aplicativos()[app].get('base') else []
    origens.append(PERFIS / app)
    teclas = arquivos_teclas(app)
    proprio = usuario / 'keybindings.json'
    if proprio.exists() and hashlib.sha256(proprio.read_bytes()).hexdigest() in TECLAS_ANTIGAS.get(app, ()):
        proprio.unlink()
    if teclas and not proprio.exists():
        if keymap_de(app) == 'intellij' or not aplicativos()[app].get('keymap'):
            (usuario / 'keybindings.json').write_text(juntar_teclas(teclas), encoding='utf8')
        else:
            aplicar_keymap(app, 'vscode')
    for origem in origens:
        trechos = origem / 'snippets'
        if trechos.is_dir():
            shutil.copytree(trechos, usuario / 'snippets', dirs_exist_ok=True)


def editor():
    nomes = ('VSCodium.exe', 'Code.exe') if JANELAS else ('codium', 'code')
    return next((RAIZ / 'editor' / n for n in nomes if (RAIZ / 'editor' / n).exists()), RAIZ / 'editor' / nomes[-1])


def ripgrep():
    pacotes = RAIZ / 'editor/resources/app/node_modules.asar.unpacked/@vscode'
    return next(iter(pacotes.glob('ripgrep*/bin/**/rg.exe' if JANELAS else 'ripgrep*/bin/**/rg')), None)


def node():
    return RAIZ / 'node' / ('node.exe' if JANELAS else 'bin/node')


def comando(app, alvos=(), porta=None):
    visual = opcao(app, 'visual') and aplicativos()[app].get('base')
    args = [str(editor()), f"--user-data-dir={DADOS / app / 'user'}", f"--extensions-dir={DADOS / app / 'extensions'}"]
    args += [f'--disable-extension={e}' for e in desligadas(app)]
    if not JANELAS:
        args.append('--ozone-platform=x11')
    if porta or visual:
        args.append(f'--remote-debugging-port={porta or 0}')
    return args + [str(a) for a in alvos]


def ambiente(app):
    amb = {**os.environ, 'SUITE_TOOLS': str(ferramentas(app)), 'SUITE_VISUAL': '1' if opcao(app, 'visual') else '0',
           'SUITE_ANIMATIONS': '1' if opcao(app, 'animations') else '0', 'SUITE_WATERMARK': str(DADOS / app / 'watermark.svg')}
    if node().exists():
        amb['SUITE_NODE'] = str(node())
    amb['SUITE_HUB'] = sys.executable
    amb['SUITE_APP'] = app
    # Run from source, the interpreter alone is not the Hub; a packaged Hub needs nothing else.
    amb['SUITE_HUB_ARGS'] = json.dumps([] if getattr(sys, 'frozen', False) else [str(Path(__file__).resolve())])
    if not getattr(sys, 'frozen', False):
        amb['SUITE_HUB_ROOT'] = str(RAIZ)
    for chave in list(amb):
        if chave == 'ELECTRON_RUN_AS_NODE' or chave.startswith('VSCODE_'):
            del amb[chave]
    amb.pop('SUITE_ROOT', None)
    return amb


def ligar_icone():
    """Liga a janela do editor ao ícone da marca na barra de tarefas do Linux."""
    if JANELAS:
        return
    b = marca()
    classe = b['name'].lower()
    texto = (f"[Desktop Entry]\nType=Application\nName={b['name']}\nExec={editor()}\n"
             f"Icon={imagem_icone('hub', 'png')}\nStartupWMClass={classe}\nNoDisplay=true\n")
    arquivo = CASA / f'.local/share/applications/{classe}-editor.desktop'
    if not arquivo.exists() or arquivo.read_text(encoding='utf8') != texto:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(texto, encoding='utf8')


def abrir_app(app, alvos=(), porta=None, comando_=None):
    alvos = [caminho_real(a) for a in alvos]
    preparar(app)
    ligar_icone()
    if comando_:
        (ferramentas(app) / 'ao-abrir').write_text(comando_, encoding='utf8')
    if alvos:
        registrar(app, alvos[0])
    extra = {'creationflags': subprocess.DETACHED_PROCESS} if JANELAS else {'start_new_session': True}
    return subprocess.Popen(comando(app, alvos, porta), env=ambiente(app), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)


def registrar(app, alvo):
    tudo = opcoes()
    lista = [p for p in tudo.setdefault('recent', []) if chave_caminho(p['path']) != chave_caminho(alvo)]
    tudo['recent'] = [{'path': str(alvo), 'app': app, 'at': time.time()}] + lista[:29]
    OPCOES.parent.mkdir(parents=True, exist_ok=True)
    OPCOES.write_text(json.dumps(tudo, indent=2), encoding='utf8')


def chave_caminho(caminho, janelas=JANELAS):
    """Identifica uma pasta: no Windows, a mesma pasta aparece com barras e letras diferentes."""
    texto = str(caminho)
    if not janelas:
        return posixpath.normpath(texto)
    return ntpath.normcase(ntpath.normpath(texto.lstrip('/') if ntpath.splitdrive(texto.lstrip('/'))[0] else texto))


def recentes(so_app=None):
    vistos = {}
    for p in opcoes().get('recent', []):
        vistos.setdefault(chave_caminho(p['path']), (p['path'], p['app'], float('inf')))
    for app in aplicativos():
        for w in (pasta_usuario(app) / 'workspaceStorage').glob('*/workspace.json'):
            try:
                u = urlparse(json.loads(w.read_text(encoding='utf8'))['folder'])
                if u.scheme == 'file':
                    caminho = unquote(u.path).lstrip('/') if JANELAS else unquote(u.path)
                    vistos.setdefault(chave_caminho(caminho), (caminho, app, w.stat().st_mtime))
            except (OSError, KeyError, ValueError):
                pass
    fora = {chave_caminho(p) for p in opcoes().get('hidden', [])}
    bons = [(Path(p), a, t) for c, (p, a, t) in vistos.items() if c not in fora and Path(p).is_dir()
            and (so_app is None or a == so_app) and not (TEMPORARIO and p.startswith(TEMPORARIO))]
    return [(p, a) for p, a, _ in sorted(bons, key=lambda x: -x[2])]


def quando(caminho):
    """How long ago a project was opened, in words; empty when unknown."""
    chave = chave_caminho(caminho)
    instante = next((p.get('at') for p in opcoes().get('recent', []) if chave_caminho(p['path']) == chave), None)
    if not instante:
        return ''
    passou = time.time() - instante
    if passou < 60:
        return 'Just now'
    if passou < 3600:
        return f'{int(passou // 60)} min ago'
    if passou < 86400:
        return f'{int(passou // 3600)} h ago'
    if passou < 172800:
        return 'Yesterday'
    if passou < 604800:
        return f'{int(passou // 86400)} days ago'
    return time.strftime('%b %d', time.localtime(instante))


def tipo_rotulo(pasta):
    """Short build or language tag for a project row."""
    try:
        nomes = {p.name for p in Path(pasta).iterdir()}
    except OSError:
        return ''
    if 'pom.xml' in nomes:
        return 'Maven'
    if nomes & {'build.gradle', 'build.gradle.kts'}:
        return 'Gradle'
    if 'tsconfig.json' in nomes:
        return 'TypeScript'
    if 'package.json' in nomes:
        return 'Node'
    if any(n.endswith('.html') for n in nomes):
        return 'HTML'
    return 'Java' if (Path(pasta) / 'src').is_dir() and tipo_projeto(Path(pasta)) == 'java' else ''


def ocultar_recente(caminho):
    tudo = opcoes()
    tudo['hidden'] = sorted(set(tudo.get('hidden', [])) | {str(caminho)})
    tudo['recent'] = [p for p in tudo.get('recent', []) if chave_caminho(p['path']) != chave_caminho(caminho)]
    OPCOES.write_text(json.dumps(tudo, indent=2), encoding='utf8')


def curto(caminho):
    texto = str(caminho)
    return '~' + texto[len(str(CASA)):] if texto.startswith(str(CASA)) else texto


def nome_do_repo(url):
    return re.sub(r'\.git$', '', url.rstrip('/').rsplit('/', 1)[-1].rsplit(':', 1)[-1])


def ferramentas(app):
    return DADOS / app / 'tools'


def gravar_geral(chave, valor):
    tudo = opcoes()
    tudo[chave] = valor
    OPCOES.parent.mkdir(parents=True, exist_ok=True)
    OPCOES.write_text(json.dumps(tudo, indent=2), encoding='utf8')


def etapa_atual(app):
    try:
        return (ferramentas(app) / 'etapa').read_text(encoding='utf8').strip()
    except OSError:
        return ''


def processo_vivo(pid):
    if JANELAS:
        kernel = ctypes.windll.kernel32
        alca = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not alca:
            return False
        codigo = ctypes.c_ulong()
        vivo = kernel.GetExitCodeProcess(alca, ctypes.byref(codigo)) and codigo.value == 259  # STILL_ACTIVE
        kernel.CloseHandle(alca)
        return bool(vivo)
    return Path(f'/proc/{pid}').exists()


def rodando(app):
    """True while the app's editor runs: it keeps its pid in code.lock."""
    try:
        return processo_vivo(int((DADOS / app / 'user/code.lock').read_text(encoding='utf8')))
    except (OSError, ValueError):
        return False


def estado_app(app):
    if not editor().exists():
        return 'att', 'Needs attention', 'Editor files are missing'
    if rodando(app):
        return 'run', 'Running', ''
    if not (pasta_usuario(app) / 'settings.json').exists():
        return 'prep', 'Preparing', 'First launch'
    return 'ready', '', ''  # nothing to report: the Hub stays quiet


def limpar_etapa(app):
    (ferramentas(app) / 'etapa').unlink(missing_ok=True)


def blur_unsupported():
    """Why this system can't blur behind a window; empty when it can."""
    if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        return 'Blur needs a real window.'
    if JANELAS:
        return '' if sys.getwindowsversion().build >= 22621 else 'Blur needs Windows 11 22H2 or newer.'
    if 'KDE' in os.environ.get('XDG_CURRENT_DESKTOP', '') and os.environ.get('DISPLAY'):
        return ''
    return 'Blur needs KDE Plasma.'


def vidro_disponivel():
    return bool(opcoes().get('blur', False)) and not blur_unsupported()


def aplicar_vidro(janela_id):
    """Pede ao sistema o desfoque atrás da janela; se falhar, ela fica só translúcida."""
    try:
        if JANELAS:
            dwm = ctypes.windll.dwmapi
            margens = (ctypes.c_int * 4)(-1, -1, -1, -1)
            dwm.DwmExtendFrameIntoClientArea(ctypes.c_void_p(janela_id), margens)
            for atributo, valor in ((20, 1), (38, 3)):
                dado = ctypes.c_int(valor)
                dwm.DwmSetWindowAttribute(ctypes.c_void_p(janela_id), atributo, ctypes.byref(dado), ctypes.sizeof(dado))
            return
        x = ctypes.cdll.LoadLibrary('libX11.so.6')
        x.XOpenDisplay.restype = ctypes.c_void_p
        tela = x.XOpenDisplay(None)
        x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x.XInternAtom.restype = ctypes.c_ulong
        x.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        x.XFlush.argtypes = x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        atomo = x.XInternAtom(tela, b'_KDE_NET_WM_BLUR_BEHIND_REGION', 0)
        x.XChangeProperty(tela, janela_id, atomo, 6, 32, 0, None, 0)
        x.XFlush(tela)
        x.XCloseDisplay(tela)
    except (OSError, AttributeError):
        pass


def tipo_projeto(pasta):
    """Descobre o app de um projeto olhando os arquivos da raiz e de src."""
    nomes = {p.name for p in pasta.iterdir()} | ({p.name for p in (pasta / 'src').iterdir()} if (pasta / 'src').is_dir() else set())
    if nomes & {'pom.xml', 'build.gradle', 'build.gradle.kts'} or any(n.endswith('.java') for n in nomes):
        return 'java'
    if 'package.json' in nomes or any(n.endswith(('.html', '.js', '.ts', '.css')) for n in nomes):
        return 'web'
    return 'standard'


def secoes(so_app=None):
    """Projetos separados: recentes e os que já existem em disco, ou por app no painel."""
    feitos = recentes(so_app)
    ja = {p for p, _ in feitos}
    fora = set(opcoes().get('hidden', []))
    disco = []
    for pasta in dict.fromkeys(pasta_projetos(a) for a in ([so_app] if so_app else aplicativos())):
        if pasta.is_dir():
            for p in sorted(pasta.iterdir(), key=lambda x: x.name.lower()):
                if p.is_dir() and not p.name.startswith('.') and p not in ja and str(p) not in fora:
                    ja.add(p)
                    app = tipo_projeto(p)
                    if so_app in (None, app):
                        disco.append((p, app))
    if so_app:
        return [(t, l) for t, l in (('Recent', feitos), ('On this computer', disco)) if l]
    return [('', feitos + disco)] if feitos or disco else []


def marca_dagua(app):
    """Grava em cinza o ícone do app para a tela vazia do editor."""
    desenho = (ASSETS / f'{app}.svg').read_text(encoding='utf8')
    cinza = re.sub(r'(fill|stroke)="#[0-9A-Fa-f]{6}"', r'\1="#35383D"', desenho)
    (DADOS / app).mkdir(parents=True, exist_ok=True)
    (DADOS / app / 'watermark.svg').write_text(cinza, encoding='utf8')


def janelas_editor(pid):
    """Janelas X11 de um processo; no Windows a espera é só a animação por cima."""
    if JANELAS or not pid or not shutil.which('xprop'):
        return set()
    r = subprocess.run(['xprop', '-root', '_NET_CLIENT_LIST'], capture_output=True, text=True)
    achadas = set()
    for janela_ in re.findall(r'0x[0-9a-f]+', r.stdout):
        dono = subprocess.run(['xprop', '-id', janela_, '_NET_WM_PID'], capture_output=True, text=True).stdout
        if dono.strip().endswith(f'= {pid}'):
            achadas.add(janela_)
    return achadas


def opacidade_editor(janela_, visivel):
    """Deixa o editor carregar invisível, sem mudar nada nele."""
    nome = '_NET_WM_WINDOW_OPACITY'
    args = ['-remove', nome] if visivel else ['-f', nome, '32c', '-set', nome, '0']
    subprocess.run(['xprop', '-id', janela_, *args], capture_output=True)


def ajuste(app, chave):
    return ler_json(pasta_usuario(app) / 'settings.json').get(chave, modelo(app).get(chave))


def gravar_ajuste(app, chave, valor):
    arquivo = pasta_usuario(app) / 'settings.json'
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    atual = ler_json(arquivo)
    atual[chave] = valor
    arquivo.write_text(json.dumps(atual, indent=4, ensure_ascii=False), encoding='utf8')


def temas(app):
    nomes = set()
    pastas = list((DADOS / app / 'extensions').glob('*/package.json'))
    pastas += list((RAIZ / 'editor/resources/app/extensions').glob('theme-*/package.json'))
    for f in pastas:
        try:
            for t in json.loads(f.read_text(encoding='utf8')).get('contributes', {}).get('themes', []):
                nome = t.get('id') or t.get('label')
                if nome and not nome.startswith('%'):
                    nomes.add(nome)
        except (OSError, ValueError):
            pass
    return sorted(nomes, key=str.lower)


def temas_icones(app):
    """Icon themes the app has, as id -> label."""
    saida = {}
    pastas = list((DADOS / app / 'extensions').glob('*/package.json'))
    pastas += list((RAIZ / 'editor/resources/app/extensions').glob('theme-*/package.json'))
    for f in pastas:
        try:
            temas_ = json.loads(f.read_text(encoding='utf8')).get('contributes', {}).get('iconThemes', [])
        except (OSError, ValueError):
            continue
        for t in temas_:
            nome = t.get('label') or t.get('id', '')
            if nome.startswith('%'):
                nome = ler_json(f.with_name('package.nls.json')).get(nome.strip('%'), '')
            saida[t.get('id')] = nome
    return saida


def pacotes_icones(app):
    """Packs the Customize screen offers, as name -> id: ours when installed, and the one in use under its own name."""
    instalados = temas_icones(app)
    saida = {n: t for n, t in ICON_THEMES.items() if t in instalados}
    for tema in (ajuste(app, 'workbench.iconTheme'), modelo(app).get('workbench.iconTheme')):
        if tema and tema not in saida.values():
            nome = re.sub(r'\s*\(.*\)$', '', instalados.get(tema) or '').strip() or 'Other'
            saida[nome if nome not in saida else 'Other'] = tema
    return saida


def plugins(app):
    saida = {}
    for f in (DADOS / app / 'extensions').glob('*/package.json'):
        try:
            m = json.loads(f.read_text(encoding='utf8'))
        except (OSError, ValueError):
            continue
        nome = m.get('displayName') or m['name']
        nome = m['name'] if nome.startswith('%') else nome
        saida[f"{m['publisher']}.{m['name']}".lower()] = (nome, m.get('version', ''), m['publisher'])
    return sorted(((i, *v) for i, v in saida.items()), key=lambda x: x[1].lower())


def desligadas(app):
    return opcoes().get(app, {}).get('disabled', [])


def alternar_extensao(app, ident, ligada):
    lista = set(desligadas(app))
    lista.discard(ident) if ligada else lista.add(ident)
    gravar_opcao(app, 'disabled', sorted(lista))


def lembrar_fundo(app):
    try:
        return json.loads((ferramentas(app) / 'opcoes.json').read_text(encoding='utf8')).get('fundo', 0.1)
    except (OSError, ValueError):
        return 0.1


def gravar_fundo_forca(app, valor):
    ferramentas(app).mkdir(parents=True, exist_ok=True)
    (ferramentas(app) / 'opcoes.json').write_text(json.dumps({'fundo': valor}), encoding='utf8')


def gravar_fundo(origem, pasta):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    imagem = QImage(str(origem))
    if imagem.isNull():
        return False
    if imagem.width() > 1600:
        imagem = imagem.scaledToWidth(1600, Qt.SmoothTransformation)
    Path(pasta).mkdir(parents=True, exist_ok=True)
    return imagem.convertToFormat(QImage.Format_RGB888).save(str(Path(pasta) / 'fundo.jpg'), 'JPG', 72)


def area_de_trabalho():
    if JANELAS:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', "[Environment]::GetFolderPath('Desktop')"],
                           capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if r.stdout.strip():
            return Path(r.stdout.strip())
    else:
        r = shutil.which('xdg-user-dir') and subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True)
        if r and r.stdout.strip():
            return Path(r.stdout.strip())
    return CASA / 'Desktop'


def imagem_icone(nome, tipo):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    if not QGuiApplication.instance():
        QGuiApplication(sys.argv)
    imagem = QImage(256, 256, QImage.Format_ARGB32)
    imagem.fill(Qt.transparent)
    pintor = QPainter(imagem)
    QSvgRenderer(str(ASSETS / f'{nome}.svg')).render(pintor)
    pintor.end()
    alvo = DADOS / 'icons' / f'{nome}.{tipo}'
    alvo.parent.mkdir(parents=True, exist_ok=True)
    imagem.save(str(alvo))
    return alvo


def criar_atalho(app, desktop=True, menu=True):
    """Creates the Hub's or an app's shortcut; an app's goes straight to its screen."""
    b = marca()
    titulo = f"{b['name']} {aplicativos()[app]['title']}" if app else b['hub']
    congelado = getattr(sys, 'frozen', False)
    programa = sys.executable if congelado else f'env SUITE_ROOT={RAIZ} HOME={CASA} {sys.executable} {Path(__file__).resolve()}'
    args = f'--welcome {app}' if app else ''
    pasta = area_de_trabalho()
    if JANELAS:
        icone_ = imagem_icone(app or 'hub', 'ico')
        inicio = Path(os.environ.get('APPDATA', '')) / 'Microsoft/Windows/Start Menu/Programs'
        destinos = ([pasta / f'{titulo}.lnk'] if desktop else []) + ([inicio / f'{titulo}.lnk'] if menu else [])
        for destino in destinos:
            destino.parent.mkdir(parents=True, exist_ok=True)
            script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{destino}');$s.TargetPath='{sys.executable}';"
                      f"$s.Arguments='{args}';$s.WorkingDirectory='{RAIZ}';$s.IconLocation='{icone_}';$s.Save()")
            r = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode:
                destino.with_suffix('.bat').write_text(f'@start "" "{sys.executable}" {args}\r\n')
        return destinos[0] if destinos else None
    icone_ = imagem_icone(app or 'hub', 'png')
    texto = (f'[Desktop Entry]\nType=Application\nName={titulo}\nExec="{programa}" {args}\n'
             f'Icon={icone_}\nTerminal=false\nCategories=Development;\n') if congelado else (
             f'[Desktop Entry]\nType=Application\nName={titulo}\nExec={programa} {args}\nIcon={icone_}\nTerminal=false\n')
    nome = f"{b['name'].lower()}{'-' + app if app else ''}.desktop"
    aplicacoes = CASA / '.local/share/applications'
    destinos = ([pasta / nome] if desktop else []) + ([aplicacoes / nome] if menu else [])
    for destino in destinos:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding='utf8')
        destino.chmod(0o755)
    return destinos[0] if destinos else None


def origens_importacao():
    if JANELAS:
        base = Path(os.environ.get('APPDATA', ''))
    else:
        base = CASA / '.config'
    return [('VS Code', base / 'Code/User'), ('VSCodium', base / 'VSCodium/User')]


def importar(app, origem):
    """Copia ajustes de um perfil existente; a origem nunca é alterada."""
    usuario = pasta_usuario(app)
    usuario.mkdir(parents=True, exist_ok=True)
    atual = ler_json(usuario / 'settings.json')
    atual.update(ler_json(origem / 'settings.json'))
    (usuario / 'settings.json').write_text(json.dumps(atual, indent=4, ensure_ascii=False), encoding='utf8')
    if (origem / 'keybindings.json').exists():
        shutil.copy(origem / 'keybindings.json', usuario)
    if (origem / 'snippets').is_dir():
        shutil.copytree(origem / 'snippets', usuario / 'snippets', dirs_exist_ok=True)


SISTEMAS_JAVA = {
    'None': 'Plain .java files in src. Run them with the Run button; nothing to download.',
    'Maven': 'pom.xml and src/main/java. The usual choice in courses and companies; libraries come from Maven Central.',
    'Gradle': 'build.gradle and src/main/java. Used by Android and many Spring projects; downloads Gradle the first time.',
}
POM = '''<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <groupId>org.example</groupId>
    <artifactId>{nome}</artifactId>
    <version>1.0-SNAPSHOT</version>
    <properties>
        <maven.compiler.release>21</maven.compiler.release>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    </properties>
</project>
'''
GRADLE = '''plugins {{
    id 'application'
}}

repositories {{
    mavenCentral()
}}

java {{
    toolchain {{
        languageVersion = JavaLanguageVersion.of(21)
    }}
}}

application {{
    mainClass = 'Main'
}}
'''


def montar_java(raiz, sistema, nome):
    """Turns a plain src/ project into Maven or Gradle layout; the Java extension imports either."""
    if sistema not in ('Maven', 'Gradle'):
        return
    destino = raiz / 'src/main/java'
    destino.mkdir(parents=True, exist_ok=True)
    for f in list((raiz / 'src').glob('*.java')):
        f.replace(destino / f.name)
    artefato = re.sub(r'[^a-z0-9-]+', '-', nome.lower()).strip('-') or 'app'
    if sistema == 'Maven':
        (raiz / 'pom.xml').write_text(POM.replace('{nome}', artefato), encoding='utf8')
        ignorar = ['target/']
    else:
        (raiz / 'build.gradle').write_text(GRADLE.format(), encoding='utf8')
        (raiz / 'settings.gradle').write_text(f"rootProject.name = '{artefato}'\n", encoding='utf8')
        ignorar = ['build/', '.gradle/']
    arquivo = raiz / '.gitignore'
    linhas_ = arquivo.read_text(encoding='utf8').splitlines() if arquivo.exists() else []
    arquivo.write_text('\n'.join([*linhas_, *[i for i in ignorar if i not in linhas_]]) + '\n', encoding='utf8')


def criar_projeto(app, modelo_, nome, local, git=False, sistema=None):
    raiz = Path(local) / nome
    origem = PERFIS / app / 'templates' / modelo_
    if origem.is_dir() and modelo_ != 'Empty Project':
        shutil.copytree(origem, raiz)
    else:
        raiz.mkdir(parents=True)
    montar_java(raiz, sistema, nome)
    ignorar = raiz / '.gitignore'
    if git or ignorar.exists():
        # The editor keeps its own state in .vscode; it is not part of the project.
        linhas_ = ignorar.read_text(encoding='utf8').splitlines() if ignorar.exists() else []
        if not any(l.strip().rstrip('/') == '.vscode' for l in linhas_):
            ignorar.write_text('\n'.join([*linhas_, '.vscode/']) + '\n', encoding='utf8')
    if git:
        subprocess.run(['git', 'init', '-q'], cwd=raiz, check=True)
    if not confiavel(raiz):
        confiar(raiz)
    return raiz


def numero_versao(texto):
    return tuple(int(n) for n in re.findall(r'\d+', str(texto))[:3])


def pacote_atual():
    return 'berthline-windows.zip' if JANELAS else 'berthline-linux.tar.gz'


def contexto_ssl():
    """The system's certificates plus the bundled ones.

    The packaged libcrypto only looks where Ubuntu keeps certificates, so on Fedora it finds none.
    """
    contexto = ssl.create_default_context()
    if certifi:
        contexto.load_verify_locations(certifi.where())
    return contexto


def motivo_rede(erro):
    """Says in plain words why GitHub did not answer."""
    causa = getattr(erro, 'reason', erro)
    if isinstance(erro, urllib.error.HTTPError):
        if erro.code in (403, 429):
            return 'GitHub refused the request for now (rate limit). Try again in an hour.'
        return f'GitHub answered with error {erro.code}.'
    if isinstance(causa, ssl.SSLCertVerificationError):
        return f"Could not verify GitHub's certificate: {getattr(causa, 'verify_message', '') or causa}."
    if isinstance(causa, TimeoutError) or 'timed out' in str(causa):
        return 'GitHub took too long to answer. Check the connection.'
    if isinstance(causa, OSError) and causa.errno in (-2, -3, 11001, 11002, 11004):
        return 'No connection: the address of GitHub could not be found.'
    return f'Could not reach GitHub: {causa}'


def ler_url(url):
    pedido = urllib.request.Request(url, headers={'User-Agent': 'Berthline-Hub', 'Accept': 'application/vnd.github+json'})
    try:
        return urllib.request.urlopen(pedido, timeout=8, context=contexto_ssl())
    except OSError as e:
        raise OSError(motivo_rede(e)) from e


def checar_novidade():
    """Asks GitHub for the newest release. Sends no data; prereleases count while 0.x lasts."""
    with ler_url(f"https://api.github.com/repos/{marca().get('repo')}/releases?per_page=10") as r:
        lista = json.loads(r.read().decode('utf8'))
    versoes = [x for x in lista if not x.get('draft') and numero_versao(x.get('tag_name'))]
    if not versoes:
        return None
    x = max(versoes, key=lambda v: numero_versao(v['tag_name']))
    ativos = {a['name']: a['browser_download_url'] for a in x.get('assets', [])}
    return {'version': x['tag_name'].lstrip('v'), 'notes': x.get('body') or '', 'page': x.get('html_url', ''),
            'package': ativos.get(pacote_atual(), ''), 'sums': ativos.get('SHA256SUMS', '')}


def novidade():
    """The release to announce, or None."""
    tudo = opcoes()
    nova = tudo.get('update')
    if nova and numero_versao(nova['version']) > numero_versao(versao()) and nova['version'] != tudo.get('skip_version'):
        return nova
    return None


def baixar_verificado(url, somas, destino, progresso=None):
    """Downloads a package and keeps it only if it matches the release's SHA256SUMS."""
    with ler_url(somas) as r:
        linhas = r.read().decode('utf8').splitlines()
    nome = Path(destino).name
    esperado = next((l.split()[0].lower() for l in linhas if l.split()[-1].lstrip('*') == nome), None)
    if not esperado:
        raise ValueError(f'{nome} is not listed in SHA256SUMS')
    parte = Path(f'{destino}.part')
    parte.parent.mkdir(parents=True, exist_ok=True)
    soma = hashlib.sha256()
    with ler_url(url) as r, parte.open('wb') as saida:
        total = int(r.headers.get('Content-Length') or 0)
        feito = 0
        while bloco_ := r.read(1 << 20):
            saida.write(bloco_)
            soma.update(bloco_)
            feito += len(bloco_)
            if progresso and total:
                progresso(feito / total)
    if soma.hexdigest() != esperado:
        parte.unlink(missing_ok=True)
        raise ValueError('The download does not match its SHA-256')
    parte.replace(destino)
    return Path(destino)


def preparar_novidade(nova, progresso=None):
    """Downloads, checks and unpacks a release beside the install. Nothing is replaced yet."""
    area_ = troca.area(RAIZ)
    shutil.rmtree(area_, ignore_errors=True)
    arquivo = baixar_verificado(nova['package'], nova['sums'], area_ / pacote_atual(), progresso)
    if progresso:
        progresso(None)
    return troca.preparar_pacote(RAIZ, arquivo, nova['version'])


def depois_de_atualizar(area_):
    """First start of a new version: migrate what the person already has, then tell the helper to keep it."""
    for app in aplicativos():
        if (pasta_usuario(app) / 'settings.json').exists():
            preparar(app)
    gravar_geral('update', None)
    troca.confirmar(area_)
    threading.Thread(target=troca.limpar, args=(area_,), daemon=True).start()


def restos_de_troca():
    """Clears a finished update's work folder that an earlier start could not remove."""
    area_ = troca.area(RAIZ)
    if (area_ / 'ok').exists() or (area_ / 'error.txt').exists():
        threading.Thread(target=troca.limpar, args=(area_, 0), daemon=True).start()


CLASSES = {}  # the audit reaches the small windows through this


def moldura_windows(hwnd):
    """Cuts the caption off a native Windows frame and keeps its shadow."""
    import ctypes
    from ctypes import wintypes

    class MARGINS(ctypes.Structure):
        _fields_ = [('esq', ctypes.c_int), ('dir', ctypes.c_int), ('topo', ctypes.c_int), ('base', ctypes.c_int)]
    try:
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(MARGINS(0, 0, 1, 0)))
        # Windows 11 draws its rounded corners on this kind of window only when asked
        ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(ctypes.c_int(2)), 4)
    except (OSError, AttributeError):
        pass
    sem_mudar = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020  # NOSIZE NOMOVE NOZORDER NOACTIVATE FRAMECHANGED
    ctypes.windll.user32.SetWindowPos(wintypes.HWND(hwnd), None, 0, 0, 0, 0, sem_mudar)


def mensagem_windows(janela_, endereco):
    """Answers the two messages that decide where the frame is; None leaves the rest to Qt."""
    import ctypes
    from ctypes import wintypes
    msg = wintypes.MSG.from_address(endereco)
    if msg.message == 0x0083 and msg.wParam:  # WM_NCCALCSIZE: the whole window is client area
        if ctypes.windll.user32.IsZoomed(msg.hWnd):
            # maximized windows hang their frame off the screen; pull the content back in
            borda = ctypes.windll.user32.GetSystemMetrics(32) + ctypes.windll.user32.GetSystemMetrics(92)
            alto = ctypes.windll.user32.GetSystemMetrics(33) + ctypes.windll.user32.GetSystemMetrics(92)
            retangulo = wintypes.RECT.from_address(msg.lParam)
            retangulo.left += borda
            retangulo.right -= borda
            retangulo.top += alto
            retangulo.bottom -= alto
        return 0
    if msg.message == 0x0084:  # WM_NCHITTEST: edges resize, the bar moves, the rest is the window's
        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        caixa = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(msg.hWnd, ctypes.byref(caixa))
        escala = janela_.devicePixelRatioF() or 1
        borda = int(6 * escala)
        if janela_.redimensiona_ and not ctypes.windll.user32.IsZoomed(msg.hWnd):
            esq, dir_ = x < caixa.left + borda, x >= caixa.right - borda
            cima, baixo = y < caixa.top + borda, y >= caixa.bottom - borda
            lados = {(True, False, True, False): 13, (False, True, True, False): 14, (True, False, False, True): 16,
                     (False, True, False, True): 17, (True, False, False, False): 10, (False, True, False, False): 11,
                     (False, False, True, False): 12, (False, False, False, True): 15}
            lado = lados.get((esq, dir_, cima, baixo))
            if lado:
                return lado
        barra = janela_.barra_
        from PySide6.QtCore import QPoint
        ponto = wintypes.POINT(x, y)
        ctypes.windll.user32.ScreenToClient(msg.hWnd, ctypes.byref(ponto))
        local = QPoint(int(ponto.x / escala), int(ponto.y / escala))
        dentro = barra.mapFrom(janela_, local)
        if barra.rect().contains(dentro) and barra.arrasta(dentro):
            return 2  # HTCAPTION: native drag, snap and double-click
        return 1
    return None
AO_ABRIR = []  # work for the moment the first window is up


def limpar_ambiente():
    """Keep what the packaged Hub needs for itself away from every program it starts.

    With the Hub's own Qt on the library path, Dolphin or any system Qt app dies on start.
    Libraries are already resolved by now, and Qt reads its paths when the application is created.
    """
    if not getattr(sys, 'frozen', False):
        return
    original = os.environ.pop('LD_LIBRARY_PATH_ORIG', None)
    os.environ.pop('LD_LIBRARY_PATH', None)
    if original:
        os.environ['LD_LIBRARY_PATH'] = original
    for nome in ['QT_PLUGIN_PATH', 'QML2_IMPORT_PATH', *[n for n in os.environ if n.startswith('_PYI_')]]:
        os.environ.pop(nome, None)


def janela(inicial=None, lancar=None):
    forcar_xcb = not JANELAS and os.environ.get('DISPLAY') and 'QT_QPA_PLATFORM' not in os.environ
    if forcar_xcb:
        os.environ['QT_QPA_PLATFORM'] = 'xcb'
    from PySide6.QtCore import QEvent, QObject, QRect, QStandardPaths, Property, QEasingCurve, QProcess, QProcessEnvironment, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QUrl
    from PySide6.QtGui import (
        QColor, QDesktopServices, QFont, QFontDatabase, QGuiApplication, QIcon, QImage, QImageReader, QPainter, QPainterPath, QPen,
        QPixmap,
    )
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import (
        QAbstractButton, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QProgressBar,
        QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
        QPushButton, QScrollArea, QSlider, QStackedWidget, QToolButton, QVBoxLayout,
        QWidget,
    )

    VIDRO = [vidro_disponivel()]  # changes while the Hub runs
    ESTILO = """
    * { font-family: 'Inter', 'Segoe UI', 'Noto Sans', sans-serif; font-size: 13px; color: #E6E3DA; }
    QWidget#pagina, QScrollArea, QStackedWidget, QAbstractScrollArea { background: transparent; border: none; }
    QDialog, QMenu, QMessageBox { background: #1E2124; }
    QFrame#linhaV, QFrame#linhaH { background: #34383E; border: none; }
    QFrame#faixa { background: #1E2124; border: none; }
    QFrame#lista { border: 1px solid #34383E; }
    QLabel#mudo { color: #8F939A; font-size: 12px; }
    QLabel#titulo { font-size: 19px; font-weight: 600; }
    QLabel#grande { font-size: 19px; font-weight: 600; }
    QLabel#forte { font-weight: 600; }
    QLabel#secao { color: #EDE6D3; font-size: 12px; font-weight: 600; }
    QLabel#tag { font-size: 11px; font-weight: 600; border: 1px solid #5A5F66; padding: 0 5px; }
    QPushButton { background: transparent; border: 1px solid #5A5F66; border-radius: 1px; padding: 4px 10px; font-weight: 600; }
    QPushButton:hover { background: rgba(255, 255, 255, 14); }
    QPushButton:pressed { background: rgba(255, 255, 255, 26); }
    QPushButton:disabled { color: #6F737A; border-color: #34383E; }
    QPushButton#azul { background: ACENTO; border-color: ACENTO; color: #14161A; }
    QPushButton#azul:hover { background: #EDE6D3; border-color: #EDE6D3; }
    QPushButton#azul:disabled { background: transparent; color: #6F737A; border-color: #34383E; }
    QPushButton#aba { border: none; border-left: 3px solid transparent; border-radius: 0; text-align: left; padding: 7px 12px 7px 11px; color: #A9ACB2; font-weight: 400; }
    QPushButton#aba:hover { background: rgba(255, 255, 255, 12); color: #E6E3DA; }
    QPushButton#aba:checked { background: #1F2225; border-left-color: ACENTO; color: #FFFFFF; font-weight: 600; }
    QPushButton#guia { border: none; border-bottom: 2px solid transparent; border-radius: 0; padding: 12px 2px 10px; color: #8F939A; }
    QPushButton#guia:hover { background: transparent; color: #E6E3DA; }
    QPushButton#guia:checked { color: #FFFFFF; border-bottom-color: #EDE6D3; }
    QPushButton#seg { border-radius: 0; padding: 3px 10px; font-weight: 400; }
    QPushButton#seg:checked { background: #EDE6D3; color: #14161A; font-weight: 600; }
    QPushButton#seg:disabled { color: #6F737A; }
    QPushButton#link { border: none; color: #FFFFFF; padding: 2px 0; text-align: left; background: transparent; text-decoration: underline; }
    QPushButton#link:disabled { color: #6F737A; }
    QPushButton#volta { border: none; border-top: 1px solid #34383E; border-radius: 0; text-align: left; padding: 9px 14px; }
    QToolButton { border: none; border-radius: 1px; padding: 3px; }
    QToolButton:hover { background: rgba(255, 255, 255, 20); }
    QToolButton::menu-indicator { image: none; }
    QToolButton#engrenagem { border-bottom: 2px solid transparent; border-radius: 0; padding: 4px 4px 3px; }
    QToolButton#engrenagem:hover, QToolButton#engrenagem:checked { background: transparent; }
    QToolButton#engrenagem:checked { border-bottom-color: #EDE6D3; }
    QToolButton#filtro { padding: 1px 6px; color: #8F939A; }
    QToolButton#filtro:checked { color: #E6E3DA; font-weight: 600; }
    QLineEdit, QComboBox { background: transparent; border: 1px solid #4A4F56; border-radius: 1px; padding: 3px 7px; }
    QLineEdit#busca { background: transparent; border: none; }
    QLineEdit:focus, QComboBox:focus { border-color: ACENTO; }
    QComboBox::drop-down { border: none; width: 22px; }
    QComboBox::down-arrow { image: url(SETA); }
    QComboBox QAbstractItemView { background: #1E2124; selection-background-color: #34383E; }
    QListWidget { background: transparent; border: none; outline: 0; }
    QListWidget::item { border-radius: 0; }
    QListWidget::item:hover { background: rgba(255, 255, 255, 10); }
    QListWidget::item:selected { background: rgba(255, 255, 255, 18); color: #F0F0F0; }
    QListWidget#modelos::item { border-left: 3px solid transparent; }
    QListWidget#modelos::item:selected { background: #1F2225; border-left-color: ACENTO; }
    QListWidget#grade::item { padding: 4px; color: #A9ACB2; }
    QListWidget#grade::item:selected { background: #1F2225; color: #FFFFFF; border: 1px solid ACENTO; }
    QProgressBar { background: #34383E; border: none; }
    QLabel#tituloJanela { color: #A9ACB2; font-size: 12px; }
    QToolButton#botaoJanela, QToolButton#fecharJanela { border: none; border-radius: 3px; padding: 0; }
    QToolButton#botaoJanela:hover { background: rgba(255, 255, 255, 22); }
    QToolButton#fecharJanela:hover { background: #C8102E; }
    Dialogo { border: 1px solid #3A3E44; }
    QProgressBar::chunk { background: ACENTO; }
    QFrame#ferramenta { border: none; border-bottom: 1px solid #2C3035; }
    QFrame#ferramenta:hover { background: rgba(255, 255, 255, 7); }
    QMenu { border: 1px solid #34383E; padding: 4px; }
    QMenu::item { padding: 5px 24px 5px 12px; border-radius: 0; }
    QMenu::item:selected { background: #34383E; }
    QMenu::separator { height: 1px; background: #34383E; margin: 4px 8px; }
    QCheckBox { spacing: 7px; color: #A9ADB3; }
    QCheckBox:checked { color: #F0F0F0; }
    QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #8F939A; border-radius: 2px; background: transparent; }
    QCheckBox::indicator:hover { border-color: ACENTO; }
    QCheckBox::indicator:checked { background: ACENTO; border-color: ACENTO; image: url(VISTO); }
    QCheckBox::indicator:disabled { border-color: #34383E; background: #34383E; }
    QSlider::groove:horizontal { height: 3px; background: #4A4F56; }
    QSlider::handle:horizontal { width: 9px; margin: -6px 0; border-radius: 0; background: #EDE6D3; }
    QScrollBar:vertical { background: transparent; width: 8px; }
    QScrollBar::handle:vertical { background: #4A4F56; border-radius: 0; min-height: 24px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    """
    AZUL = '#EDE6D3'

    def estilo(cor):
        return (ESTILO.replace('SETA', (ASSETS / 'seta.svg').as_posix()).replace('VISTO', (ASSETS / 'visto.svg').as_posix())
                .replace('ACENTO', cor))

    def com_vidro(janela_):
        """Deixa a janela translúcida com desfoque do sistema, quando existe."""
        if VIDRO[0]:
            janela_.setAttribute(Qt.WA_TranslucentBackground)

    def surgir(janela_):
        janela_.setWindowOpacity(0.0)
        janela_.show()
        if VIDRO[0]:
            aplicar_vidro(int(janela_.winId()))
        animacao = QPropertyAnimation(janela_, b'windowOpacity', janela_)
        animacao.setDuration(180)
        animacao.setStartValue(0.0)
        animacao.setEndValue(1.0)
        animacao.setEasingCurve(QEasingCurve.OutCubic)
        animacao.start()
        janela_.entrada = animacao

    BORDA = 6  # how far into the window a resize can start, in logical pixels

    class Moldura:
        """The window draws its own title bar and the system still moves, resizes and snaps it.

        Windows keeps its native frame (shadow, snap, Aero shake) with the caption cut away;
        Linux gets a frameless window that hands moves and resizes back to the window manager.
        """
        barra_ = None
        redimensiona_ = False

        def showEvent(self, evento):
            super().showEvent(evento)
            if JANELAS and self.barra_ and not getattr(self, 'moldada_', False):
                self.moldada_ = True
                moldura_windows(int(self.winId()))
            if VIDRO[0] and self.barra_:
                aplicar_vidro(int(self.winId()))

        def nativeEvent(self, tipo, mensagem):
            if JANELAS and self.barra_ and tipo == b'windows_generic_MSG':
                resposta = mensagem_windows(self, int(mensagem))
                if resposta is not None:
                    return True, resposta
            return super().nativeEvent(tipo, mensagem)

        def changeEvent(self, evento):
            super().changeEvent(evento)
            if self.barra_ and evento.type() == QEvent.WindowStateChange:
                self.barra_.estado_mudou()

    def desenho_botao(tipo, cor):
        figura = QPixmap(QSize(28, 28) * 2)
        figura.setDevicePixelRatio(2)
        figura.fill(Qt.transparent)
        p = QPainter(figura)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(cor), 1.0))
        x, y = 9, 9
        if tipo == 'min':
            p.drawLine(QPointF(x, y + 5), QPointF(x + 10, y + 5))
        elif tipo == 'max':
            p.drawRect(QRectF(x + 0.5, y + 0.5, 9, 9))
        elif tipo == 'restaurar':
            p.drawRect(QRectF(x + 0.5, y + 2.5, 7, 7))
            p.drawPolyline([QPointF(x + 2.5, y + 2.5), QPointF(x + 2.5, y + 0.5), QPointF(x + 9.5, y + 0.5),
                            QPointF(x + 9.5, y + 7.5), QPointF(x + 7.5, y + 7.5)])
        else:
            p.drawLine(QPointF(x, y), QPointF(x + 10, y + 10))
            p.drawLine(QPointF(x + 10, y), QPointF(x, y + 10))
        p.end()
        return QIcon(figura)

    class BarraTitulo(QWidget):
        """The window's own title bar: its mark, its title or tabs, and the three buttons."""

        def __init__(self, janela_, redimensiona, conteudo=None, icone_=None):
            super().__init__(janela_)
            self.setObjectName('barra')
            self.janela_ = janela_
            self.redimensiona = redimensiona
            self.setFixedHeight(44 if conteudo else 34)
            h = QHBoxLayout(self)
            h.setContentsMargins(12 if not conteudo else 0, 0, 8, 0)
            h.setSpacing(4)
            if conteudo:
                h.addWidget(conteudo, 1)
            else:
                marca_ = QLabel()
                marca_.setPixmap(QIcon(icone_ or str(ASSETS / 'hub.svg')).pixmap(16, 16))
                h.addWidget(marca_)
                self.titulo = rotulo(janela_.windowTitle(), 'tituloJanela')
                janela_.windowTitleChanged.connect(self.titulo.setText)
                h.addWidget(self.titulo, 1)
            self.botoes = {}
            for tipo, dica in (('min', 'Minimize'), ('max', 'Maximize'), ('fechar', 'Close')):
                if (tipo == 'max' and not redimensiona) or (tipo == 'min' and isinstance(janela_, QDialog)):
                    continue
                b = QToolButton()
                b.setObjectName('fecharJanela' if tipo == 'fechar' else 'botaoJanela')
                b.setAccessibleName(dica)
                b.setToolTip(dica)
                b.setFixedSize(28, 28)
                b.setIconSize(QSize(28, 28))
                b.setIcon(desenho_botao(tipo, '#C9CCD1'))
                h.addWidget(b, 0, Qt.AlignVCenter)
                self.botoes[tipo] = b
            if 'min' in self.botoes:
                self.botoes['min'].clicked.connect(janela_.showMinimized)
            self.botoes['fechar'].clicked.connect(janela_.close)
            if 'max' in self.botoes:
                self.botoes['max'].clicked.connect(self.alternar)

        def alternar(self):
            self.janela_.showNormal() if self.janela_.isMaximized() else self.janela_.showMaximized()

        def estado_mudou(self):
            if 'max' in self.botoes:
                maior = self.janela_.isMaximized()
                self.botoes['max'].setIcon(desenho_botao('restaurar' if maior else 'max', '#C9CCD1'))
                self.botoes['max'].setAccessibleName('Restore' if maior else 'Maximize')
                self.botoes['max'].setToolTip('Restore' if maior else 'Maximize')

        def arrasta(self, ponto):
            """True where a press should move the window: the bar itself or text, never a control."""
            alvo = self.childAt(ponto)
            while alvo and alvo is not self:
                if isinstance(alvo, (QAbstractButton, QLineEdit, QComboBox)):
                    return False
                alvo = alvo.parentWidget()
            return True

        def mousePressEvent(self, e):
            self.inicio = None
            if e.button() == Qt.LeftButton and not JANELAS and self.arrasta(e.position().toPoint()):
                if not self.janela_.windowHandle().startSystemMove():
                    self.inicio = e.globalPosition().toPoint() - self.janela_.frameGeometry().topLeft()

        def mouseMoveEvent(self, e):
            if getattr(self, 'inicio', None) is not None and not self.janela_.isMaximized():
                self.janela_.move(e.globalPosition().toPoint() - self.inicio)

        def mouseReleaseEvent(self, _):
            self.inicio = None

        def mouseDoubleClickEvent(self, e):
            if e.button() == Qt.LeftButton and self.redimensiona and not JANELAS:
                self.alternar()

    class Borda(QWidget):
        """Invisible strip on a frameless window's edge that starts the system's own resize."""

        CURSORES = {Qt.LeftEdge: Qt.SizeHorCursor, Qt.RightEdge: Qt.SizeHorCursor, Qt.TopEdge: Qt.SizeVerCursor,
                    Qt.BottomEdge: Qt.SizeVerCursor}

        def __init__(self, janela_, lados):
            super().__init__(janela_)
            self.lados = lados
            canto = lados in (Qt.TopEdge | Qt.LeftEdge, Qt.BottomEdge | Qt.RightEdge)
            outro = lados in (Qt.TopEdge | Qt.RightEdge, Qt.BottomEdge | Qt.LeftEdge)
            self.setCursor(Qt.SizeFDiagCursor if canto else Qt.SizeBDiagCursor if outro else self.CURSORES[lados])

        def mousePressEvent(self, e):
            self.inicio = None
            if e.button() != Qt.LeftButton or self.window().isMaximized():
                return
            if not self.window().windowHandle().startSystemResize(self.lados):
                # the window manager said no: follow the mouse here instead
                self.inicio = (e.globalPosition().toPoint(), self.window().geometry())

        def mouseMoveEvent(self, e):
            if not getattr(self, 'inicio', None):
                return
            origem, caixa = self.inicio
            d = e.globalPosition().toPoint() - origem
            nova = QRect(caixa)
            minimo = self.window().minimumSizeHint().expandedTo(QSize(320, 240))
            if self.lados & Qt.LeftEdge:
                nova.setLeft(min(caixa.left() + d.x(), caixa.right() - minimo.width()))
            if self.lados & Qt.RightEdge:
                nova.setRight(max(caixa.right() + d.x(), caixa.left() + minimo.width()))
            if self.lados & Qt.TopEdge:
                nova.setTop(min(caixa.top() + d.y(), caixa.bottom() - minimo.height()))
            if self.lados & Qt.BottomEdge:
                nova.setBottom(max(caixa.bottom() + d.y(), caixa.top() + minimo.height()))
            self.window().setGeometry(nova)

        def mouseReleaseEvent(self, _):
            self.inicio = None

    class Bordas(QObject):
        def __init__(self, janela_):
            super().__init__(janela_)
            self.janela_ = janela_
            l, r_, t, b = Qt.LeftEdge, Qt.RightEdge, Qt.TopEdge, Qt.BottomEdge
            self.faixas = [Borda(janela_, lado) for lado in (l, r_, t, b, t | l, t | r_, b | l, b | r_)]
            janela_.installEventFilter(self)

        def eventFilter(self, _obj, evento):
            if evento.type() in (QEvent.Resize, QEvent.Show, QEvent.WindowStateChange):
                largura, altura, d = self.janela_.width(), self.janela_.height(), BORDA
                lugares = [(0, d, d, altura - 2 * d), (largura - d, d, d, altura - 2 * d), (d, 0, largura - 2 * d, d),
                           (d, altura - d, largura - 2 * d, d), (0, 0, d, d), (largura - d, 0, d, d),
                           (0, altura - d, d, d), (largura - d, altura - d, d, d)]
                for faixa, lugar in zip(self.faixas, lugares):
                    faixa.setGeometry(*lugar)
                    faixa.setVisible(not self.janela_.isMaximized())
                    faixa.raise_()
            return False

    def integrar(janela_, redimensiona=False, conteudo=None, icone_=None):
        """Puts the title bar on top of the window and returns the widget the window builds into."""
        janela_.redimensiona_ = redimensiona
        com_vidro(janela_)
        if not JANELAS:
            janela_.setWindowFlag(Qt.FramelessWindowHint, True)
        externo = QVBoxLayout(janela_)
        externo.setContentsMargins(1, 1, 1, 1) if not JANELAS else externo.setContentsMargins(0, 0, 0, 0)
        externo.setSpacing(0)
        janela_.barra_ = BarraTitulo(janela_, redimensiona, conteudo, icone_)
        externo.addWidget(janela_.barra_)
        if not conteudo:
            externo.addWidget(linha('linhaH'))
        corpo = QWidget()
        corpo.setObjectName('corpo')
        externo.addWidget(corpo, 1)
        if redimensiona and not JANELAS:
            janela_.bordas_ = Bordas(janela_)
        return corpo

    class Raiz(Moldura, QWidget):
        """Janela principal: pinta o próprio fundo para o vidro funcionar."""

        def paintEvent(self, _):
            p = QPainter(self)
            p.setCompositionMode(QPainter.CompositionMode_Source)
            p.fillRect(self.rect(), QColor(22, 24, 27, 205) if VIDRO[0] else QColor('#16181B'))
            if self.barra_ and not JANELAS and not self.isMaximized():
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                p.setPen(QColor('#3A3E44'))
                p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    class Dialogo(Moldura, QDialog):
        """Hub dialog with the same title bar as the windows, and the same glass."""

        def paintEvent(self, evento):
            Raiz.paintEvent(self, evento)

    class Troca(QStackedWidget):
        """Troca de página com passagem suave."""

        def ir(self, pagina):
            if pagina is self.currentWidget():
                return
            self.setCurrentWidget(pagina)
            if not opcoes().get('transitions', True):
                return
            efeito = QGraphicsOpacityEffect(pagina)
            pagina.setGraphicsEffect(efeito)
            animacao = QPropertyAnimation(efeito, b'opacity', pagina)
            animacao.setDuration(170)
            animacao.setStartValue(0.0)
            animacao.setEndValue(1.0)
            animacao.setEasingCurve(QEasingCurve.OutCubic)
            animacao.finished.connect(lambda: pagina.setGraphicsEffect(None))
            animacao.start()
            pagina.entrada = animacao

    def rotulo(texto, nome=None):
        r = QLabel(texto)
        if nome:
            r.setObjectName(nome)
        return r

    def linha(nome):
        f = QFrame()
        f.setObjectName(nome)
        f.setFixedHeight(1) if nome == 'linhaH' else f.setFixedWidth(1)
        return f

    def icone(app, tamanho):
        r = QLabel()
        r.setPixmap(QIcon(str(ASSETS / f'{app}.svg')).pixmap(tamanho, tamanho))
        return r

    def link(texto, acao):
        b = QPushButton(texto)
        b.setObjectName('link')
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(acao)
        return b

    def em_fundo(trabalho, depois):
        """Runs network work off the window's thread; `depois` gets (result, error) back on it."""
        saida = []

        def rodar():
            try:
                saida.append((trabalho(), None))
            except Exception as e:  # whatever it was, the window has to hear about it
                saida.append((None, str(e) or type(e).__name__))
        threading.Thread(target=rodar, daemon=True).start()
        vigia = QTimer(QApplication.instance())

        def olhar():
            if saida:
                vigia.stop()
                vigia.deleteLater()
                depois(*saida[0])
        vigia.timeout.connect(olhar)
        vigia.start(100)

    def lampada(estado):
        r = QLabel()
        r.setFixedSize(9, 9)
        r.setStyleSheet(f'background:{LAMPADAS[estado]};border-radius:4px;')
        return r

    def etiqueta(texto, cor=None):
        r = rotulo(texto, 'tag')
        if cor:
            r.setStyleSheet(f'color:{cor};border-color:{cor};')
        return r

    def segmento(textos, atual, ao_mudar):
        """Row of joined buttons where exactly one stays selected."""
        caixa = QWidget()
        h = QHBoxLayout(caixa)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        grupo = QButtonGroup(caixa)
        caixa.botoes = {}
        for texto in textos:
            b = QPushButton(texto)
            b.setObjectName('seg')
            b.setCheckable(True)
            b.setChecked(texto == atual)
            b.clicked.connect(lambda _=False, t=texto: ao_mudar(t))
            grupo.addButton(b)
            h.addWidget(b)
            caixa.botoes[texto] = b
        return caixa

    def nome_app(app):
        return f"{marca()['name']} {aplicativos()[app]['title']}"

    class Combo(QComboBox):
        def wheelEvent(self, evento):
            evento.ignore()

    def draw_boat(p, kind, cor, fase):
        """Draws one boat in a 120 x 78 box, with the hull's keel on y=72."""
        creme = QColor('#EDE6D3')

        def traco(caminho, cor_, largura):
            p.setPen(QPen(cor_, largura, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(caminho)

        casco = QPainterPath()
        for i, (x, y) in enumerate(((8, 52), (112, 52), (100, 72), (20, 72))):
            casco.moveTo(x, y) if i == 0 else casco.lineTo(x, y)
        casco.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(creme if kind == 'hub' else cor)
        p.drawPath(casco)
        if kind == 'java':
            p.fillRect(QRectF(38, 40, 46, 12), cor)
            p.fillRect(QRectF(52, 24, 14, 16), creme)
            p.fillRect(QRectF(52, 29, 14, 4), cor)
            for i, x in enumerate((48, 59, 70)):
                t = (fase * .3 + i / 3) % 1
                vapor = QPainterPath()
                vapor.moveTo(x, 22 - 8 * t)
                vapor.cubicTo(x - 4, 17 - 8 * t, x + 4, 14 - 8 * t, x, 9 - 8 * t)
                tom = QColor(cor)
                tom.setAlphaF(math.sin(math.pi * t))
                traco(vapor, tom, 3.4)
        elif kind == 'web':
            for pontos in (((42, 12), (22, 30), (42, 48)), ((78, 12), (98, 30), (78, 48))):
                seta = QPainterPath()
                seta.moveTo(*pontos[0])
                seta.lineTo(*pontos[1])
                seta.lineTo(*pontos[2])
                traco(seta, cor, 6.5)
            mastro = QPainterPath()
            mastro.moveTo(68, 4)
            mastro.lineTo(52, 52)
            traco(mastro, creme, 4.5)
        elif kind == 'hub':
            p.fillRect(QRectF(54, 12, 5, 40), creme)
            bandeira = QPainterPath()
            for i, (x, y) in enumerate(((59, 14), (84, 14), (75, 23), (84, 32), (59, 32))):
                bandeira.moveTo(x, y) if i == 0 else bandeira.lineTo(x, y)
            bandeira.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#C8102E'))
            p.drawPath(bandeira)
        else:
            cabine = QPainterPath()
            cabine.addRect(QRectF(32, 20, 56, 32))
            traco(cabine, cor, 4)
            prompt = QPainterPath()
            prompt.moveTo(41, 28)
            prompt.lineTo(50, 36)
            prompt.lineTo(41, 44)
            prompt.moveTo(55, 44)
            prompt.lineTo(72, 44)
            traco(prompt, creme, 3.6)

    class Sea(QWidget):
        """A boat on animated water. Moving boats sail; anchored ones only rock."""

        def __init__(self, kind, largura=300, altura=150, moving=True, boat=132, x=None, cor=None):
            super().__init__()
            self.setFixedSize(largura, altura)
            self.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.kind = kind
            self.moving = moving
            self.boat = boat
            self.x_boat = (largura - boat) / 2 if x is None else x
            self.viagem = None
            self.fase = 0.0
            self.cor = QColor(cor or aplicativos().get(kind, {}).get('accent', '#7FA6C9'))
            self.relogio = QTimer(self)
            self.relogio.timeout.connect(self.passo)
            self.animar = opcoes().get('transitions', True)

        def showEvent(self, _):
            if self.animar:
                self.relogio.start(33 if self.moving else 66)

        def hideEvent(self, _):
            self.relogio.stop()

        def passo(self):
            self.fase += .1
            self.update()

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            largura = self.width()
            agua = self.height() - 15
            escala = self.boat / 120
            x = self.x_boat
            if self.viagem is not None:
                x = -self.boat + self.viagem * (largura + self.boat)
            balanco = math.sin(self.fase * .6)
            p.save()
            p.translate(x, agua + 3 - 72 * escala + balanco * 1.6)
            p.scale(escala, escala)
            if self.moving and self.viagem is None:
                p.setPen(QPen(QColor('#8F939A'), 1.6))
                for i, (y, comprimento) in enumerate(((60, 16), (66, 22), (72, 12))):
                    t = (self.fase * .4 + i / 3) % 1
                    tom = QColor('#8F939A')
                    tom.setAlphaF(math.sin(math.pi * t) * .9)
                    p.setPen(QPen(tom, 1.6))
                    x0 = -8 - 22 * t - comprimento
                    p.drawLine(QPointF(x0, y), QPointF(x0 + comprimento, y))
            p.translate(60, 62)
            p.rotate(balanco * 1.8)
            p.translate(-60, -62)
            draw_boat(p, self.kind, self.cor, self.fase)
            p.restore()
            passo_ = self.fase * (5 if self.moving else 1.2)
            for camada, (y, alfa, grossura, sentido) in enumerate(((agua, 255, 2.0, 1), (agua + 7, 97, 1.3, .6))):
                onda = QPainterPath()
                for x_ in range(0, largura + 5, 4):
                    h = y + math.sin((x_ + passo_ * sentido) / 7.64) * 3
                    onda.moveTo(x_, h) if x_ == 0 else onda.lineTo(x_, h)
                tom = QColor(self.cor)
                tom.setAlpha(alfa)
                p.setPen(QPen(tom, grossura))
                p.setBrush(Qt.NoBrush)
                p.drawPath(onda)

    class Partida(Raiz):
        """Waiting window: the app's boat sails until the editor is ready."""

        def __init__(self, app, texto, etapas=False):
            super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            self.setObjectName('raiz')
            self.app = app
            com_vidro(self)
            cor = aplicativos()[app].get('accent', AZUL)
            self.setStyleSheet(estilo(cor))
            self.setFixedSize(380, 250)
            v = QVBoxLayout(self)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            self.detalhe = rotulo('', 'mudo')
            self.detalhe.setAlignment(Qt.AlignCenter)
            self.detalhe.setFixedHeight(26)
            v.addWidget(self.detalhe)
            v.addWidget(Sea(app, 380, 180, True, 156))
            v.addWidget(linha('linhaH'))
            rodape = QHBoxLayout()
            rodape.setContentsMargins(14, 0, 14, 0)
            rodape.setSpacing(14)
            self.texto = rotulo(texto)
            self.passos = {}
            if etapas:
                self.texto.hide()
                for chave, nome_ in (('', 'Editor'), ('extensions', 'Extensions'), ('java', 'Java server')):
                    if chave != 'java' or aplicativos()[app].get('memory'):
                        self.passos[chave] = rotulo(nome_, 'mudo')
                        rodape.addWidget(self.passos[chave])
                self.cor = cor
                self.etapa('')
            rodape.addWidget(self.texto)
            rodape.addStretch(1)
            if etapas:
                rodape.addWidget(rotulo('Click to skip', 'mudo'))
            caixa = QWidget()
            caixa.setFixedHeight(42)
            caixa.setLayout(rodape)
            v.addWidget(caixa)
            tela = QGuiApplication.primaryScreen().availableGeometry()
            self.move(tela.center() - self.rect().center())

        def etapa(self, agora, detalhe=''):
            """Marks the current stage in the footer; earlier ones stay lit."""
            self.detalhe.setText(detalhe)
            chaves = list(self.passos)
            atual = chaves.index(agora) if agora in chaves else len(chaves)
            for i, chave in enumerate(chaves):
                estilo_ = f'color:{self.cor};font-weight:600;font-size:12px;' if i == atual else ('color:#E6E3DA;font-size:12px;' if i < atual else '')
                self.passos[chave].setStyleSheet(estilo_)

        def aviso(self, texto):
            """Replaces the stages with one sentence."""
            for r in self.passos.values():
                r.hide()
            self.texto.setText(texto)
            self.texto.show()

        def mouseReleaseEvent(self, _):
            if getattr(self, 'pular', None):
                self.pular()

        def sair(self, depois):
            animacao = QPropertyAnimation(self, b'windowOpacity', self)
            animacao.setDuration(240)
            animacao.setStartValue(1.0)
            animacao.setEndValue(0.0)
            animacao.finished.connect(depois)
            animacao.start()
            self.saida = animacao

    class Abertura(Raiz):
        """The logo's boat sails across while the Hub opens. One click skips it."""

        def __init__(self, depois):
            super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            self.setObjectName('raiz')
            com_vidro(self)
            self.setFixedSize(460, 230)
            self.depois = depois
            self.terminou = False
            v = QVBoxLayout(self)
            v.setContentsMargins(0, 22, 0, 16)
            v.setSpacing(6)
            self.barco = Sea('hub', 460, 150, True, 124)
            self.barco.viagem = 0.0
            nome = QHBoxLayout()
            nome.setSpacing(8)
            nome.addStretch(1)
            nome.addWidget(rotulo(marca()['name'], 'grande'))
            nome.addWidget(rotulo(versao(), 'mudo'), 0, Qt.AlignBottom)
            nome.addStretch(1)
            v.addWidget(self.barco)
            v.addLayout(nome)
            tela = QGuiApplication.primaryScreen().availableGeometry()
            self.move(tela.center() - self.rect().center())
            self.curso = QPropertyAnimation(self, b'percurso', self)
            self.curso.setDuration(1600)
            self.curso.setStartValue(0.0)
            self.curso.setEndValue(1.0)
            self.curso.setEasingCurve(QEasingCurve.InOutSine)
            self.curso.finished.connect(self.fim)

        def ler(self):
            return self.barco.viagem

        def mudar(self, valor):
            self.barco.viagem = valor
            self.barco.update()

        percurso = Property(float, ler, mudar)

        def comecar(self):
            surgir(self)
            self.curso.start()

        def mouseReleaseEvent(self, _):
            self.curso.stop()
            self.fim()

        def fim(self):
            if self.terminou:
                return
            self.terminou = True
            animacao = QPropertyAnimation(self, b'windowOpacity', self)
            animacao.setDuration(120)
            animacao.setStartValue(1.0)
            animacao.setEndValue(0.0)
            animacao.finished.connect(lambda: (self.depois(), self.close()))
            animacao.start()
            self.saida = animacao

    def abrir(app, *alvos, comando_=None):
        if alvos and not pode_abrir(alvos[0]):
            return
        inicio = time.time()
        limite = 110 if aplicativos()[app].get('memory') else 30
        partida = Partida(app, '', True)
        for w in QApplication.topLevelWidgets():
            if w is not partida and not isinstance(w, QMenu):
                w.hide()
        surgir(partida)
        QApplication.processEvents()
        limpar_etapa(app)
        escondidas = set()
        processo = abrir_app(app, alvos, comando_=comando_)

        def terminar():
            relogio.stop()
            for janela_ in escondidas:
                opacidade_editor(janela_, True)
            partida.sair(QApplication.quit)

        def conferir():
            for janela_ in janelas_editor(getattr(processo, 'pid', None)) - escondidas:
                opacidade_editor(janela_, False)
                escondidas.add(janela_)
            agora, _, detalhe = etapa_atual(app).partition('|')
            passou = int(time.time() - inicio)
            if not agora:
                detalhe = 'Window open' if escondidas else 'Starting the editor'
            elif agora == 'java':
                detalhe = f'{detalhe or "Java server"} · {passou} s'
            partida.etapa(agora, detalhe)
            if agora == 'ready':
                terminar()
            elif time.time() - inicio > limite:
                relogio.stop()
                partida.aviso('Still loading in the background')
                QTimer.singleShot(1500, terminar)
        relogio = QTimer(partida)
        relogio.timeout.connect(conferir)
        relogio.start(120)
        partida.pular = terminar

    def mostrar(app, alvo=None):
        """Brings up an editor that is already running, with no waiting window."""
        abrir_app(app, [alvo] if alvo else [])
        QApplication.quit()

    def entrar(app, depois):
        """Mostra o barco por um instante ao trocar de app."""
        if not opcoes().get('transitions', True):
            return depois()
        partida = Partida(app, f'Opening {nome_app(app)}…')
        surgir(partida)
        QTimer.singleShot(900, lambda: partida.sair(lambda: (partida.close(), depois())))
        QApplication.instance().partida = partida

    def pode_abrir(pasta):
        if confiavel(pasta):
            return True
        caminho = Path(pasta)
        c = QMessageBox(QApplication.activeWindow())
        c.setWindowTitle('Trust this folder?')
        c.setText(f'Do you trust the code in {caminho.name}?')
        c.setInformativeText('Trusted folders run tasks, debuggers and extensions. '
                             'Restricted Mode is safer for code you did not write, but Java and Run stay off.')
        so_ela = c.addButton('Trust folder', QMessageBox.AcceptRole)
        mae = c.addButton(f'Trust all in {caminho.parent.name or caminho.parent}', QMessageBox.AcceptRole)
        restrito = c.addButton('Open restricted', QMessageBox.DestructiveRole)
        c.addButton('Cancel', QMessageBox.RejectRole)
        so_ela.setObjectName('azul')
        c.exec()
        escolha = c.clickedButton()
        if escolha == so_ela:
            confiar(caminho)
        elif escolha == mae:
            confiar(caminho.parent)
        return escolha in (so_ela, mae, restrito)

    def nota():
        r = rotulo('', 'mudo')
        r.setWordWrap(True)
        return r

    def avisar(rotulo_, texto, erro=False):
        rotulo_.setText(texto)
        rotulo_.setStyleSheet(f'color:{ALERTA};' if erro else '')
        rotulo_.setVisible(bool(texto))

    def conteudo_modelo(app, nome):
        """What a template puts in the folder, said in one line."""
        origem = PERFIS / app / 'templates' / nome
        arquivos = sorted(f.name for f in origem.rglob('*') if f.is_file() and not f.name.startswith('.')) if origem.is_dir() else []
        return ', '.join(arquivos[:3]) + (' …' if len(arquivos) > 3 else '') if arquivos else 'an empty folder'

    class NovoProjeto(Dialogo):
        """New project the way JetBrains IDEs lay it out: kinds on the left, a short form on the right."""

        def __init__(self, pai, app):
            super().__init__(pai)
            self.setWindowTitle('New Project')
            self.setFixedSize(660, 430)
            self.app = app
            self.projeto = None
            self.modelos_ = aplicativos()[app].get('templates', [])
            self.tipos = QListWidget()
            self.tipos.setObjectName('modelos')
            self.tipos.setFixedWidth(170)
            for texto in ('New Project', 'Empty Project') if self.modelos_ else ('Empty Project',):
                item = QListWidgetItem(texto)
                item.setSizeHint(QSize(160, 34))
                self.tipos.addItem(item)
            self.tipos.setCurrentRow(0)
            self.tipos.currentRowChanged.connect(self.avaliar)
            self.nome = QLineEdit('untitled')
            self.nome.selectAll()
            self.local = QLineEdit(curto(pasta_projetos(app)))
            pasta = QPushButton('Browse')
            pasta.clicked.connect(self.escolher)
            fila = QHBoxLayout()
            fila.setSpacing(6)
            fila.addWidget(self.local, 1)
            fila.addWidget(pasta)
            self.sobre_nome = nota()
            self.existe = nota()
            self.git = QCheckBox('Create Git repository')
            self.git.setEnabled(bool(shutil.which('git')))
            self.git.setToolTip('' if shutil.which('git') else 'Git was not found on this computer.')
            self.sobre_inicio = nota()
            self.inicio = segmento(self.modelos_, self.modelos_[0], self.descrever) if len(self.modelos_) > 1 else None
            self.exemplo = QCheckBox('Add sample code') if len(self.modelos_) == 1 else None
            self.sobre_exemplo = nota()
            if self.exemplo:
                self.exemplo.setChecked(True)
                self.exemplo.toggled.connect(lambda _: self.descrever())
            self.sistema = segmento(SISTEMAS_JAVA, 'None', self.descrever) if app == 'java' else None
            self.sobre_sistema = nota()
            self.erro = nota()
            self.criar_ = QPushButton('Create')
            self.criar_.setObjectName('azul')
            self.criar_.setDefault(True)
            self.criar_.clicked.connect(self.criar)
            cancelar = QPushButton('Cancel')
            cancelar.clicked.connect(self.reject)
            grade = QGridLayout()
            grade.setHorizontalSpacing(14)
            grade.setVerticalSpacing(10)
            grade.setColumnMinimumWidth(0, 70)
            grade.addWidget(rotulo('Name'), 0, 0)
            grade.addWidget(self.nome, 0, 1)
            grade.addWidget(self.sobre_nome, 1, 1)
            grade.addWidget(rotulo('Location'), 2, 0)
            grade.addLayout(fila, 2, 1)
            grade.addWidget(self.existe, 3, 1)
            grade.addWidget(self.git, 4, 1)
            self.extras = []
            if self.sistema:
                rot = rotulo('Build system')
                grade.addWidget(rot, 5, 0)
                grade.addWidget(self.sistema, 5, 1, Qt.AlignLeft)
                grade.addWidget(self.sobre_sistema, 6, 1)
                self.extras += [rot, self.sistema, self.sobre_sistema]
            if self.inicio:
                rot = rotulo('Starter')
                grade.addWidget(rot, 7, 0)
                grade.addWidget(self.inicio, 7, 1, Qt.AlignLeft)
                grade.addWidget(self.sobre_inicio, 8, 1)
                self.extras += [rot, self.inicio, self.sobre_inicio]
            if self.exemplo:
                grade.addWidget(self.exemplo, 7, 1)
                grade.addWidget(self.sobre_exemplo, 8, 1)
                self.extras += [self.exemplo, self.sobre_exemplo]
            grade.setColumnMinimumWidth(0, 90)
            direita = QVBoxLayout()
            direita.setContentsMargins(20, 4, 0, 0)
            direita.setSpacing(0)
            direita.addLayout(grade)
            direita.addStretch(1)
            corpo = QHBoxLayout()
            corpo.setSpacing(0)
            corpo.addWidget(self.tipos)
            corpo.addSpacing(12)
            corpo.addWidget(linha('linhaV'))
            corpo.addLayout(direita, 1)
            rodape = QHBoxLayout()
            rodape.setSpacing(8)
            rodape.addWidget(self.erro, 1)
            rodape.addWidget(cancelar)
            rodape.addWidget(self.criar_)
            v = QVBoxLayout(integrar(self, icone_=str(ASSETS / f'{app}.svg')))
            v.setContentsMargins(16, 16, 18, 14)
            v.setSpacing(0)
            v.addLayout(corpo, 1)
            v.addSpacing(12)
            v.addWidget(linha('linhaH'))
            v.addSpacing(12)
            v.addLayout(rodape)
            self.nome.textChanged.connect(self.avaliar)
            self.local.textChanged.connect(self.avaliar)
            self.avaliar()

        def escolhido(self, seg):
            return next(t for t, b in seg.botoes.items() if b.isChecked()) if seg else None

        def descrever(self, *_):
            if self.sistema:
                avisar(self.sobre_sistema, SISTEMAS_JAVA[self.escolhido(self.sistema)])
            if self.inicio:
                avisar(self.sobre_inicio, f'Starts with {conteudo_modelo(self.app, self.escolhido(self.inicio))}.')
            if self.exemplo:
                avisar(self.sobre_exemplo, f'Adds {conteudo_modelo(self.app, self.modelos_[0])} that prints a greeting.'
                       if self.exemplo.isChecked() else 'Starts with an empty src folder.')

        def modelo(self):
            if self.tipos.currentItem().text() == 'Empty Project':
                return 'Empty Project'
            if self.inicio:
                return next(t for t, b in self.inicio.botoes.items() if b.isChecked())
            return self.modelos_[0] if self.exemplo.isChecked() else 'Empty Project'

        def avaliar(self, *_):
            for w in self.extras:
                w.setVisible(self.tipos.currentItem().text() != 'Empty Project')
            if self.tipos.currentItem().text() != 'Empty Project':
                self.descrever()
            nome, local = self.nome.text().strip(), self.local.text().strip()
            valido = bool(re.fullmatch(r'[\w .-]+', nome)) and nome not in ('.', '..')
            alvo = Path(local).expanduser() / nome
            avisar(self.sobre_nome, '' if valido else 'Use letters, numbers, spaces, dots, dashes or underscores.', not valido)
            if valido and alvo.exists():
                avisar(self.existe, f'{curto(alvo)} already exists. Open it from the project list.', True)
            else:
                avisar(self.existe, f'Creates {curto(alvo)}' if valido and local else '')
            self.criar_.setEnabled(valido and bool(local) and not alvo.exists())

        def escolher(self):
            d = QFileDialog.getExistingDirectory(self, 'Location', str(Path(self.local.text()).expanduser()))
            if d:
                self.local.setText(curto(d))

        def criar(self):
            self.avaliar()
            if not self.criar_.isEnabled():
                return
            try:
                self.projeto = criar_projeto(self.app, self.modelo(), self.nome.text().strip(),
                                             Path(self.local.text().strip()).expanduser(), self.git.isChecked(),
                                             None if self.tipos.currentItem().text() == 'Empty Project' else self.escolhido(self.sistema))
                self.accept()
            except (OSError, subprocess.CalledProcessError) as e:
                avisar(self.erro, f'Could not create the project: {str(e)[:70]}', True)

    def erro_git(texto):
        """git's last words, said the way a person can act on them."""
        t = texto.lower()
        if 'could not read username' in t or 'authentication' in t or 'permission denied' in t:
            return 'This repository needs a sign-in. Clone private ones from the editor, which can ask for it.'
        if 'not found' in t or 'does not appear to be a git repository' in t or 'does not exist' in t:
            return 'No repository at this address. Check it and try again.'
        if 'could not resolve host' in t or 'unable to access' in t or 'timed out' in t:
            return 'Could not reach the server. Check the connection.'
        linhas_ = [l for l in texto.strip().splitlines() if l.strip()]
        return (linhas_[-1] if linhas_ else 'The clone failed.')[:110]

    def endereco_git(url):
        """True for what git clone can take: web, ssh and scp-like addresses, or a local folder."""
        url = url.strip()
        return bool(re.fullmatch(r'(https?|ssh|git|file)://\S+', url) or re.fullmatch(r'[\w.-]+@[\w.-]+:\S+', url)
                    or (url and Path(url).expanduser().is_dir()))

    class Clonar(Dialogo):
        def __init__(self, pai, app):
            super().__init__(pai)
            self.setWindowTitle('Clone Repository')
            self.setFixedWidth(560)
            self.pasta = None
            self.criada = False
            self.proc = QProcess(self)
            self.proc.setProcessChannelMode(QProcess.MergedChannels)
            self.saida = ''
            self.url = QLineEdit()
            self.url.setPlaceholderText('https://github.com/user/project.git')
            self.sobre_url = nota()
            self.base = QLineEdit(curto(CLONES))
            pasta = QPushButton('Browse')
            pasta.clicked.connect(self.escolher)
            fila = QHBoxLayout()
            fila.setSpacing(6)
            fila.addWidget(self.base, 1)
            fila.addWidget(pasta)
            self.sobre_destino = nota()
            self.etapa = rotulo('', 'mudo')
            self.barra = QProgressBar()
            self.barra.setTextVisible(False)
            self.barra.setFixedHeight(3)
            self.progresso = QWidget()
            p = QVBoxLayout(self.progresso)
            p.setContentsMargins(0, 0, 0, 0)
            p.setSpacing(6)
            p.addWidget(self.etapa)
            p.addWidget(self.barra)
            self.progresso.hide()
            self.erro = nota()
            self.botao = QPushButton('Clone')
            self.botao.setObjectName('azul')
            self.botao.setDefault(True)
            self.botao.clicked.connect(self.clonar)
            self.cancelar_ = QPushButton('Cancel')
            self.cancelar_.clicked.connect(self.cancelar)
            rodape = QHBoxLayout()
            rodape.setSpacing(8)
            rodape.addWidget(self.erro, 1)
            rodape.addWidget(self.cancelar_)
            rodape.addWidget(self.botao)
            v = QVBoxLayout(integrar(self, icone_=str(ASSETS / f'{app}.svg')))
            v.setContentsMargins(22, 18, 22, 16)
            v.setSpacing(14)
            grade = QGridLayout()
            grade.setHorizontalSpacing(14)
            grade.setVerticalSpacing(8)
            grade.setColumnMinimumWidth(0, 70)
            grade.addWidget(rotulo('URL'), 0, 0)
            grade.addWidget(self.url, 0, 1)
            grade.addWidget(self.sobre_url, 1, 1)
            grade.addWidget(rotulo('Directory'), 2, 0)
            grade.addLayout(fila, 2, 1)
            grade.addWidget(self.sobre_destino, 3, 1)
            v.addLayout(grade)
            v.addWidget(self.progresso)
            v.addWidget(linha('linhaH'))
            v.addLayout(rodape)
            self.url.textChanged.connect(self.avaliar)
            self.base.textChanged.connect(self.avaliar)
            self.proc.readyRead.connect(self.ler)
            self.proc.finished.connect(self.terminou)
            self.avaliar()
            if not shutil.which('git'):
                avisar(self.erro, 'Git was not found on this computer.', True)
                self.botao.setEnabled(False)

        def destino(self):
            return Path(self.base.text().strip()).expanduser() / nome_do_repo(self.url.text().strip())

        def avaliar(self):
            url = self.url.text().strip()
            ok = endereco_git(url)
            if not url:
                avisar(self.sobre_url, 'From GitHub, GitLab or any Git server.')
            else:
                avisar(self.sobre_url, '' if ok else 'Use an https://, ssh:// or git@ address.', not ok)
            alvo = self.destino()
            livre = ok and not alvo.exists()
            if ok and alvo.exists():
                avisar(self.sobre_destino, f'{curto(alvo)} already exists. Pick another folder.', True)
            else:
                avisar(self.sobre_destino, f'Clones into {curto(alvo)}' if ok else '')
            self.botao.setEnabled(livre and bool(shutil.which('git')) and self.proc.state() == QProcess.NotRunning)

        def escolher(self):
            d = QFileDialog.getExistingDirectory(self, 'Clone into', str(Path(self.base.text()).expanduser()))
            if d:
                self.base.setText(curto(d))

        def clonar(self):
            self.avaliar()
            if not self.botao.isEnabled():
                return
            alvo = self.destino()
            alvo.parent.mkdir(parents=True, exist_ok=True)
            amb = QProcessEnvironment.systemEnvironment()
            amb.insert('GIT_TERMINAL_PROMPT', '0')
            self.proc.setProcessEnvironment(amb)
            self.saida = ''
            avisar(self.erro, '')
            self.etapa.setText('Connecting')
            self.barra.setRange(0, 0)
            self.progresso.show()
            for w in (self.url, self.base, self.botao):
                w.setEnabled(False)
            self.criada = True
            self.proc.start('git', ['clone', '--progress', '--', self.url.text().strip(), str(alvo)])

        def ler(self):
            texto = bytes(self.proc.readAll()).decode(errors='replace')
            self.saida += texto
            for parte in reversed(re.split(r'[\r\n]+', texto)):
                m = re.match(r'(?:remote: )?([A-Za-z ]+):\s+(\d+)%', parte.strip())
                if m:
                    self.etapa.setText(f'{m.group(1).strip()} · {m.group(2)}%')
                    self.barra.setRange(0, 100)
                    self.barra.setValue(int(m.group(2)))
                    break

        def terminou(self, codigo, _estado):
            self.ler()
            for w in (self.url, self.base):
                w.setEnabled(True)
            if codigo == 0:
                self.pasta = str(self.destino())
                self.accept()
                return
            self.progresso.hide()
            self.apagar_parcial()
            avisar(self.erro, erro_git(self.saida), True)
            self.avaliar()

        def apagar_parcial(self):
            if self.criada and self.destino().exists():
                shutil.rmtree(self.destino(), ignore_errors=True)
            self.criada = False

        def cancelar(self):
            if self.proc.state() != QProcess.NotRunning:
                self.proc.finished.disconnect(self.terminou)
                self.proc.kill()
                self.proc.waitForFinished(3000)
                self.apagar_parcial()
            self.reject()

    class Caixa(QWidget):
        """Small shipping container in the profile's color, marked with its language."""

        def __init__(self, app):
            super().__init__()
            self.app = app
            self.cor = QColor(aplicativos()[app].get('accent', AZUL))
            self.setFixedSize(46, 30)

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.fillRect(self.rect(), self.cor)
            for x in (38, 41):  # the door's locking bars
                p.fillRect(QRectF(x, 0, 1.5, 30), QColor(0, 0, 0, 70))
            canto = QColor(0, 0, 0, 105)
            for x, y in ((0, 0), (41, 0), (0, 26), (41, 26)):
                p.fillRect(QRectF(x, y, 5, 4), canto)
            p.setPen(QPen(QColor('#14161A'), 2, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin))
            p.setBrush(Qt.NoBrush)
            marca_ = QPainterPath()
            if self.app == 'java':
                for x in (10, 18, 26):
                    marca_.moveTo(x, 23)
                    marca_.cubicTo(x - 3, 19, x + 3, 15, x, 7)
            elif self.app == 'web':
                marca_.moveTo(13, 9)
                marca_.lineTo(7, 15)
                marca_.lineTo(13, 21)
                marca_.moveTo(25, 9)
                marca_.lineTo(31, 15)
                marca_.lineTo(25, 21)
                marca_.moveTo(22, 7)
                marca_.lineTo(16, 23)
            else:
                marca_.moveTo(9, 9)
                marca_.lineTo(15, 15)
                marca_.lineTo(9, 21)
                marca_.moveTo(18, 22)
                marca_.lineTo(29, 22)
            p.drawPath(marca_)

    class LinhaProjeto(QWidget):
        """Project row: a small container carries the profile's color and language."""

        def __init__(self, caminho, app, geral):
            super().__init__()
            self.setAttribute(Qt.WA_TransparentForMouseEvents)
            h = QHBoxLayout(self)
            h.setContentsMargins(4, 5, 12, 5)
            h.setSpacing(12)
            t = QVBoxLayout()
            t.setSpacing(1)
            t.addWidget(rotulo(caminho.name, 'forte'))
            t.addWidget(rotulo(curto(caminho), 'mudo'))
            h.addWidget(Caixa(app), 0, Qt.AlignVCenter)
            h.addLayout(t, 1)
            lado = QVBoxLayout()
            lado.setSpacing(2)
            lado.addStretch(1)
            for texto in (tipo_rotulo(caminho), quando(caminho)):
                if texto:
                    lado.addWidget(rotulo(texto, 'mudo'), 0, Qt.AlignRight)
            lado.addStretch(1)
            h.addLayout(lado)

    class ListaProjetos(QListWidget):
        """Projetos recentes; `app` nulo mostra os de todos os apps."""

        def __init__(self, app=None):
            super().__init__()
            self.app = app
            self.texto = ''
            self.so = None
            self.setSpacing(1)
            self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
            self.itemClicked.connect(self.ativar)
            self.setContextMenuPolicy(Qt.CustomContextMenu)
            self.customContextMenuRequested.connect(self.menu)
            self.recarregar()

        def recarregar(self):
            self.clear()
            self.total = 0
            for titulo, projetos in secoes(self.app):
                if titulo:
                    cabeca = QListWidgetItem(self)
                    cabeca.setFlags(Qt.NoItemFlags)
                    cabeca.setSizeHint(QSize(0, 30))
                    r = rotulo(titulo, 'secao')
                    r.setContentsMargins(4, 8, 0, 0)
                    self.setItemWidget(cabeca, r)
                for caminho, app in projetos:
                    item = QListWidgetItem(self)
                    item.setData(Qt.UserRole, (app, str(caminho)))
                    item.setSizeHint(QSize(0, 50))
                    self.setItemWidget(item, LinhaProjeto(caminho, app, self.app is None))
                    self.total += 1

        def ativar(self, item):
            if item.data(Qt.UserRole):
                abrir(*item.data(Qt.UserRole))

        def filtrar(self, texto=None):
            self.texto = self.texto if texto is None else texto
            for i in range(self.count()):
                item = self.item(i)
                dados = item.data(Qt.UserRole)
                fora = bool(self.texto) and (not dados or self.texto.lower() not in dados[1].lower())
                item.setHidden(fora or bool(self.so and (not dados or dados[0] != self.so)))

        def so_app(self, app):
            self.so = app
            self.filtrar()

        def menu(self, pos):
            item = self.itemAt(pos)
            if not item or not item.data(Qt.UserRole):
                return
            app, alvo = item.data(Qt.UserRole)
            m = QMenu(self)
            m.addAction('Open', lambda: abrir(app, alvo))
            m.addAction('Show in File Manager', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(alvo)))
            m.addAction('Copy Path', lambda: QGuiApplication.clipboard().setText(alvo))
            m.addSeparator()
            m.addAction('Remove from Recent Projects', lambda: (ocultar_recente(alvo), self.recarregar()))
            m.exec(self.mapToGlobal(pos))

    def busca_linha():
        b = QLineEdit()
        b.setObjectName('busca')
        b.setPlaceholderText('Search projects')
        b.addAction(QIcon(str(ASSETS / 'busca.svg')), QLineEdit.LeadingPosition)
        return b

    class Projetos(QWidget):
        def __init__(self, app):
            super().__init__()
            self.setObjectName('pagina')
            self.app = app
            self.lista = ListaProjetos(app)
            self.pilha = QStackedWidget()
            self.pilha.addWidget(self.pagina_lista())
            self.pilha.addWidget(self.pagina_vazia())
            self.pilha.setCurrentIndex(0 if self.lista.total else 1)
            v = QVBoxLayout(self)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(self.pilha)

        def botoes(self):
            fila = QHBoxLayout()
            fila.setSpacing(8)
            for texto, acao in (('New Project', self.novo), ('Open', self.pasta), ('Clone Repository', self.clonar)):
                b = QPushButton(texto)
                b.clicked.connect(acao)
                if texto == 'New Project':
                    b.setObjectName('azul')
                fila.addWidget(b)
            return fila

        def dica(self):
            r = rotulo('Drop a folder here to open it', 'mudo')
            r.setAlignment(Qt.AlignCenter)
            r.setStyleSheet('border:1px dashed #4A4F56;padding:8px;')
            return r

        def pagina_lista(self):
            p = QWidget()
            v = QVBoxLayout(p)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            topo = QHBoxLayout()
            topo.setContentsMargins(14, 8, 14, 8)
            busca = busca_linha()
            busca.textChanged.connect(self.lista.filtrar)
            topo.addWidget(busca, 1)
            topo.addLayout(self.botoes())
            v.addLayout(topo)
            v.addWidget(linha('linhaH'))
            caixa = QVBoxLayout()
            caixa.setContentsMargins(16, 6, 16, 14)
            caixa.setSpacing(10)
            caixa.addWidget(self.lista, 1)
            caixa.addWidget(self.dica())
            v.addLayout(caixa, 1)
            return p

        def pagina_vazia(self):
            p = QWidget()
            v = QVBoxLayout(p)
            v.setContentsMargins(16, 6, 16, 14)
            v.addStretch(1)
            info = aplicativos()[self.app]
            for w in (rotulo('No projects yet', 'grande'), rotulo(info['description'], 'mudo'),
                      rotulo('Create a project, or open one from disk or version control.', 'mudo')):
                w.setAlignment(Qt.AlignCenter)
                v.addWidget(w)
            v.addSpacing(14)
            fila = QHBoxLayout()
            fila.addStretch(1)
            fila.addLayout(self.botoes())
            fila.addStretch(1)
            v.addLayout(fila)
            v.addStretch(2)
            v.addWidget(self.dica())
            return p

        def novo(self):
            d = NovoProjeto(self, self.app)
            if d.exec():
                abrir(self.app, d.projeto)

        def pasta(self):
            inicio = pasta_projetos(self.app)
            pasta = QFileDialog.getExistingDirectory(self, 'Open', str(inicio if inicio.is_dir() else CASA))
            if pasta:
                abrir(self.app, pasta)

        def clonar(self):
            d = Clonar(self, self.app)
            if d.exec():
                abrir(self.app, d.pasta)

    class Degrau(QPushButton):
        """One line of the load mark: the chosen line is thicker, in the app's color."""

        def __init__(self, texto, cor):
            super().__init__(texto)
            self.cor = QColor(cor)
            self.setCheckable(True)
            self.setFixedSize(130, 19)
            self.setCursor(Qt.PointingHandCursor)

        def paintEvent(self, _):
            p = QPainter(self)
            marcado = self.isChecked()
            comprimento, grossura = (70, 5) if marcado else (42, 3)
            p.fillRect(QRectF(0, (self.height() - grossura) / 2, comprimento, grossura), self.cor if marcado else QColor('#5A5F66'))
            p.setPen(QColor('#FFFFFF' if marcado else '#8F939A'))
            p.drawText(QRectF(comprimento + 7, 0, 60, self.height()), Qt.AlignVCenter, self.text())

    class MarcaPlimsoll(QWidget):
        """The ring and bar painted on a ship's hull, beside the memory lines."""

        def __init__(self):
            super().__init__()
            self.setFixedSize(56, 56)

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor('#EDE6D3'), 2))
            p.drawEllipse(QRectF(8, 8, 40, 40))
            p.drawLine(0, 28, 56, 28)

    class Personalizar(QWidget):
        def __init__(self, app):
            super().__init__()
            self.setObjectName('pagina')
            self.app = app
            info = aplicativos()[app]
            externo = QVBoxLayout(self)
            externo.setContentsMargins(0, 0, 0, 0)
            externo.setSpacing(0)
            aviso = QFrame()
            aviso.setObjectName('faixa')
            a = QHBoxLayout(aviso)
            a.setContentsMargins(20, 7, 20, 7)
            a.addWidget(rotulo(f"Changes apply the next time {info['title']} opens.", 'mudo'))
            externo.addWidget(aviso)
            externo.addWidget(linha('linhaH'))
            rolagem = QScrollArea()
            rolagem.setWidgetResizable(True)
            miolo = QWidget()
            miolo.setObjectName('pagina')
            colunas = QHBoxLayout(miolo)
            colunas.setContentsMargins(20, 14, 20, 14)
            colunas.setSpacing(26)
            esq, dir_ = QVBoxLayout(), QVBoxLayout()
            esq.setSpacing(6)
            dir_.setSpacing(6)
            colunas.addLayout(esq, 1)
            colunas.addLayout(dir_, 1)
            esq.addWidget(rotulo('Appearance', 'secao'))
            self.tema = Combo()
            self.tema.setFixedWidth(170)
            self.tema.addItems(temas(app))
            atual = ajuste(app, 'workbench.colorTheme')
            if atual:
                if self.tema.findText(atual) < 0:
                    self.tema.addItem(atual)
                self.tema.setCurrentText(atual)
            self.tema.currentTextChanged.connect(lambda t: gravar_ajuste(app, 'workbench.colorTheme', t))
            esq.addLayout(self.campo('Theme', self.tema))
            self.fonte = Combo()
            self.fonte.setFixedWidth(64)
            self.fonte.addItems(['9', '10', '11', '12', '13', '14', '15', '16', '18', '20', '24', '28'])
            self.fonte.setCurrentText(str(ajuste(app, 'editor.fontSize') or 13))
            self.fonte.currentTextChanged.connect(lambda n: gravar_ajuste(app, 'editor.fontSize', int(n)))
            esq.addLayout(self.campo('Editor font', self.fonte))
            self.caixa('Animations', 'animations', esq)
            if info.get('base'):
                c = self.caixa('Tree icons and watermark', 'visual', esq)
                c.setToolTip('Uses a local debugging port.')
                if info.get('keymap'):
                    esq.addSpacing(8)
                    esq.addWidget(rotulo('Keymap', 'secao'))
                    nomes = {'intellij': 'IntelliJ', 'vscode': 'VS Code'}
                    self.teclas = segmento(nomes.values(), nomes[keymap_de(app)], self.mudar_keymap)
                    esq.addLayout(self.campo('Shortcuts', self.teclas))
                    esq.addWidget(rotulo('Changes at once, even with the editor open.', 'mudo'))
                self.pacotes(esq)
                esq.addSpacing(8)
                esq.addWidget(rotulo('Wallpaper', 'secao'))
                self.imagem = rotulo('', 'mudo')
                esq.addLayout(self.campo('Image', self.imagem))
                fila = QHBoxLayout()
                fila.setSpacing(8)
                escolher = QPushButton('Choose')
                escolher.clicked.connect(self.escolher_fundo)
                self.tirar = QPushButton('Remove')
                self.tirar.clicked.connect(self.tirar_fundo)
                fila.addWidget(escolher)
                fila.addWidget(self.tirar)
                fila.addStretch(1)
                esq.addLayout(fila)
                self.forca = QSlider(Qt.Horizontal)
                self.forca.setFixedWidth(150)
                self.forca.setRange(3, 40)
                self.forca.setValue(round(lembrar_fundo(app) * 100))
                self.forca.valueChanged.connect(lambda n: gravar_fundo_forca(app, n / 100))
                esq.addLayout(self.campo('Strength', self.forca))
                self.ver_fundo()
            else:
                self.pacotes(esq)
            dir_.addWidget(rotulo('Projects', 'secao'))
            fila = QHBoxLayout()
            fila.setSpacing(8)
            self.pasta = QLineEdit(curto(pasta_projetos(app)))
            self.pasta.setToolTip(f"Folder where new {info['title']} projects are created")
            self.pasta.editingFinished.connect(lambda: self.mudar_pasta(self.pasta.text()))
            procurar = QPushButton('Browse')
            procurar.clicked.connect(self.procurar_pasta)
            fila.addWidget(self.pasta, 1)
            fila.addWidget(procurar)
            dir_.addLayout(fila)
            dir_.addWidget(rotulo('New projects start in this folder.', 'mudo'))
            dir_.addSpacing(8)
            if info.get('memory'):
                dir_.addWidget(rotulo('Memory limit', 'secao'))
                fila = QHBoxLayout()
                fila.setSpacing(12)
                fila.addWidget(MarcaPlimsoll())
                degraus = QVBoxLayout()
                degraus.setSpacing(1)
                grupo = QButtonGroup(self)
                for m in reversed(MEMORIAS):
                    b = Degrau(m, info.get('accent', AZUL))
                    b.setChecked(m == opcao(app, 'memory'))
                    b.clicked.connect(lambda _=False, x=m: gravar_opcao(app, 'memory', x))
                    grupo.addButton(b)
                    degraus.addWidget(b)
                fila.addLayout(degraus)
                fila.addStretch(1)
                dir_.addLayout(fila)
                dir_.addWidget(rotulo('The Java server stops at this line.', 'mudo'))
                dir_.addSpacing(8)
            dir_.addWidget(rotulo('AI', 'secao'))
            self.caixa('Enable AI features', 'ai', dir_)
            dir_.addSpacing(8)
            dir_.addWidget(rotulo('Import', 'secao'))
            d = rotulo('Copies settings, shortcuts and snippets. The original stays untouched.', 'mudo')
            d.setWordWrap(True)
            dir_.addWidget(d)
            fila = QHBoxLayout()
            fila.setSpacing(8)
            achou = False
            for nome_, origem in origens_importacao():
                b = QPushButton(f'From {nome_}')
                b.setEnabled(origem.is_dir())
                achou = achou or origem.is_dir()
                b.clicked.connect(lambda _=False, o=origem, n=nome_: self.importar(o, n))
                fila.addWidget(b)
            fila.addStretch(1)
            dir_.addLayout(fila)
            if not achou:
                dir_.addWidget(rotulo('No installation found.', 'mudo'))
            dir_.addSpacing(8)
            dir_.addWidget(rotulo('More', 'secao'))
            dir_.addWidget(link('All settings…', lambda: abrir(app, comando_='workbench.action.openSettings')))
            dir_.addWidget(link('Keyboard shortcuts…', lambda: abrir(app, comando_='workbench.action.openGlobalKeybindings')))
            esq.addStretch(1)
            dir_.addStretch(1)
            rolagem.setWidget(miolo)
            externo.addWidget(rolagem, 1)

        def campo(self, texto, controle):
            fila = QHBoxLayout()
            fila.addWidget(QLabel(texto))
            fila.addStretch(1)
            fila.addWidget(controle)
            return fila

        def pacotes(self, layout):
            """The icon pack in use is shown by its own name, even when it is not one of ours."""
            layout.addSpacing(8)
            layout.addWidget(rotulo('File icons', 'secao'))
            opcoes_ = pacotes_icones(self.app)
            tema_ = ajuste(self.app, 'workbench.iconTheme')
            pacote = next((n for n, t in opcoes_.items() if t == tema_), None)
            self.icones = segmento(opcoes_, pacote, lambda n: gravar_ajuste(self.app, 'workbench.iconTheme', opcoes_[n]))
            layout.addLayout(self.campo('Pack', self.icones))

        def mudar_pasta(self, texto):
            """An empty field goes back to the usual folder."""
            alvo = Path(texto.strip()).expanduser() if texto.strip() else PROJETOS
            if not alvo.is_absolute():
                alvo = CASA / alvo
            try:
                alvo.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                QMessageBox.warning(self, 'Project folder', f'Could not use this folder: {e}')
                alvo = pasta_projetos(self.app)
            gravar_opcao(self.app, 'folder', '' if alvo == PROJETOS else str(alvo))
            self.pasta.setText(curto(alvo))

        def procurar_pasta(self):
            d = QFileDialog.getExistingDirectory(self, 'Project folder', str(pasta_projetos(self.app)))
            if d:
                self.mudar_pasta(d)

        def mudar_keymap(self, texto):
            if not aplicar_keymap(self.app, 'intellij' if texto == 'IntelliJ' else 'vscode'):
                QMessageBox.warning(self, 'Keymap', 'Could not read your keybindings.json. Fix it and try again.')
                self.teclas.botoes['IntelliJ' if keymap_de(self.app) == 'intellij' else 'VS Code'].setChecked(True)

        def ver_fundo(self):
            tem = (ferramentas(self.app) / 'fundo.jpg').exists()
            self.imagem.setText('Set' if tem else 'None')
            self.tirar.setEnabled(tem)

        def tirar_fundo(self):
            (ferramentas(self.app) / 'fundo.jpg').unlink(missing_ok=True)
            self.ver_fundo()

        def caixa(self, texto, chave, layout):
            c = QCheckBox(texto)
            c.setChecked(opcao(self.app, chave))
            c.toggled.connect(lambda n: gravar_opcao(self.app, chave, n))
            layout.addWidget(c)
            return c

        def escolher_fundo(self):
            d = EscolherImagem(self, self.app)
            arquivo = d.arquivo if d.exec() else ''
            if arquivo and not gravar_fundo(arquivo, ferramentas(self.app)):
                QMessageBox.warning(self, 'Background image', 'Could not read this image.')
            self.ver_fundo()

        def importar(self, origem, nome_):
            importar(self.app, origem)
            QMessageBox.information(self, 'Import', f'{nome_} settings copied to {nome_app(self.app)}.')

    IMAGENS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif')

    def miniatura(arquivo, largura, altura):
        """A small copy of the image, read at that size so a folder of photos opens fast."""
        leitor = QImageReader(str(arquivo))
        leitor.setAutoTransform(True)
        tamanho = leitor.size()
        if tamanho.isValid():
            tamanho.scale(largura, altura, Qt.KeepAspectRatio)
            leitor.setScaledSize(tamanho)
        imagem = leitor.read()
        if imagem.isNull():
            return None
        quadro = QPixmap(largura, altura)
        quadro.fill(QColor('#101214'))
        p = QPainter(quadro)
        p.drawImage((largura - imagem.width()) // 2, (altura - imagem.height()) // 2, imagem)
        p.end()
        return QIcon(quadro)

    class EscolherImagem(Dialogo):
        """Wallpaper picker with previews; the same on Linux and Windows."""

        LARGURA, ALTURA = 156, 98

        def __init__(self, pai, app):
            super().__init__(pai)
            self.setWindowTitle('Choose Wallpaper')
            self.resize(780, 540)
            self.arquivo = ''
            self.fila = []
            imagens = Path(QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or CASA / 'Pictures')
            self.lugares = {'Pictures': imagens, 'Desktop': area_de_trabalho(),
                            'Downloads': Path(QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or CASA / 'Downloads'),
                            'Home': CASA}
            self.locais = QListWidget()
            self.locais.setObjectName('modelos')
            self.locais.setFixedWidth(150)
            for nome, caminho in self.lugares.items():
                item = QListWidgetItem(nome)
                item.setData(Qt.UserRole, str(caminho))
                item.setSizeHint(QSize(140, 32))
                self.locais.addItem(item)
            self.locais.itemClicked.connect(lambda i: self.abrir_pasta(Path(i.data(Qt.UserRole))))
            outra = link('Other folder…', self.outra)
            self.subir = QPushButton('Up')
            self.subir.clicked.connect(lambda: self.abrir_pasta(self.pasta.parent))
            self.onde = rotulo('', 'mudo')
            self.grade = QListWidget()
            self.grade.setObjectName('grade')
            self.grade.setViewMode(QListWidget.IconMode)
            self.grade.setIconSize(QSize(self.LARGURA, self.ALTURA))
            self.grade.setGridSize(QSize(self.LARGURA + 16, self.ALTURA + 34))
            self.grade.setResizeMode(QListWidget.Adjust)
            self.grade.setMovement(QListWidget.Static)
            self.grade.setUniformItemSizes(True)
            self.grade.setWordWrap(False)
            self.grade.setTextElideMode(Qt.ElideMiddle)
            self.grade.itemSelectionChanged.connect(self.marcar)
            self.grade.itemActivated.connect(self.ativar)
            self.vazio = rotulo('No images in this folder.', 'mudo')
            self.vazio.setAlignment(Qt.AlignCenter)
            self.escolhido = rotulo('', 'mudo')
            self.usar = QPushButton('Use Image')
            self.usar.setObjectName('azul')
            self.usar.setDefault(True)
            self.usar.setEnabled(False)
            self.usar.clicked.connect(self.accept)
            cancelar = QPushButton('Cancel')
            cancelar.clicked.connect(self.reject)
            esquerda = QVBoxLayout()
            esquerda.setContentsMargins(0, 0, 0, 0)
            esquerda.setSpacing(6)
            esquerda.addWidget(rotulo('Places', 'secao'))
            self.locais.setFixedHeight(self.locais.count() * 32 + 4)
            esquerda.addWidget(self.locais)
            esquerda.addSpacing(6)
            esquerda.addWidget(outra)
            esquerda.addStretch(1)
            topo = QHBoxLayout()
            topo.setSpacing(8)
            topo.addWidget(self.subir)
            topo.addWidget(self.onde, 1)
            direita = QVBoxLayout()
            direita.setContentsMargins(0, 0, 0, 0)
            direita.setSpacing(8)
            direita.addLayout(topo)
            direita.addWidget(self.grade, 1)
            direita.addWidget(self.vazio, 1)
            corpo = QHBoxLayout()
            corpo.setSpacing(16)
            corpo.addLayout(esquerda)
            corpo.addWidget(linha('linhaV'))
            corpo.addLayout(direita, 1)
            rodape = QHBoxLayout()
            rodape.setSpacing(8)
            rodape.addWidget(self.escolhido, 1)
            rodape.addWidget(cancelar)
            rodape.addWidget(self.usar)
            v = QVBoxLayout(integrar(self, True, icone_=str(ASSETS / f'{app}.svg')))
            v.setContentsMargins(22, 18, 22, 16)
            v.setSpacing(14)
            v.addLayout(corpo, 1)
            v.addWidget(linha('linhaH'))
            v.addLayout(rodape)
            self.icone_pasta = self.desenhar_pasta()
            self.relogio = QTimer(self)
            self.relogio.timeout.connect(self.carregar)
            self.abrir_pasta(imagens if imagens.is_dir() else CASA)

        def abrir_pasta(self, pasta):
            self.pasta = Path(pasta)
            self.grade.clear()
            self.fila = []
            self.onde.setText(curto(self.pasta))
            self.subir.setEnabled(self.pasta.parent != self.pasta)
            for i in range(self.locais.count()):
                self.locais.item(i).setSelected(Path(self.locais.item(i).data(Qt.UserRole)) == self.pasta)
            try:
                filhos = sorted(self.pasta.iterdir(), key=lambda f: (not f.is_dir(), f.name.lower()))
            except OSError:
                filhos = []
            vazio_ = QPixmap(self.LARGURA, self.ALTURA)
            vazio_.fill(QColor('#101214'))
            for f in filhos:
                if f.name.startswith('.'):
                    continue
                if f.is_dir():
                    item = QListWidgetItem(self.icone_pasta, f.name)
                elif f.suffix.lower() in IMAGENS:
                    item = QListWidgetItem(QIcon(vazio_), f.name)
                    self.fila.append(item)
                else:
                    continue
                item.setData(Qt.UserRole, str(f))
                item.setToolTip(f.name)
                self.grade.addItem(item)
            tem = self.grade.count() > 0
            self.grade.setVisible(tem)
            self.vazio.setVisible(not tem)
            self.marcar()
            self.relogio.start(0)

        def desenhar_pasta(self):
            figura = QPixmap(self.LARGURA, self.ALTURA)
            figura.fill(QColor('#1A1C1F'))
            p = QPainter(figura)
            p.setPen(QPen(QColor('#8F939A'), 1.5))
            x, y = self.LARGURA // 2 - 22, self.ALTURA // 2 - 15
            p.drawPolyline([QPointF(x, y + 30), QPointF(x, y), QPointF(x + 15, y), QPointF(x + 19, y + 5),
                            QPointF(x + 44, y + 5), QPointF(x + 44, y + 30), QPointF(x, y + 30)])
            p.end()
            return QIcon(figura)

        def carregar(self):
            """A few previews per turn, so the window keeps answering while a big folder loads."""
            for _ in range(4):
                if not self.fila:
                    self.relogio.stop()
                    return
                item = self.fila.pop(0)
                figura = miniatura(item.data(Qt.UserRole), self.LARGURA, self.ALTURA)
                if figura:
                    item.setIcon(figura)
                else:
                    item.setText(f'{item.text()} (unreadable)')

        def marcar(self):
            item = self.grade.currentItem() if self.grade.selectedItems() else None
            caminho = Path(item.data(Qt.UserRole)) if item else None
            imagem = bool(caminho) and caminho.suffix.lower() in IMAGENS
            self.arquivo = str(caminho) if imagem else ''
            self.escolhido.setText(caminho.name if imagem else '')
            self.usar.setEnabled(imagem)

        def ativar(self, item):
            caminho = Path(item.data(Qt.UserRole))
            if caminho.is_dir():
                self.abrir_pasta(caminho)
            else:
                self.accept()

        def outra(self):
            d = QFileDialog.getExistingDirectory(self, 'Folder with images', str(self.pasta))
            if d:
                self.abrir_pasta(Path(d))

    class Plugins(QWidget):
        def __init__(self, app):
            super().__init__()
            self.setObjectName('pagina')
            self.app = app
            v = QVBoxLayout(self)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            topo = QHBoxLayout()
            topo.setContentsMargins(20, 12, 13, 12)
            busca = QLineEdit()
            busca.setObjectName('busca')
            busca.setPlaceholderText('Search installed plugins')
            busca.addAction(QIcon(str(ASSETS / 'busca.svg')), QLineEdit.LeadingPosition)
            topo.addWidget(busca, 1)
            loja = QPushButton('Marketplace')
            loja.clicked.connect(lambda: abrir(app, comando_='workbench.view.extensions'))
            topo.addWidget(loja)
            v.addLayout(topo)
            v.addWidget(linha('linhaH'))
            self.lista = QListWidget()
            self.lista.setSelectionMode(QListWidget.NoSelection)
            obrigatorias = aplicativos()[app].get('required', [])
            todos = plugins(app)
            opcionais = [x for x in todos if x[0] not in obrigatorias]
            fixos = [x for x in todos if x[0] in obrigatorias]
            for titulo, grupo_ in ((f'Optional · {len(opcionais)}', opcionais), (f'Required · {len(fixos)}', fixos)):
                if not grupo_:
                    continue
                cabeca = QListWidgetItem(self.lista)
                cabeca.setFlags(Qt.NoItemFlags)
                cabeca.setSizeHint(QSize(0, 30))
                r = rotulo(titulo, 'secao')
                r.setContentsMargins(20, 8, 0, 0)
                self.lista.setItemWidget(cabeca, r)
                for ident, nome, versao_, autor in grupo_:
                    item = QListWidgetItem(self.lista)
                    item.setData(Qt.UserRole, nome.lower())
                    item.setSizeHint(QSize(0, 32))
                    w = QWidget()
                    h = QHBoxLayout(w)
                    h.setContentsMargins(20, 0, 16, 0)
                    h.setSpacing(10)
                    h.addWidget(rotulo(nome, 'forte'))
                    h.addWidget(rotulo(f'{autor} · {versao_}', 'mudo'), 1)
                    if ident in obrigatorias:
                        trava = QLabel()
                        trava.setPixmap(QIcon(str(ASSETS / 'lock.svg')).pixmap(11, 11))
                        trava.setToolTip(f'{nome_app(app)} needs this plugin.')
                        h.addWidget(trava)
                        h.addWidget(rotulo('Required', 'mudo'))
                    else:
                        ligado = QCheckBox()
                        ligado.setToolTip(f'Enable {nome}')
                        ligado.setChecked(ident not in desligadas(app))
                        ligado.toggled.connect(lambda n, i=ident: alternar_extensao(app, i, n))
                        h.addWidget(ligado)
                    self.lista.setItemWidget(item, w)
            v.addWidget(self.lista, 1)
            busca.textChanged.connect(self.filtrar)

        def filtrar(self, texto):
            for i in range(self.lista.count()):
                item = self.lista.item(i)
                dado = item.data(Qt.UserRole)
                item.setHidden(bool(texto) and (dado is None or texto.lower() not in dado))

    class Aprender(QWidget):
        def __init__(self, app):
            super().__init__()
            self.setObjectName('pagina')
            self.app = app
            info = aplicativos()[app]
            h = QHBoxLayout(self)
            h.setContentsMargins(20, 14, 20, 14)
            h.setSpacing(26)
            esq = QVBoxLayout()
            esq.setSpacing(4)
            esq.addWidget(rotulo(f"Learn {info['title']}", 'secao'))
            for texto, url in info.get('learn', []):
                esq.addWidget(link(texto, lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u))))
                esq.addWidget(rotulo(url.split('/')[2], 'mudo'))
            esq.addStretch(1)
            h.addLayout(esq, 2)
            self.direita = QVBoxLayout()
            self.direita.setSpacing(0)
            h.addLayout(self.direita, 3)
            self.mostrar_teclas()

        def showEvent(self, _):
            self.mostrar_teclas()

        def mostrar_teclas(self):
            """Rebuilt on show, because the keymap can change in Customize."""
            while self.direita.count():
                filho = self.direita.takeAt(0)
                if filho.widget():
                    filho.widget().deleteLater()
                elif filho.layout():
                    pass
            if not aplicativos()[self.app].get('base'):
                self.direita.addWidget(rotulo('Keymap', 'secao'))
                r = rotulo('Standard keeps the editor defaults, so there is no keymap to learn here.', 'mudo')
                r.setWordWrap(True)
                self.direita.addWidget(r)
                self.direita.addStretch(1)
                return
            nome = 'IntelliJ' if keymap_de(self.app) == 'intellij' else 'VS Code'
            self.direita.addWidget(rotulo(f'Keymap: {nome}', 'secao'))
            self.direita.addSpacing(6)
            for acao, tecla in teclas_app(self.app):
                w = QWidget()
                fila = QHBoxLayout(w)
                fila.setContentsMargins(0, 4, 0, 4)
                fila.addWidget(QLabel(acao))
                fila.addStretch(1)
                fila.addWidget(etiqueta(tecla))
                self.direita.addWidget(w)
                self.direita.addWidget(linha('linhaH'))
            if aplicativos()[self.app].get('keymap'):
                self.direita.addSpacing(8)
                self.direita.addWidget(link('Change keymap', lambda: self.window().ir('Customize')))
            self.direita.addStretch(1)

    class Boasvindas(Raiz):
        """Tela de início de cada app, com o que é específico dele."""

        def __init__(self, app, painel=None):
            super().__init__()
            self.setObjectName('raiz')
            self.painel = painel
            self.app = app
            self.setWindowTitle(f"{marca()['hub']} · {aplicativos()[app]['title']} · Projects")
            self.setWindowIcon(QIcon(str(ASSETS / f'{app}.svg')))
            com_vidro(self)
            self.setStyleSheet(estilo(aplicativos()[app].get('accent', AZUL)))
            self.resize(820, 650)
            self.setAcceptDrops(True)
            self.paginas = Troca()
            self.abas = {}
            grupo = QButtonGroup(self)
            esquerda = QWidget()
            esquerda.setFixedWidth(200)
            e = QVBoxLayout(esquerda)
            e.setContentsMargins(0, 0, 0, 0)
            e.setSpacing(0)
            tipo, titulo_estado, _ = estado_app(app)
            topo = QWidget()
            topo.setFixedSize(200, 128)
            self.mar = Sea(app, 200, 128, tipo == 'run', 92, 4)
            self.mar.setParent(topo)
            nome = rotulo(aplicativos()[app]['title'], 'grande')
            nome.setParent(topo)
            nome.setGeometry(106, 30, 92, 28)
            nome.setStyleSheet('font-size:16px;')
            e.addWidget(topo)
            e.addWidget(linha('linhaH'))
            e.addSpacing(10)
            for titulo, pagina in (('Projects', Projetos(app)), ('Customize', Personalizar(app)),
                                   ('Plugins', Plugins(app)), ('Learn', Aprender(app))):
                b = QPushButton(titulo)
                b.setObjectName('aba')
                b.setCheckable(True)
                b.clicked.connect(lambda _=False, w=pagina, t=titulo: (self.paginas.ir(w), self.setWindowTitle(f"{marca()['hub']} · {aplicativos()[app]['title']} · {t}")))
                grupo.addButton(b)
                e.addWidget(b)
                self.abas[titulo] = b
                self.paginas.addWidget(pagina)
            self.abas['Projects'].setChecked(True)
            e.addStretch(1)
            estado = QHBoxLayout()
            estado.setContentsMargins(14, 0, 14, 4)
            estado.setSpacing(7)
            self.lampada = lampada(tipo)
            self.estado = rotulo(titulo_estado, 'forte')
            estado.addWidget(self.lampada)
            estado.addWidget(self.estado, 1)
            e.addLayout(estado)
            self.lampada.setVisible(bool(titulo_estado))
            self.estado.setVisible(bool(titulo_estado))
            r = rotulo(f"{marca()['name']} {versao()}\nEditor {versao_editor()}", 'mudo')
            r.setContentsMargins(14, 0, 14, 8)
            r.setStyleSheet('font-size:11px;')
            e.addWidget(r)
            voltar = QPushButton('‹ Cargo')
            voltar.setObjectName('volta')
            voltar.clicked.connect(self.voltar)
            e.addWidget(voltar)
            h = QHBoxLayout(integrar(self, True, icone_=str(ASSETS / f'{app}.svg')))
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(0)
            h.addWidget(esquerda)
            h.addWidget(linha('linhaV'))
            h.addWidget(self.paginas, 1)
            self.vigia = QTimer(self)
            self.vigia.timeout.connect(self.atualizar)
            self.vigia.start(2000)

        def atualizar(self):
            """Keeps the rail true: coming back from the editor, it may still be closing."""
            tipo, titulo, _ = estado_app(self.app)
            self.lampada.setStyleSheet(f'background:{LAMPADAS[tipo]};border-radius:4px;')
            self.lampada.setVisible(bool(titulo))
            self.estado.setText(titulo)
            self.estado.setVisible(bool(titulo))
            self.mar.moving = tipo == 'run'

        def ir(self, titulo):
            self.abas[titulo].click()

        def voltar(self):
            self.painel = self.painel or Painel()
            self.close()

        def closeEvent(self, evento):
            if self.painel and self.isVisible():
                surgir(self.painel)
            evento.accept()

        def dragEnterEvent(self, e):
            if e.mimeData().hasUrls():
                e.acceptProposedAction()

        def dropEvent(self, e):
            alvos = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if alvos:
                abrir(self.app, *alvos)

    class Ferramenta(QFrame):
        """One app in the Cargo: its boat on the water, its state and main action."""

        def __init__(self, app, painel):
            super().__init__()
            self.setObjectName('ferramenta')
            self.setCursor(Qt.PointingHandCursor)
            self.setFixedSize(400, 146)
            self.app = app
            self.painel = painel
            info = aplicativos()[app]
            self.mar = Sea(app, 400, 146, False, 132, 4)
            self.mar.setParent(self)
            coluna = QWidget(self)
            coluna.setGeometry(170, 18, 222, 100)
            t = QVBoxLayout(coluna)
            t.setContentsMargins(0, 0, 0, 0)
            t.setSpacing(5)
            t.addWidget(rotulo(info['title'], 'titulo'))
            self.linha_estado = QHBoxLayout()
            self.linha_estado.setSpacing(6)
            self.lampada = QLabel()
            self.estado = rotulo('', 'forte')
            self.detalhe = rotulo('', 'mudo')
            self.linha_estado.addWidget(self.lampada)
            self.linha_estado.addWidget(self.estado)
            self.linha_estado.addWidget(self.detalhe, 1)
            t.addLayout(self.linha_estado)
            acoes = QHBoxLayout()
            self.acao = QPushButton()
            self.acao.setCursor(Qt.ArrowCursor)
            self.acao.clicked.connect(self.agir)
            acoes.addWidget(self.acao)
            acoes.addStretch(1)
            self.mais = QToolButton()
            self.mais.setText('⋯')
            self.mais.setCursor(Qt.ArrowCursor)
            self.mais.setFixedSize(26, 26)
            self.mais.setStyleSheet('padding:0;')
            self.mais.setPopupMode(QToolButton.InstantPopup)
            m = QMenu(self.mais)
            m.addAction('Open', lambda: painel.boasvindas(app))
            m.addAction('Open Editor Directly', lambda: abrir(app))
            m.addAction('Settings', lambda: painel.boasvindas(app, 'Customize'))
            m.addAction('Plugins', lambda: painel.boasvindas(app, 'Plugins'))
            m.addSeparator()
            m.addAction('Create Desktop Shortcut', lambda: painel.atalho(app))
            m.addAction('Show Data Folder', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(DADOS / app))))
            self.mais.setMenu(m)
            acoes.addWidget(self.mais)
            t.addLayout(acoes)
            t.addStretch(1)
            self.atualizar()

        def atualizar(self):
            """Reads the app's state and project again; called while the Hub is open."""
            self.tipo, titulo, detalhe = estado_app(self.app)
            self.projeto = next(iter(recentes(self.app)), (None, None))[0]
            if not detalhe and self.projeto:
                detalhe = self.projeto.name
            self.lampada.setFixedSize(9, 9)
            self.lampada.setStyleSheet(f'background:{LAMPADAS[self.tipo]};border-radius:4px;')
            self.lampada.setVisible(bool(titulo))
            self.estado.setText(titulo)
            self.estado.setVisible(bool(titulo))
            medida = self.detalhe.fontMetrics()
            self.detalhe.setText(medida.elidedText(detalhe, Qt.ElideMiddle, 90))
            rodando_ = self.tipo == 'run'
            if self.mar.moving != rodando_:
                self.mar.moving = rodando_
                if self.mar.relogio.isActive():
                    self.mar.relogio.start(33 if rodando_ else 66)
            if rodando_:
                texto = 'Show'
            elif self.projeto:
                texto = f'Open {self.projeto.name}'
            else:
                texto = 'Open'
            self.acao.setText(self.acao.fontMetrics().elidedText(texto, Qt.ElideMiddle, 150))
            self.acao.setToolTip(str(self.projeto) if self.projeto else '')
            self.acao.setEnabled(self.tipo != 'att')

        def agir(self):
            if self.tipo == 'run':
                mostrar(self.app, self.projeto)
            elif self.projeto:
                abrir(self.app, str(self.projeto))
            else:
                self.painel.boasvindas(self.app)

        def mouseReleaseEvent(self, e):
            if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
                self.painel.boasvindas(self.app)

    class Preparo(Raiz):
        """First-use window. Everything here can be changed later, and it can run again."""

        def __init__(self, painel):
            super().__init__()
            self.setObjectName('raiz')
            self.painel = painel
            self.setWindowTitle(f"Set up {marca()['name']}")
            com_vidro(self)
            self.resize(820, 650)
            self.linhas = {}
            v = QVBoxLayout(integrar(self, True))
            v.setContentsMargins(28, 18, 28, 18)
            v.setSpacing(6)
            topo = QHBoxLayout()
            topo.setSpacing(10)
            topo.addWidget(icone('hub', 28))
            topo.addWidget(rotulo(marca()['name'], 'forte'))
            topo.addStretch(1)
            topo.addWidget(rotulo(versao(), 'mudo'))
            v.addLayout(topo)
            v.addWidget(linha('linhaH'))
            v.addSpacing(8)
            v.addWidget(rotulo(f"Set up {marca()['name']}", 'grande'))
            v.addWidget(rotulo('Everything here can be changed later in the Hub.', 'mudo'))
            v.addSpacing(10)
            v.addWidget(rotulo('Apps', 'secao'))
            grade = QGridLayout()
            grade.setHorizontalSpacing(10)
            grade.setVerticalSpacing(7)
            for coluna, texto in ((1, 'App'), (2, 'Create shortcut'), (4, 'Keymap'), (5, 'Project folder')):
                grade.addWidget(rotulo(texto, 'mudo'), 0, coluna)
            for i, (app, info) in enumerate(aplicativos().items(), 1):
                grade.addWidget(icone(app, 28), i, 0)
                grade.addWidget(rotulo(info['title'], 'forte'), i, 1)
                mesa, menu = QCheckBox('Desktop'), QCheckBox('Menu')
                for c, onde in ((mesa, 'on the Desktop'), (menu, 'in the app menu')):
                    c.setToolTip(f"Tick to create a {info['title']} shortcut {onde}")
                grade.addWidget(mesa, i, 2)
                grade.addWidget(menu, i, 3)
                teclas = None
                if info.get('keymap'):
                    teclas = segmento(('IntelliJ', 'VS Code'), 'IntelliJ' if keymap_de(app) == 'intellij' else 'VS Code', lambda _: None)
                    grade.addWidget(teclas, i, 4)
                pasta = QLineEdit(curto(pasta_projetos(app)))
                pasta.setToolTip(f"{info['title']} project folder")
                grade.addWidget(pasta, i, 5)
                procurar = QPushButton('Browse')
                procurar.clicked.connect(lambda _=False, c=pasta: self.procurar(c))
                grade.addWidget(procurar, i, 6)
                self.linhas[app] = (mesa, menu, teclas, pasta)
            grade.setColumnStretch(5, 1)
            v.addLayout(grade)
            v.addWidget(rotulo('A shortcut is created only where you tick a box. None are ticked to start with.', 'mudo'))
            v.addSpacing(10)
            v.addWidget(rotulo('Create Hub shortcut', 'secao'))
            fila = QHBoxLayout()
            fila.setSpacing(16)
            self.hub_mesa, self.hub_menu = QCheckBox('Desktop'), QCheckBox('App menu')
            for c in (self.hub_mesa, self.hub_menu):
                fila.addWidget(c)
            fila.addStretch(1)
            v.addLayout(fila)
            v.addSpacing(10)
            v.addWidget(rotulo('Theme for all apps', 'secao'))
            self.tema = 'Dark'
            fila = QHBoxLayout()
            fila.addWidget(segmento(THEMES, self.tema, self.escolher_tema))
            fila.addStretch(1)
            v.addLayout(fila)
            v.addStretch(1)
            fim = QHBoxLayout()
            fim.addStretch(1)
            pular = QPushButton('Skip')
            pular.clicked.connect(self.encerrar)
            terminar = QPushButton('Finish')
            terminar.setObjectName('azul')
            terminar.clicked.connect(self.concluir)
            fim.addWidget(pular)
            fim.addWidget(terminar)
            v.addLayout(fim)

        def escolher_tema(self, nome):
            self.tema = nome

        def procurar(self, campo):
            d = QFileDialog.getExistingDirectory(self, 'Project folder', str(CASA))
            if d:
                campo.setText(curto(d))

        def concluir(self):
            try:
                for app, (mesa, menu, teclas, pasta) in self.linhas.items():
                    if mesa.isChecked() or menu.isChecked():
                        criar_atalho(app, mesa.isChecked(), menu.isChecked())
                    alvo = Path(pasta.text().strip()).expanduser()
                    if str(alvo) != str(PROJETOS):
                        gravar_opcao(app, 'folder', str(alvo))
                    alvo.mkdir(parents=True, exist_ok=True)
                    if teclas:
                        aplicar_keymap(app, 'intellij' if teclas.botoes['IntelliJ'].isChecked() else 'vscode')
                    gravar_ajuste(app, 'workbench.colorTheme', tema_de(app, self.tema))
                if self.hub_mesa.isChecked() or self.hub_menu.isChecked():
                    criar_atalho(None, self.hub_mesa.isChecked(), self.hub_menu.isChecked())
            except OSError as e:
                QMessageBox.warning(self, 'Setup', f'Could not finish the setup: {e}')
                return
            self.encerrar()

        def encerrar(self):
            gravar_geral('setup', True)
            self.close()
            surgir(self.painel)

    class Novidade(Dialogo):
        """Update notice. Nothing downloads until the person clicks Update now."""

        def __init__(self, painel, nova):
            super().__init__(painel)
            self.painel = painel
            self.nova = nova
            self.parte = 0
            self.setWindowTitle(f"{marca()['name']} {nova['version']}")
            self.resize(460, 360)
            v = QVBoxLayout(integrar(self))
            v.setContentsMargins(18, 16, 18, 16)
            v.setSpacing(8)
            topo = QHBoxLayout()
            topo.setSpacing(9)
            bandeira = QLabel()
            bandeira.setPixmap(QIcon(str(ASSETS / 'flag.svg')).pixmap(18, 14))
            topo.addWidget(bandeira)
            topo.addWidget(rotulo(self.windowTitle(), 'grande'))
            topo.addStretch(1)
            topo.addWidget(rotulo(f'You have {versao()}', 'mudo'))
            v.addLayout(topo)
            v.addWidget(linha('linhaH'))
            notas = '\n'.join(nova.get('notes', '').strip().splitlines()[:8]) or 'See the release page for what changed.'
            r = rotulo(notas)
            r.setTextFormat(Qt.PlainText)
            r.setWordWrap(True)
            v.addWidget(r)
            v.addWidget(linha('linhaH'))
            for chave, valor in (('Package', pacote_atual()), ('Source', 'GitHub release, checked by SHA-256'),
                                 ('Kept', 'Projects, settings and your extensions'),
                                 ('If it fails', 'This version comes back')):
                fila = QHBoxLayout()
                fila.addWidget(rotulo(chave, 'mudo'))
                fila.addStretch(1)
                fila.addWidget(QLabel(valor))
                v.addLayout(fila)
            v.addStretch(1)
            self.estado = rotulo('', 'mudo')
            self.estado.setWordWrap(True)
            v.addWidget(self.estado)
            fim = QHBoxLayout()
            fim.addWidget(link('Skip this version', self.pular))
            if nova.get('page'):
                fim.addWidget(link('Release page', lambda: QDesktopServices.openUrl(QUrl(nova['page']))))
            fim.addStretch(1)
            self.depois = depois = QPushButton('Later')
            depois.clicked.connect(self.reject)
            self.relogio = QTimer(self)
            self.relogio.timeout.connect(self.mostrar)
            self.baixar = QPushButton('Update now')
            self.baixar.setObjectName('azul')
            self.baixar.clicked.connect(self.agir)
            pode = bool(nova.get('package') and nova.get('sums'))
            self.baixar.setEnabled(pode)
            if not pode:
                self.estado.setText('This release has no package for this system.')
            fim.addWidget(depois)
            fim.addWidget(self.baixar)
            v.addLayout(fim)

        def pular(self):
            gravar_geral('skip_version', self.nova['version'])
            self.painel.ver_novidade()
            self.reject()

        def agir(self):
            abertos = [info['title'] for app, info in aplicativos().items() if rodando(app)]
            motivo = troca.impedimento(RAIZ)
            if abertos:
                self.estado.setText(f"Close {', '.join(abertos)} first: the update replaces the editor.")
                return
            if motivo:
                self.estado.setText(f'This copy cannot update itself. {motivo} Get the package from the release page.')
                return
            self.baixar.setEnabled(False)
            self.depois.setEnabled(False)
            self.parte = 0
            self.mostrar()
            self.relogio.start(300)
            em_fundo(lambda: preparar_novidade(self.nova, self.andou), self.terminou)

        def andou(self, parte):
            self.parte = parte

        def mostrar(self):
            self.estado.setText('Unpacking and checking…' if self.parte is None else f'Downloading… {self.parte:.0%}')

        def terminou(self, area_, erro):
            self.relogio.stop()
            if not erro:
                try:
                    troca.iniciar(RAIZ, area_)
                except OSError as e:
                    erro = str(e)
            if erro:
                self.baixar.setEnabled(True)
                self.depois.setEnabled(True)
                self.estado.setText(f'Nothing was changed. {erro[:200]}')
                return
            self.estado.setText('Restarting…')
            QApplication.quit()

    class Painel(Raiz):
        """Janela principal: lista os apps e guarda só o que vale para todos."""

        def __init__(self):
            super().__init__()
            self.setObjectName('raiz')
            com_vidro(self)
            b = marca()
            self.setWindowTitle(f"{b['hub']} · Cargo")
            # A fixed size keeps window managers, KDE included, from maximizing the panel.
            self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
                                | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
            self.setFixedSize(400, 620)
            self.tela = None
            self.linhas = []
            self.miolo = Troca()
            self.ferramentas = self.pagina_ferramentas()
            self.lista = ListaProjetos()
            self.projetos = self.pagina_projetos()
            self.gerais = self.pagina_gerais()
            for p in (self.ferramentas, self.projetos, self.gerais):
                self.miolo.addWidget(p)
            v = QVBoxLayout()
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            topo = QHBoxLayout()
            topo.setContentsMargins(12, 0, 6, 0)
            topo.setSpacing(14)
            topo.addWidget(icone('hub', 22), 0, Qt.AlignVCenter)
            self.guias = {}
            grupo = QButtonGroup(self)
            for titulo, pagina in (('Cargo', self.ferramentas), ('Projects', self.projetos)):
                g = QPushButton(titulo)
                g.setObjectName('guia')
                g.setCheckable(True)
                g.clicked.connect(lambda _=False, w=pagina: self.miolo.ir(w))
                grupo.addButton(g)
                topo.addWidget(g)
                self.guias[titulo] = g
            self.guias['Cargo'].setChecked(True)
            topo.addStretch(1)
            ajuste_ = QToolButton()
            ajuste_.setIcon(QIcon(str(ASSETS / 'engrenagem.svg')))
            ajuste_.setIconSize(QSize(20, 20))
            ajuste_.setToolTip('Settings')
            ajuste_.setObjectName('engrenagem')
            ajuste_.setCheckable(True)
            ajuste_.clicked.connect(lambda: self.miolo.ir(self.gerais))
            ajuste_.setIconSize(QSize(17, 17))
            grupo.addButton(ajuste_)
            self.guias['Settings'] = ajuste_
            caixa = QWidget()
            caixa.setFixedHeight(44)
            caixa.setLayout(topo)
            integrar(self, False, caixa).setLayout(v)
            v.addWidget(linha('linhaH'))
            v.addWidget(self.miolo, 1)
            self.faixa = QFrame()
            self.faixa.setObjectName('faixa')
            self.faixa.setFixedHeight(36)
            f = QHBoxLayout(self.faixa)
            f.setContentsMargins(12, 0, 12, 0)
            f.setSpacing(9)
            bandeira = QLabel()
            bandeira.setPixmap(QIcon(str(ASSETS / 'flag.svg')).pixmap(18, 14))
            f.addWidget(bandeira)
            self.faixa_texto = rotulo('', 'forte')
            f.addWidget(self.faixa_texto, 1)
            f.addWidget(link('View', self.ver_detalhes))
            v.addWidget(linha('linhaH'))
            v.addWidget(self.faixa)
            rodape = QHBoxLayout()
            rodape.setContentsMargins(12, 0, 12, 0)
            rodape.addWidget(rotulo(f"{marca()['name']} {versao()}", 'forte'))
            rodape.addStretch(1)
            rodape.addWidget(rotulo(f'Editor {versao_editor()}', 'mudo'))
            rodape.addSpacing(6)
            rodape.addWidget(ajuste_)
            pe = QWidget()
            pe.setFixedHeight(32)
            pe.setLayout(rodape)
            v.addWidget(pe)
            self.miolo.currentChanged.connect(self.marcar)
            self.vigia = QTimer(self)
            self.vigia.timeout.connect(self.atualizar)
            self.ver_novidade()
            if opcoes().get('check_updates', True) and time.time() - opcoes().get('checked', 0) > 21600:
                em_fundo(checar_novidade, self.recebeu)

        def ver_novidade(self):
            nova = novidade()
            self.faixa.setVisible(bool(nova))
            if nova:
                self.faixa_texto.setText(f"{marca()['name']} {nova['version']} is available")

        def recebeu(self, nova, erro):
            if not erro:
                gravar_geral('checked', time.time())
                gravar_geral('update', nova)
                self.ver_novidade()
            if hasattr(self, 'checagem'):
                if erro:
                    self.checagem.setText(erro)
                else:
                    self.checagem.setText(self.faixa_texto.text() if novidade() else 'Up to date.')

        def checar_agora(self):
            self.checagem.setText('Checking…')
            em_fundo(checar_novidade, self.recebeu)

        def ver_detalhes(self):
            nova = novidade()
            if nova:
                Novidade(self, nova).exec()

        def marcar(self, _):
            pagina = self.miolo.currentWidget()
            nome = {self.ferramentas: 'Cargo', self.projetos: 'Projects', self.gerais: 'Settings'}[pagina]
            self.guias[nome].setChecked(True)
            self.setWindowTitle(f"{marca()['hub']} · {nome}")

        def atualizar(self):
            for f in self.linhas:
                f.atualizar()

        def showEvent(self, _):
            self.atualizar()
            self.vigia.start(3000)

        def hideEvent(self, _):
            self.vigia.stop()

        def pagina_ferramentas(self):
            p = QWidget()
            p.setObjectName('pagina')
            v = QVBoxLayout(p)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            for app in aplicativos():
                self.linhas.append(Ferramenta(app, self))
                v.addWidget(self.linhas[-1])
            v.addStretch(1)
            return p

        def pagina_projetos(self):
            p = QWidget()
            p.setObjectName('pagina')
            v = QVBoxLayout(p)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            busca = busca_linha()
            busca.textChanged.connect(self.lista.filtrar)
            fila = QHBoxLayout()
            fila.setContentsMargins(10, 6, 12, 6)
            fila.setSpacing(6)
            fila.addWidget(busca, 1)
            grupo = QButtonGroup(p)
            todos = QToolButton()
            todos.setText('All')
            todos.setToolTip('All apps')
            todos.setObjectName('filtro')
            todos.setCheckable(True)
            todos.setChecked(True)
            todos.clicked.connect(lambda: self.lista.so_app(None))
            grupo.addButton(todos)
            fila.addWidget(todos)
            for app, info in aplicativos().items():
                b = QToolButton()
                b.setToolTip(info['title'])
                b.setCheckable(True)
                b.setFixedSize(16, 16)
                b.setStyleSheet('QToolButton{background:%s;border:2px solid #16181B;border-radius:0;padding:0;}'
                                'QToolButton:checked{border-color:#EDE6D3;}' % info.get('accent', AZUL))
                b.clicked.connect(lambda _=False, a=app: self.lista.so_app(a))
                grupo.addButton(b)
                fila.addWidget(b)
            v.addLayout(fila)
            v.addWidget(linha('linhaH'))
            v.addWidget(self.lista, 1)
            return p

        def pagina_gerais(self):
            p = QWidget()
            p.setObjectName('pagina')
            v = QVBoxLayout(p)
            v.setContentsMargins(16, 12, 16, 12)
            v.setSpacing(6)
            v.addWidget(rotulo('Settings', 'grande'))
            v.addSpacing(4)
            v.addWidget(rotulo('Trusted folders', 'secao'))
            d = rotulo('Projects here open with every feature on. Applies to all apps.', 'mudo')
            d.setWordWrap(True)
            v.addWidget(d)
            self.confiaveis = QListWidget()
            self.confiaveis.setObjectName('lista')
            v.addWidget(self.confiaveis)
            fila = QHBoxLayout()
            fila.setSpacing(8)
            b = QPushButton('Add')
            b.clicked.connect(self.adicionar)
            fila.addWidget(b)
            self.tirar = QPushButton('Remove')
            self.tirar.clicked.connect(self.retirar)
            self.tirar.setEnabled(False)
            fila.addWidget(self.tirar)
            fila.addStretch(1)
            v.addLayout(fila)
            self.confiaveis.itemSelectionChanged.connect(lambda: self.tirar.setEnabled(bool(self.confiaveis.selectedItems())))
            v.addSpacing(8)
            v.addWidget(rotulo('Window', 'secao'))
            fundo = QHBoxLayout()
            fundo.addWidget(QLabel('Background'))
            fundo.addStretch(1)
            motivo = blur_unsupported()
            atual = 'Blur' if opcoes().get('blur', False) and not motivo else 'Solid'
            seg = segmento(('Solid', 'Blur'), atual, self.mudar_fundo)
            if motivo:
                seg.botoes['Blur'].setEnabled(False)
                seg.botoes['Blur'].setToolTip(motivo)
            fundo.addWidget(seg)
            v.addLayout(fundo)
            if motivo:
                v.addWidget(rotulo(motivo, 'mudo'))
            c = QCheckBox('Transitions and boat animation')
            c.setChecked(opcoes().get('transitions', True))
            c.toggled.connect(lambda n: gravar_geral('transitions', n))
            v.addWidget(c)
            v.addSpacing(8)
            v.addWidget(rotulo('Shortcuts', 'secao'))
            atalho_ = QPushButton('Add Hub to Desktop')
            atalho_.clicked.connect(lambda: self.atalho(None))
            v.addWidget(atalho_, 0, Qt.AlignLeft)
            v.addSpacing(8)
            v.addWidget(rotulo('Setup', 'secao'))
            preparo = QPushButton('Run setup again')
            preparo.clicked.connect(self.preparar_de_novo)
            v.addWidget(preparo, 0, Qt.AlignLeft)
            v.addSpacing(8)
            v.addWidget(rotulo('Updates', 'secao'))
            c = QCheckBox('Check GitHub for new versions when the Hub opens')
            c.setChecked(opcoes().get('check_updates', True))
            c.toggled.connect(lambda n: gravar_geral('check_updates', n))
            v.addWidget(c)
            fila = QHBoxLayout()
            fila.setSpacing(8)
            b = QPushButton('Check now')
            b.clicked.connect(self.checar_agora)
            self.checagem = rotulo('', 'mudo')
            self.checagem.setWordWrap(True)
            fila.addWidget(b)
            fila.addWidget(self.checagem, 1)
            v.addLayout(fila)
            v.addStretch(1)
            self.listar()
            return p

        def mudar_fundo(self, texto):
            """Blur needs a new native window, so the panel reopens itself right away."""
            quer = texto == 'Blur'
            if quer == VIDRO[0]:
                return
            gravar_geral('blur', quer)
            VIDRO[0] = vidro_disponivel()
            novo = Painel()
            novo.miolo.setCurrentWidget(novo.gerais)
            novo.resize(self.size())
            novo.move(self.pos())
            QApplication.instance().painel = novo
            surgir(novo)
            self.close()

        def preparar_de_novo(self):
            self.preparo = Preparo(self)
            self.hide()
            surgir(self.preparo)

        def listar(self):
            self.confiaveis.clear()
            self.confiaveis.addItems([curto(p) for p in pastas_confiaveis()])
            self.caminhos = [str(p) for p in pastas_confiaveis()]
            self.confiaveis.setFixedHeight(max(1, min(self.confiaveis.count(), 4)) * 26 + 2)

        def adicionar(self):
            pasta = QFileDialog.getExistingDirectory(self, 'Trust Folder', str(CASA))
            if pasta:
                confiar(pasta)
                self.listar()

        def retirar(self):
            linha_ = self.confiaveis.currentRow()
            if linha_ >= 0:
                retirar_confianca(self.caminhos[linha_])
                self.listar()

        def boasvindas(self, app, aba=None):
            self.tela = Boasvindas(app, self)
            if aba:
                self.tela.ir(aba)
            self.tela.move(self.frameGeometry().center() - self.tela.rect().center())
            self.hide()
            entrar(app, lambda: surgir(self.tela))

        def atalho(self, app):
            try:
                destino = criar_atalho(app)
                QMessageBox.information(self, 'Desktop shortcut', f'Added {nome_app(app) if app else marca()["hub"]} to {curto(destino.parent)}.')
            except OSError as e:
                QMessageBox.warning(self, 'Desktop shortcut', f'Could not create the shortcut: {e}')

    CLASSES.update(Partida=Partida, Abertura=Abertura, Preparo=Preparo, Novidade=Novidade, Personalizar=Personalizar, Boasvindas=Boasvindas,
                   endereco_git=endereco_git, erro_git=erro_git)
    aplicacao = QApplication(sys.argv)
    if forcar_xcb:
        del os.environ['QT_QPA_PLATFORM']
    limpar_ambiente()
    aplicacao.setApplicationName(marca()['hub'])
    aplicacao.setStyle('Fusion')
    aplicacao.setQuitOnLastWindowClosed(True)
    for f in ASSETS.glob('*.[to]tf'):
        QFontDatabase.addApplicationFont(str(f))
    aplicacao.setStyleSheet(estilo(AZUL))
    aplicacao.setWindowIcon(QIcon(str(ASSETS / 'hub.svg')))
    if '--shots' in sys.argv:
        destino = Path(sys.argv[sys.argv.index('--shots') + 1])
        p = Painel()
        for nome, pagina in (('cargo', p.ferramentas), ('projects', p.projetos), ('settings', p.gerais)):
            p.miolo.setCurrentWidget(pagina)
            p.show()
            aplicacao.processEvents()
            p.grab().save(str(destino / f'painel-{nome}.png'))
        for app in aplicativos():
            t = Boasvindas(app)
            t.show()
            for aba in t.abas:
                t.ir(aba)
                aplicacao.processEvents()
                t.grab().save(str(destino / f'{app}-{aba.lower()}.png'))
            t.close()
            s = Partida(app, '', True)
            s.show()
            aplicacao.processEvents()
            s.grab().save(str(destino / f'{app}-partida.png'))
            s.close()
        return 0
    if lancar:
        QTimer.singleShot(0, lambda: abrir(*lancar))
        return aplicacao.exec()
    j = Boasvindas(inicial) if inicial else Painel()
    if not inicial and not opcoes().get('setup') and not opcoes().get('recent'):
        j.preparo = j = Preparo(j)
    for trabalho in AO_ABRIR:
        QTimer.singleShot(0, lambda t=trabalho: t(j))
    if inicial or not opcoes().get('transitions', True):
        surgir(j)
    else:
        abertura = Abertura(lambda: surgir(j))
        abertura.comecar()
    return aplicacao.exec()


def main():
    args = sys.argv[1:]
    if args[:1] in (['--open'], ['--background'], ['--trust'], ['--prepare']):
        limpar_ambiente()
    if args[:1] == ['--open']:
        porta = int(args[args.index('--port') + 1]) if '--port' in args else None
        alvos = [a for a in args[2:] if a != '--port' and a != str(porta)]
        processo = abrir_app(args[1], alvos, porta)
        print(processo.pid)
        return 0
    if args[:1] == ['--launch']:
        return janela(lancar=args[1:])
    if args[:1] == ['--welcome']:
        return janela(args[1])
    if args[:1] == ['--background']:
        return 0 if gravar_fundo(args[1], os.environ['SUITE_TOOLS']) else 1
    if args[:1] == ['--trust']:
        confiar(args[1])
        return 0
    if args[:1] == ['--prepare']:
        for app in aplicativos():
            preparar(app)
        return 0
    if args[:1] == ['--swap']:  # the helper copy: see troca.py
        return troca.aplicar(args[1], args[2], int(args[3]), processo_vivo)
    if args[:1] == ['--install-update']:  # a package already downloaded and checked by the person
        if any(rodando(app) for app in aplicativos()):
            print('Close the editors first: the update replaces them.')
            return 2
        troca.iniciar(RAIZ, troca.preparar_pacote(RAIZ, args[1]))
        return 0
    if args[:1] == ['--check-update']:
        try:
            nova = checar_novidade()
        except (OSError, ValueError, KeyError) as e:
            print(e)
            return 1
        print(nova['version'] if nova else 'no release')
        return 0
    if args[:1] == ['--updated']:
        try:
            depois_de_atualizar(args[1])
        except Exception:  # any failure here must end the program, so the helper restores the old version
            return 1
    elif args[:1] == ['--update-failed']:
        try:
            motivo = (Path(args[1]) / 'error.txt').read_text(encoding='utf8')
        except OSError:
            motivo = ''
        AO_ABRIR.append(lambda j: avisar_falha(j, motivo))
    if args[:1] != ['--updated']:
        restos_de_troca()
    return janela()


def avisar_falha(pai, motivo):
    from PySide6.QtWidgets import QMessageBox
    aviso = QMessageBox(QMessageBox.Warning, 'Update', 'The update was not installed.', QMessageBox.Ok, pai)
    aviso.setInformativeText(f'{motivo}\n\nYour previous version is back, with your settings and projects as they were.')
    aviso.open()


if __name__ == '__main__':
    sys.exit(main())
