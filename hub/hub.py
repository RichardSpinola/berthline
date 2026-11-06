"""Hub of the suite: opens each profile and keeps its settings."""
import ctypes
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

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
PADRAO = {'telemetry': False, 'ai': False, 'visual': True, 'animations': True, 'memory': '1G'}
CORES_ICONE = ['#A9C27F', '#C77DBB', '#6AAB73', '#56A8F5', '#E8A33D', '#F75464', '#9B8AE3']


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


def confiar(pasta):
    gravar_confiaveis(pastas_confiaveis() + [Path(pasta).resolve()])


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
    for chave, valor in base.items():
        if chave not in atual or '${SUITE}' in json.dumps(valor):
            atual[chave] = caminhos(valor)
    atual['telemetry.telemetryLevel'] = 'all' if opcao(app, 'telemetry') else 'off'
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
    for origem in origens + [PERFIS / app]:
        teclas = origem / 'keybindings.json'
        if teclas.exists() and not (usuario / 'keybindings.json').exists():
            shutil.copy(teclas, usuario)
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
    amb.pop('SUITE_ROOT', None)
    return amb


def abrir_app(app, alvos=(), porta=None, comando_=None):
    preparar(app)
    if comando_:
        (ferramentas(app) / 'ao-abrir').write_text(comando_, encoding='utf8')
    if alvos:
        registrar(app, alvos[0])
    extra = {'creationflags': subprocess.DETACHED_PROCESS} if JANELAS else {'start_new_session': True}
    return subprocess.Popen(comando(app, alvos, porta), env=ambiente(app), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)


def registrar(app, alvo):
    tudo = opcoes()
    lista = [p for p in tudo.setdefault('recent', []) if p['path'] != str(alvo)]
    tudo['recent'] = [{'path': str(alvo), 'app': app}] + lista[:29]
    OPCOES.parent.mkdir(parents=True, exist_ok=True)
    OPCOES.write_text(json.dumps(tudo, indent=2), encoding='utf8')


def recentes(so_app=None):
    vistos = {p['path']: (p['app'], float('inf')) for p in opcoes().get('recent', [])}
    for app in aplicativos():
        for w in (pasta_usuario(app) / 'workspaceStorage').glob('*/workspace.json'):
            try:
                u = urlparse(json.loads(w.read_text(encoding='utf8'))['folder'])
                if u.scheme == 'file':
                    vistos.setdefault(unquote(u.path).lstrip('/') if JANELAS else unquote(u.path), (app, w.stat().st_mtime))
            except (OSError, KeyError, ValueError):
                pass
    fora = set(opcoes().get('hidden', []))
    bons = [(Path(p), a, t) for p, (a, t) in vistos.items() if p not in fora and Path(p).is_dir()
            and (so_app is None or a == so_app) and not (TEMPORARIO and p.startswith(TEMPORARIO))]
    return [(p, a) for p, a, _ in sorted(bons, key=lambda x: -x[2])]


def ocultar_recente(caminho):
    tudo = opcoes()
    tudo['hidden'] = sorted(set(tudo.get('hidden', [])) | {str(caminho)})
    tudo['recent'] = [p for p in tudo.get('recent', []) if p['path'] != str(caminho)]
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


def limpar_etapa(app):
    (ferramentas(app) / 'etapa').unlink(missing_ok=True)


def vidro_disponivel():
    if not opcoes().get('blur', True) or os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        return False
    if JANELAS:
        return sys.getwindowsversion().build >= 22621
    return 'KDE' in os.environ.get('XDG_CURRENT_DESKTOP', '') and bool(os.environ.get('DISPLAY'))


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
    if PROJETOS.is_dir():
        for p in sorted(PROJETOS.iterdir(), key=lambda x: x.name.lower()):
            if p.is_dir() and not p.name.startswith('.') and p not in ja and str(p) not in fora:
                app = tipo_projeto(p)
                if so_app in (None, app):
                    disco.append((p, app))
    if so_app:
        return [(t, l) for t, l in (('Recent', feitos), ('On this computer', disco)) if l]
    return [(info['title'], [x for x in feitos + disco if x[1] == app]) for app, info in aplicativos().items()
            if any(x[1] == app for x in feitos + disco)]


def marca_dagua(app):
    """Grava em cinza o ícone do app para a tela vazia do editor."""
    desenho = (ASSETS / f'{app}.svg').read_text(encoding='utf8')
    cinza = re.sub(r'(fill|stroke)="#[0-9A-Fa-f]{6}"', r'\1="#35383D"', desenho)
    (DADOS / app).mkdir(parents=True, exist_ok=True)
    (DADOS / app / 'watermark.svg').write_text(cinza, encoding='utf8')


def janela_aberta(app, desde):
    return any(p.stat().st_mtime >= desde - 1 for p in (DADOS / app / 'user/logs').glob('*/window*'))


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


def criar_atalho(app):
    """Cria o atalho do Hub ou de um app; o do app vai direto para a tela dele."""
    b = marca()
    titulo = f"{b['name']} {aplicativos()[app]['title']}" if app else b['hub']
    congelado = getattr(sys, 'frozen', False)
    programa = sys.executable if congelado else f'{sys.executable} {Path(__file__).resolve()}'
    args = f'--welcome {app}' if app else ''
    pasta = area_de_trabalho()
    pasta.mkdir(parents=True, exist_ok=True)
    if JANELAS:
        icone_ = imagem_icone(app or 'hub', 'ico')
        destino = pasta / f'{titulo}.lnk'
        script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{destino}');$s.TargetPath='{sys.executable}';"
                  f"$s.Arguments='{args}';$s.WorkingDirectory='{RAIZ}';$s.IconLocation='{icone_}';$s.Save()")
        r = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode:
            (pasta / f'{titulo}.bat').write_text(f'@start "" "{sys.executable}" {args}\r\n')
        return destino
    icone_ = imagem_icone(app or 'hub', 'png')
    texto = (f'[Desktop Entry]\nType=Application\nName={titulo}\nExec="{programa}" {args}\n'
             f'Icon={icone_}\nTerminal=false\nCategories=Development;\n') if congelado else (
             f'[Desktop Entry]\nType=Application\nName={titulo}\nExec={programa} {args}\nIcon={icone_}\nTerminal=false\n')
    nome = f"{b['name'].lower()}{'-' + app if app else ''}.desktop"
    menu = CASA / '.local/share/applications'
    menu.mkdir(parents=True, exist_ok=True)
    for destino in (menu / nome, pasta / nome):
        destino.write_text(texto, encoding='utf8')
        destino.chmod(0o755)
    return pasta / nome


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


def criar_projeto(app, modelo_, nome, local, git=False):
    raiz = Path(local) / nome
    origem = PERFIS / app / 'templates' / modelo_
    if origem.is_dir() and modelo_ != 'Empty Project':
        shutil.copytree(origem, raiz)
    else:
        raiz.mkdir(parents=True)
    if git:
        subprocess.run(['git', 'init', '-q'], cwd=raiz, check=True)
    if not confiavel(raiz):
        confiar(raiz)
    return raiz


def janela(inicial=None):
    if not JANELAS and os.environ.get('DISPLAY') and 'QT_QPA_PLATFORM' not in os.environ:
        os.environ['QT_QPA_PLATFORM'] = 'xcb'
    from PySide6.QtCore import QEasingCurve, QProcess, QProcessEnvironment, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QUrl
    from PySide6.QtGui import (
        QColor, QDesktopServices, QFont, QFontDatabase, QGuiApplication, QIcon, QImage, QPainter, QPainterPath, QPen,
    )
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import (
        QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame,
        QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
        QPushButton, QScrollArea, QSlider, QStackedWidget, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout,
        QWidget,
    )

    COM_VIDRO = vidro_disponivel()
    ESTILO = """
    * { font-family: 'Inter', 'Segoe UI', 'Noto Sans', sans-serif; font-size: 13px; color: #DFE1E5; }
    QWidget#pagina, QScrollArea, QStackedWidget, QAbstractScrollArea { background: transparent; border: none; }
    QDialog, QMenu, QMessageBox { background: #26272B; }
    QFrame#linhaV, QFrame#linhaH { background: rgba(255, 255, 255, 22); border: none; }
    QLabel#mudo { color: #8F939A; font-size: 12px; }
    QLabel#titulo { font-size: 14px; }
    QLabel#grande { font-size: 19px; }
    QLabel#secao { color: #B6B9BF; font-size: 12px; }
    QPushButton { background: transparent; border: 1px solid rgba(255, 255, 255, 40); border-radius: 3px; padding: 5px 12px; }
    QPushButton:hover { background: rgba(255, 255, 255, 14); }
    QPushButton:pressed { background: rgba(255, 255, 255, 26); }
    QPushButton:disabled { color: #6F737A; border-color: rgba(255, 255, 255, 18); }
    QPushButton#azul { background: #DFE1E5; border-color: #DFE1E5; color: #16171A; }
    QPushButton#azul:hover { background: #FFFFFF; }
    QPushButton#aba { border: none; border-radius: 3px; text-align: left; padding: 6px 10px; color: #A9ACB2; }
    QPushButton#aba:hover { background: rgba(255, 255, 255, 12); color: #DFE1E5; }
    QPushButton#aba:checked { background: rgba(255, 255, 255, 20); color: #FFFFFF; }
    QPushButton#guia { border: none; border-radius: 3px; padding: 5px 9px; color: #8F939A; }
    QPushButton#guia:hover { background: transparent; color: #DFE1E5; }
    QPushButton#guia:checked { color: #FFFFFF; background: rgba(255, 255, 255, 20); }
    QPushButton#link { border: none; color: #A9C1F5; padding: 2px 0; text-align: left; background: transparent; }
    QPushButton#link:hover { text-decoration: underline; }
    QToolButton { border: none; border-radius: 3px; padding: 3px; }
    QToolButton:hover { background: rgba(255, 255, 255, 20); }
    QToolButton::menu-indicator { image: none; }
    QLineEdit, QComboBox { background: rgba(255, 255, 255, 12); border: 1px solid rgba(255, 255, 255, 34); border-radius: 3px; padding: 4px 7px; }
    QLineEdit#busca { background: transparent; border: none; }
    QLineEdit:focus, QComboBox:focus { border-color: ACENTO; }
    QComboBox::drop-down { border: none; width: 22px; }
    QComboBox::down-arrow { image: url(SETA); }
    QComboBox QAbstractItemView { background: #26272B; selection-background-color: #3A3C42; }
    QListWidget { background: transparent; border: none; outline: 0; }
    QListWidget::item { border-radius: 3px; }
    QListWidget::item:hover { background: rgba(255, 255, 255, 12); }
    QListWidget::item:selected { background: rgba(255, 255, 255, 20); }
    QFrame#ferramenta { border-radius: 3px; }
    QFrame#ferramenta:hover { background: rgba(255, 255, 255, 12); }
    QMenu { border: 1px solid #3A3C42; padding: 4px; }
    QMenu::item { padding: 5px 24px 5px 12px; border-radius: 3px; }
    QMenu::item:selected { background: #3A3C42; }
    QMenu::separator { height: 1px; background: #3A3C42; margin: 4px 8px; }
    QCheckBox { spacing: 7px; }
    QTableWidget { background: #1E1F22; border: none; gridline-color: #3A3C42; }
    QHeaderView::section { background: #26272B; border: none; padding: 5px; }
    QSlider::groove:horizontal { height: 3px; background: rgba(255, 255, 255, 40); }
    QSlider::handle:horizontal { width: 12px; margin: -5px 0; border-radius: 6px; background: #DFE1E5; }
    QScrollBar:vertical { background: transparent; width: 8px; }
    QScrollBar::handle:vertical { background: rgba(255, 255, 255, 40); border-radius: 4px; min-height: 24px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    """
    AZUL = '#3574F0'

    def estilo(cor):
        return ESTILO.replace('SETA', (ASSETS / 'seta.svg').as_posix()).replace('ACENTO', cor)

    def com_vidro(janela_):
        """Deixa a janela translúcida com desfoque do sistema, quando existe."""
        if COM_VIDRO:
            janela_.setAttribute(Qt.WA_TranslucentBackground)

    def surgir(janela_):
        janela_.setWindowOpacity(0.0)
        janela_.show()
        if COM_VIDRO:
            aplicar_vidro(int(janela_.winId()))
        animacao = QPropertyAnimation(janela_, b'windowOpacity', janela_)
        animacao.setDuration(180)
        animacao.setStartValue(0.0)
        animacao.setEndValue(1.0)
        animacao.setEasingCurve(QEasingCurve.OutCubic)
        animacao.start()
        janela_.entrada = animacao

    class Raiz(QWidget):
        """Janela principal: pinta o próprio fundo para o vidro funcionar."""

        def paintEvent(self, _):
            p = QPainter(self)
            p.setCompositionMode(QPainter.CompositionMode_Source)
            p.fillRect(self.rect(), QColor(22, 23, 26, 205) if COM_VIDRO else QColor('#1E1F22'))

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

    def nome_app(app):
        return f"{marca()['name']} {aplicativos()[app]['title']}"

    class Combo(QComboBox):
        def wheelEvent(self, evento):
            evento.ignore()

    class Barco(QWidget):
        """Barco balançando na água, usado em toda espera."""

        def __init__(self, app, largura=300, altura=150):
            super().__init__()
            self.setFixedSize(largura, altura)
            self.fase = 0.0
            self.desenho = QSvgRenderer(str(ASSETS / f'{app}.svg'), self)
            self.cor = QColor(aplicativos()[app].get('accent', '#8C939E'))
            relogio = QTimer(self)
            relogio.timeout.connect(self.passo)
            relogio.start(33)

        def passo(self):
            self.fase += 0.07
            self.update()

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            largura = self.width()
            agua = self.height() - 22
            lado = self.height() * .62
            p.save()
            p.translate(largura / 2, agua - lado * .36 + math.sin(self.fase) * 4)
            p.rotate(math.sin(self.fase * .8) * 3)
            self.desenho.render(p, QRectF(-lado / 2, -lado * .62, lado, lado))
            p.restore()
            for camada, (altura, alfa, passo_) in enumerate(((agua + 2, 255, 1.0), (agua + 11, 90, -.7))):
                onda = QPainterPath()
                for x in range(0, largura + 1, 4):
                    y = altura + math.sin(x / 26 + self.fase * 2 * passo_) * 3
                    onda.moveTo(x, y) if x == 0 else onda.lineTo(x, y)
                cor = QColor(self.cor)
                cor.setAlpha(alfa)
                p.setPen(QPen(cor, 2.2 - camada))
                p.setBrush(Qt.NoBrush)
                p.drawPath(onda)

    class Partida(Raiz):
        """Janela de espera com o barco, até o editor terminar de carregar."""

        def __init__(self, app, texto):
            super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            self.setObjectName('raiz')
            com_vidro(self)
            self.setStyleSheet(estilo(aplicativos()[app].get('accent', AZUL)))
            self.setFixedSize(380, 250)
            v = QVBoxLayout(self)
            v.setContentsMargins(40, 26, 40, 22)
            self.texto = rotulo(texto)
            self.texto.setAlignment(Qt.AlignCenter)
            v.addWidget(Barco(app), 0, Qt.AlignCenter)
            v.addWidget(self.texto)
            tela = QGuiApplication.primaryScreen().availableGeometry()
            self.move(tela.center() - self.rect().center())

        def sair(self, depois):
            animacao = QPropertyAnimation(self, b'windowOpacity', self)
            animacao.setDuration(240)
            animacao.setStartValue(1.0)
            animacao.setEndValue(0.0)
            animacao.finished.connect(depois)
            animacao.start()
            self.saida = animacao

    ETAPAS = {'': 'Loading extensions…', 'java': 'Starting the Java server…', 'ready': 'Ready'}

    def abrir(app, *alvos, comando_=None):
        if alvos and not pode_abrir(alvos[0]):
            return
        inicio = time.time()
        limite = 110 if aplicativos()[app].get('memory') else 30
        partida = Partida(app, f'Starting {nome_app(app)}…')
        for w in QApplication.topLevelWidgets():
            if w is not partida and not isinstance(w, QMenu):
                w.hide()
        surgir(partida)
        QApplication.processEvents()
        limpar_etapa(app)
        abrir_app(app, alvos, comando_=comando_)

        def conferir():
            passou = time.time() - inicio
            if not janela_aberta(app, inicio) and passou < limite:
                return
            agora = etapa_atual(app)
            partida.texto.setText(ETAPAS.get(agora, ETAPAS['']))
            if agora == 'ready' or passou > limite:
                relogio.stop()
                partida.sair(QApplication.quit)
        relogio = QTimer(partida)
        relogio.timeout.connect(conferir)
        relogio.start(200)

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

    class NovoProjeto(QDialog):
        def __init__(self, pai, app):
            super().__init__(pai)
            self.setWindowTitle('New Project')
            self.resize(640, 400)
            self.app = app
            self.projeto = None
            self.modelos = QListWidget()
            self.modelos.setFixedWidth(180)
            self.modelos.addItem('Empty Project')
            self.modelos.addItems(aplicativos()[app].get('templates', []))
            self.modelos.setCurrentRow(1 if self.modelos.count() > 1 else 0)
            self.nome = QLineEdit('untitled')
            self.nome.selectAll()
            self.local = QLineEdit(str(PROJETOS))
            pasta = QPushButton('Browse…')
            pasta.clicked.connect(self.escolher)
            fila = QHBoxLayout()
            fila.addWidget(self.local)
            fila.addWidget(pasta)
            self.git = QCheckBox('Create Git repository')
            self.git.setEnabled(bool(shutil.which('git')))
            self.existe = rotulo('', 'mudo')
            self.existe.setWordWrap(True)
            self.erro = rotulo('', 'mudo')
            criar = QPushButton('Create')
            criar.setObjectName('azul')
            criar.setDefault(True)
            criar.clicked.connect(self.criar)
            cancelar = QPushButton('Cancel')
            cancelar.clicked.connect(self.reject)
            form = QFormLayout()
            form.setHorizontalSpacing(14)
            form.addRow('Name:', self.nome)
            form.addRow('Location:', fila)
            form.addRow('', self.git)
            direita = QVBoxLayout()
            direita.setContentsMargins(16, 8, 8, 0)
            direita.addLayout(form)
            direita.addWidget(self.existe)
            direita.addStretch(1)
            rodape = QHBoxLayout()
            rodape.addWidget(self.erro, 1)
            rodape.addWidget(cancelar)
            rodape.addWidget(criar)
            direita.addLayout(rodape)
            h = QHBoxLayout(self)
            h.setContentsMargins(12, 12, 12, 12)
            h.setSpacing(0)
            h.addWidget(self.modelos)
            h.addWidget(linha('linhaV'))
            h.addLayout(direita, 1)
            self.nome.textChanged.connect(self.avaliar)
            self.local.textChanged.connect(self.avaliar)
            self.avaliar()

        def avaliar(self):
            alvo = Path(self.local.text().strip()) / self.nome.text().strip()
            self.existe.setText(f'{alvo.name} already exists here. Open it from the project list.' if alvo.exists() else '')

        def escolher(self):
            d = QFileDialog.getExistingDirectory(self, 'Location', self.local.text())
            if d:
                self.local.setText(d)

        def criar(self):
            nome, local = self.nome.text().strip(), self.local.text().strip()
            if not re.fullmatch(r'[\w .-]+', nome):
                self.erro.setText('Enter a valid name.')
            elif (Path(local) / nome).exists():
                self.erro.setText('This project already exists.')
            else:
                try:
                    self.projeto = criar_projeto(self.app, self.modelos.currentItem().text(), nome, local, self.git.isChecked())
                    self.accept()
                except (OSError, subprocess.CalledProcessError) as e:
                    self.erro.setText(str(e)[:90])

    class Clonar(QDialog):
        def __init__(self, pai, app):
            super().__init__(pai)
            self.setWindowTitle('Clone Repository')
            self.setMinimumWidth(520)
            self.pasta = None
            self.proc = QProcess(self)
            self.url = QLineEdit()
            self.url.setPlaceholderText('https://github.com/user/project.git')
            self.destino = QLineEdit(str(CLONES))
            self.url.textChanged.connect(lambda t: self.destino.setText(str(CLONES / nome_do_repo(t)) if t else str(CLONES)))
            self.estado = rotulo('' if shutil.which('git') else 'Git was not found on this computer.', 'mudo')
            self.botao = QPushButton('Clone')
            self.botao.setObjectName('azul')
            self.botao.setDefault(True)
            self.botao.setEnabled(bool(shutil.which('git')))
            self.botao.clicked.connect(self.clonar)
            cancelar = QPushButton('Cancel')
            cancelar.clicked.connect(self.cancelar)
            form = QFormLayout()
            form.addRow('URL:', self.url)
            form.addRow('Directory:', self.destino)
            self.barco = Barco(app, 300, 110)
            self.barco.hide()
            rodape = QHBoxLayout()
            rodape.addWidget(self.estado, 1)
            rodape.addWidget(cancelar)
            rodape.addWidget(self.botao)
            v = QVBoxLayout(self)
            v.addLayout(form)
            v.addWidget(self.barco, 0, Qt.AlignCenter)
            v.addSpacing(10)
            v.addLayout(rodape)
            self.proc.finished.connect(self.terminou)

        def clonar(self):
            url, dest = self.url.text().strip(), self.destino.text().strip()
            if not url or Path(dest).exists():
                self.estado.setText('Enter a URL and an empty directory.')
                return
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            amb = QProcessEnvironment.systemEnvironment()
            amb.insert('GIT_TERMINAL_PROMPT', '0')
            self.proc.setProcessEnvironment(amb)
            self.estado.setText('Cloning…')
            self.barco.show()
            self.botao.setEnabled(False)
            self.proc.start('git', ['clone', '--', url, dest])

        def terminou(self, codigo, _estado):
            self.barco.hide()
            self.botao.setEnabled(True)
            if codigo == 0:
                self.pasta = self.destino.text().strip()
                self.accept()
            else:
                erro = bytes(self.proc.readAllStandardError()).decode(errors='replace').strip().splitlines()
                self.estado.setText((erro[-1] if erro else 'Clone failed.')[:90])

        def cancelar(self):
            self.proc.kill()
            self.reject()

    class LinhaProjeto(QWidget):
        def __init__(self, caminho, direita=''):
            super().__init__()
            self.setAttribute(Qt.WA_TransparentForMouseEvents)
            h = QHBoxLayout(self)
            h.setContentsMargins(12, 5, 12, 5)
            h.setSpacing(12)
            cor = CORES_ICONE[int(hashlib.md5(caminho.name.encode()).hexdigest(), 16) % len(CORES_ICONE)]
            letra = QLabel(re.sub(r'[^A-Za-z0-9]', '', caminho.name)[:2].upper() or 'PR')
            letra.setFixedSize(20, 20)
            letra.setAlignment(Qt.AlignCenter)
            letra.setStyleSheet(f'background:{cor};color:#1E1F22;border-radius:4px;font-size:10px;font-weight:600;')
            t = QVBoxLayout()
            t.setSpacing(1)
            t.addWidget(QLabel(caminho.name))
            t.addWidget(rotulo(curto(caminho), 'mudo'))
            h.addWidget(letra, 0, Qt.AlignTop)
            h.addLayout(t, 1)
            if direita:
                h.addWidget(rotulo(direita, 'mudo'))

    class ListaProjetos(QListWidget):
        """Projetos recentes; `app` nulo mostra os de todos os apps."""

        def __init__(self, app=None):
            super().__init__()
            self.app = app
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
                cabeca = QListWidgetItem(self)
                cabeca.setFlags(Qt.NoItemFlags)
                cabeca.setSizeHint(QSize(0, 30))
                r = rotulo(titulo, 'secao')
                r.setContentsMargins(12, 8, 0, 0)
                self.setItemWidget(cabeca, r)
                for caminho, app in projetos:
                    item = QListWidgetItem(self)
                    item.setData(Qt.UserRole, (app, str(caminho)))
                    item.setSizeHint(QSize(0, 48))
                    self.setItemWidget(item, LinhaProjeto(caminho))
                    self.total += 1

        def ativar(self, item):
            if item.data(Qt.UserRole):
                abrir(*item.data(Qt.UserRole))

        def filtrar(self, texto):
            for i in range(self.count()):
                item = self.item(i)
                dados = item.data(Qt.UserRole)
                item.setHidden(bool(texto) and (not dados or texto.lower() not in dados[1].lower()))

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
                fila.addWidget(b)
            return fila

        def pagina_lista(self):
            p = QWidget()
            v = QVBoxLayout(p)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            topo = QHBoxLayout()
            topo.setContentsMargins(20, 12, 13, 12)
            busca = busca_linha()
            busca.textChanged.connect(self.lista.filtrar)
            topo.addWidget(busca, 1)
            topo.addLayout(self.botoes())
            v.addLayout(topo)
            v.addWidget(linha('linhaH'))
            caixa = QHBoxLayout()
            caixa.setContentsMargins(12, 8, 12, 8)
            caixa.addWidget(self.lista)
            v.addLayout(caixa, 1)
            return p

        def pagina_vazia(self):
            p = QWidget()
            v = QVBoxLayout(p)
            v.addStretch(1)
            v.addWidget(icone(self.app, 88), 0, Qt.AlignCenter)
            v.addSpacing(14)
            info = aplicativos()[self.app]
            for w in (rotulo(f'Welcome to {nome_app(self.app)}', 'grande'),
                      rotulo(info['description'], 'mudo'),
                      rotulo('Create a project, or open one from disk or version control.', 'mudo')):
                w.setAlignment(Qt.AlignCenter)
                v.addWidget(w)
            v.addSpacing(18)
            fila = QHBoxLayout()
            fila.addStretch(1)
            fila.addLayout(self.botoes())
            fila.addStretch(1)
            v.addLayout(fila)
            v.addStretch(2)
            return p

        def novo(self):
            d = NovoProjeto(self, self.app)
            if d.exec():
                abrir(self.app, d.projeto)

        def pasta(self):
            pasta = QFileDialog.getExistingDirectory(self, 'Open', str(PROJETOS if PROJETOS.is_dir() else CASA))
            if pasta:
                abrir(self.app, pasta)

        def clonar(self):
            d = Clonar(self, self.app)
            if d.exec():
                abrir(self.app, d.pasta)

    class Personalizar(QScrollArea):
        def __init__(self, app):
            super().__init__()
            self.app = app
            self.setWidgetResizable(True)
            info = aplicativos()[app]
            miolo = QWidget()
            miolo.setObjectName('pagina')
            v = QVBoxLayout(miolo)
            v.setContentsMargins(24, 22, 24, 22)
            v.setSpacing(9)
            v.addWidget(rotulo('Appearance', 'secao'))
            self.tema = Combo()
            self.tema.addItems(temas(app))
            atual = ajuste(app, 'workbench.colorTheme')
            if atual:
                if self.tema.findText(atual) < 0:
                    self.tema.addItem(atual)
                self.tema.setCurrentText(atual)
            self.tema.currentTextChanged.connect(lambda t: gravar_ajuste(app, 'workbench.colorTheme', t))
            self.fonte = Combo()
            self.fonte.addItems(['9', '10', '11', '12', '13', '14', '15', '16', '18', '20', '24', '28'])
            self.fonte.setCurrentText(str(ajuste(app, 'editor.fontSize') or 13))
            self.fonte.currentTextChanged.connect(lambda n: gravar_ajuste(app, 'editor.fontSize', int(n)))
            form = QFormLayout()
            form.setHorizontalSpacing(14)
            form.addRow('Theme:', self.tema)
            form.addRow('Editor font:', self.fonte)
            v.addLayout(form)
            self.caixa('Animations', 'animations', v)
            if info.get('base'):
                self.caixa('Visual extras: tree icons and app watermark (needs a local debugging port)', 'visual', v)
                self.forca = QSlider(Qt.Horizontal)
                self.forca.setRange(3, 40)
                self.forca.setValue(round(lembrar_fundo(app) * 100))
                self.forca.valueChanged.connect(lambda n: gravar_fundo_forca(app, n / 100))
                f2 = QFormLayout()
                f2.setHorizontalSpacing(14)
                f2.addRow('Wallpaper strength:', self.forca)
                v.addLayout(f2)
                v.addWidget(link('Choose wallpaper…', self.escolher_fundo))
                v.addWidget(link('Remove wallpaper', lambda: (ferramentas(app) / 'fundo.jpg').unlink(missing_ok=True)))
            v.addSpacing(8)
            v.addWidget(rotulo('Privacy', 'secao'))
            self.caixa('Allow editor telemetry', 'telemetry', v)
            self.caixa('Enable AI features', 'ai', v)
            if info.get('memory'):
                v.addSpacing(8)
                v.addWidget(rotulo('Performance', 'secao'))
                self.memoria = Combo()
                self.memoria.addItems(MEMORIAS)
                self.memoria.setCurrentText(opcao(app, 'memory'))
                self.memoria.currentTextChanged.connect(lambda t: gravar_opcao(app, 'memory', t))
                f3 = QFormLayout()
                f3.setHorizontalSpacing(14)
                f3.addRow('Java memory limit:', self.memoria)
                v.addLayout(f3)
            v.addSpacing(8)
            v.addWidget(rotulo('Import', 'secao'))
            v.addWidget(rotulo('Copies settings, shortcuts and snippets. The original stays untouched.', 'mudo'))
            fila = QHBoxLayout()
            for nome_, origem in origens_importacao():
                b = QPushButton(f'From {nome_}')
                b.setEnabled(origem.is_dir())
                b.clicked.connect(lambda _=False, o=origem, n=nome_: self.importar(o, n))
                fila.addWidget(b)
            fila.addStretch(1)
            v.addLayout(fila)
            v.addSpacing(8)
            v.addWidget(link('All settings…', lambda: abrir(app, comando_='workbench.action.openSettings')))
            v.addWidget(link('Keyboard shortcuts…', lambda: abrir(app, comando_='workbench.action.openGlobalKeybindings')))
            v.addStretch(1)
            v.addWidget(rotulo('Changes apply the next time the app opens.', 'mudo'))
            self.setWidget(miolo)

        def caixa(self, texto, chave, layout):
            c = QCheckBox(texto)
            c.setChecked(opcao(self.app, chave))
            c.toggled.connect(lambda n: gravar_opcao(self.app, chave, n))
            layout.addWidget(c)
            return c

        def escolher_fundo(self):
            arquivo, _ = QFileDialog.getOpenFileName(self, 'Background image', str(CASA), 'Images (*.jpg *.jpeg *.png *.webp *.bmp)')
            if arquivo and not gravar_fundo(arquivo, ferramentas(self.app)):
                QMessageBox.warning(self, 'Background image', 'Could not read this image.')

        def importar(self, origem, nome_):
            importar(self.app, origem)
            QMessageBox.information(self, 'Import', f'{nome_} settings copied to {nome_app(self.app)}.')

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
            for ident, nome, versao_, autor in plugins(app):
                item = QListWidgetItem(self.lista)
                item.setData(Qt.UserRole, nome.lower())
                item.setSizeHint(QSize(0, 46))
                w = QWidget()
                h = QHBoxLayout(w)
                h.setContentsMargins(20, 3, 16, 3)
                c = QVBoxLayout()
                c.setSpacing(1)
                c.addWidget(QLabel(nome))
                c.addWidget(rotulo(f'{autor}  ·  {versao_}', 'mudo'))
                h.addLayout(c, 1)
                ligado = QCheckBox('Enabled')
                ligado.setChecked(ident not in desligadas(app))
                if ident in obrigatorias:
                    ligado.setEnabled(False)
                    ligado.setToolTip(f'{nome_app(app)} needs this plugin.')
                ligado.toggled.connect(lambda n, i=ident: alternar_extensao(app, i, n))
                h.addWidget(ligado)
                self.lista.setItemWidget(item, w)
            v.addWidget(self.lista, 1)
            busca.textChanged.connect(self.filtrar)

        def filtrar(self, texto):
            for i in range(self.lista.count()):
                item = self.lista.item(i)
                item.setHidden(texto.lower() not in item.data(Qt.UserRole))

    class Aprender(QWidget):
        ATALHOS = (
            ('Search Everywhere', 'Shift Shift'), ('Run', 'Shift+F10'), ('Debug', 'Shift+F9'), ('Rerun', 'Ctrl+5'),
            ('Stop', 'Ctrl+2'), ('Build', 'Ctrl+9'), ('Toggle Breakpoint', 'Ctrl+8'), ('Step Over', 'F8'),
            ('Step Into', 'F7'), ('Resume', 'F9'), ('Context Actions', 'Alt+Enter'), ('Generate', 'Alt+Insert'),
            ('Rename', 'Shift+F6'), ('File Structure', 'Ctrl+0'), ('Recent Files', 'Ctrl+E'), ('Terminal', 'Alt+F12'),
        )

        def __init__(self, app):
            super().__init__()
            self.setObjectName('pagina')
            info = aplicativos()[app]
            v = QVBoxLayout(self)
            v.setContentsMargins(24, 22, 24, 22)
            v.setSpacing(8)
            v.addWidget(rotulo(f"Learn {info['title']}", 'secao'))
            for texto, url in info.get('learn', []):
                v.addWidget(link(texto, lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u))))
            if info.get('base'):
                v.addSpacing(10)
                v.addWidget(rotulo('Help', 'secao'))
                v.addWidget(link('Keymap Reference', self.atalhos))
            v.addStretch(1)

        def atalhos(self):
            d = QDialog(self)
            d.setWindowTitle('Keymap Reference')
            d.resize(420, 560)
            t = QTableWidget(len(self.ATALHOS), 2)
            t.setHorizontalHeaderLabels(['Action', 'Shortcut'])
            t.verticalHeader().hide()
            t.horizontalHeader().setStretchLastSection(True)
            t.setColumnWidth(0, 220)
            t.setEditTriggers(QTableWidget.NoEditTriggers)
            for i, (acao, tecla) in enumerate(self.ATALHOS):
                t.setItem(i, 0, QTableWidgetItem(acao))
                t.setItem(i, 1, QTableWidgetItem(tecla))
            QVBoxLayout(d).addWidget(t)
            d.exec()

    class Boasvindas(Raiz):
        """Tela de início de cada app, com o que é específico dele."""

        def __init__(self, app, painel=None):
            super().__init__()
            self.setObjectName('raiz')
            self.painel = painel
            self.app = app
            self.setWindowTitle(f'Welcome to {nome_app(app)}')
            self.setWindowIcon(QIcon(str(ASSETS / f'{app}.svg')))
            com_vidro(self)
            self.setStyleSheet(estilo(aplicativos()[app].get('accent', AZUL)))
            self.resize(820, 650)
            self.setAcceptDrops(True)
            self.paginas = Troca()
            self.abas = {}
            grupo = QButtonGroup(self)
            esquerda = QWidget()
            esquerda.setFixedWidth(225)
            e = QVBoxLayout(esquerda)
            e.setContentsMargins(12, 18, 12, 14)
            e.setSpacing(4)
            topo = QHBoxLayout()
            topo.setContentsMargins(4, 0, 0, 12)
            topo.setSpacing(10)
            nome = QVBoxLayout()
            nome.setSpacing(0)
            nome.addWidget(QLabel(nome_app(app)))
            nome.addWidget(rotulo(versao_editor(), 'mudo'))
            topo.addWidget(icone(app, 30))
            topo.addLayout(nome, 1)
            e.addLayout(topo)
            for titulo, pagina in (('Projects', Projetos(app)), ('Customize', Personalizar(app)),
                                   ('Plugins', Plugins(app)), ('Learn', Aprender(app))):
                b = QPushButton(titulo)
                b.setObjectName('aba')
                b.setCheckable(True)
                b.clicked.connect(lambda _=False, w=pagina: self.paginas.ir(w))
                grupo.addButton(b)
                e.addWidget(b)
                self.abas[titulo] = b
                self.paginas.addWidget(pagina)
            self.abas['Projects'].setChecked(True)
            e.addStretch(1)
            voltar = QPushButton('Back to Hub')
            voltar.clicked.connect(self.voltar)
            e.addWidget(voltar, 0, Qt.AlignLeft)
            h = QHBoxLayout(self)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(0)
            h.addWidget(esquerda)
            h.addWidget(linha('linhaV'))
            h.addWidget(self.paginas, 1)

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
        """Linha de um app no painel: clique abre, os três pontos mostram as ações."""

        def __init__(self, app, painel):
            super().__init__()
            self.setObjectName('ferramenta')
            self.setCursor(Qt.PointingHandCursor)
            self.app = app
            self.painel = painel
            info = aplicativos()[app]
            h = QHBoxLayout(self)
            h.setContentsMargins(10, 8, 6, 8)
            h.setSpacing(12)
            t = QVBoxLayout()
            t.setSpacing(1)
            t.addWidget(rotulo(info['title'], 'titulo'))
            t.addWidget(rotulo(versao_editor(), 'mudo'))
            h.addWidget(icone(app, 38))
            h.addLayout(t, 1)
            self.mais = QToolButton()
            self.mais.setText('⋯')
            self.mais.setCursor(Qt.ArrowCursor)
            self.mais.setFixedSize(26, 26)
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
            h.addWidget(self.mais)
            self.mais.setVisible(False)

        def enterEvent(self, _):
            self.mais.setVisible(True)

        def leaveEvent(self, _):
            self.mais.setVisible(self.mais.menu().isVisible())

        def mouseReleaseEvent(self, e):
            if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
                self.painel.boasvindas(self.app)

    class Painel(Raiz):
        """Janela principal: lista os apps e guarda só o que vale para todos."""

        def __init__(self):
            super().__init__()
            self.setObjectName('raiz')
            com_vidro(self)
            b = marca()
            self.setWindowTitle(b['hub'])
            self.setFixedWidth(400)
            self.resize(400, 620)
            self.tela = None
            self.miolo = Troca()
            self.ferramentas = self.pagina_ferramentas()
            self.lista = ListaProjetos()
            self.projetos = self.pagina_projetos()
            self.gerais = self.pagina_gerais()
            for p in (self.ferramentas, self.projetos, self.gerais):
                self.miolo.addWidget(p)
            v = QVBoxLayout(self)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            topo = QHBoxLayout()
            topo.setContentsMargins(14, 10, 10, 0)
            topo.setSpacing(16)
            topo.addWidget(icone('hub', 24), 0, Qt.AlignVCenter)
            self.guias = {}
            grupo = QButtonGroup(self)
            for titulo, pagina in (('Tools', self.ferramentas), ('Projects', self.projetos)):
                g = QPushButton(titulo)
                g.setObjectName('guia')
                g.setCheckable(True)
                g.clicked.connect(lambda _=False, w=pagina: self.miolo.ir(w))
                grupo.addButton(g)
                topo.addWidget(g)
                self.guias[titulo] = g
            self.guias['Tools'].setChecked(True)
            topo.addStretch(1)
            ajuste_ = QToolButton()
            ajuste_.setIcon(QIcon(str(ASSETS / 'engrenagem.svg')))
            ajuste_.setIconSize(QSize(18, 18))
            ajuste_.setToolTip('Settings')
            ajuste_.clicked.connect(lambda: self.miolo.ir(self.gerais))
            topo.addWidget(ajuste_)
            v.addLayout(topo)
            v.addWidget(linha('linhaH'))
            v.addWidget(self.miolo, 1)

        def pagina_ferramentas(self):
            p = QWidget()
            p.setObjectName('pagina')
            v = QVBoxLayout(p)
            v.setContentsMargins(10, 14, 10, 12)
            v.setSpacing(2)
            r = rotulo('Installed', 'mudo')
            r.setContentsMargins(10, 0, 0, 6)
            v.addWidget(r)
            for app in aplicativos():
                v.addWidget(Ferramenta(app, self))
            v.addStretch(1)
            return p

        def pagina_projetos(self):
            p = QWidget()
            p.setObjectName('pagina')
            v = QVBoxLayout(p)
            v.setContentsMargins(10, 8, 10, 8)
            busca = busca_linha()
            busca.textChanged.connect(self.lista.filtrar)
            v.addWidget(busca)
            v.addWidget(self.lista, 1)
            return p

        def pagina_gerais(self):
            p = QWidget()
            p.setObjectName('pagina')
            v = QVBoxLayout(p)
            v.setContentsMargins(18, 14, 18, 14)
            v.setSpacing(9)
            v.addWidget(rotulo('Settings', 'grande'))
            v.addSpacing(4)
            v.addWidget(rotulo('Trusted folders', 'secao'))
            d = rotulo('Projects in these folders open with every feature on, without a prompt. Applies to all apps.', 'mudo')
            d.setWordWrap(True)
            v.addWidget(d)
            self.confiaveis = QListWidget()
            self.confiaveis.setFixedHeight(110)
            v.addWidget(self.confiaveis)
            fila = QHBoxLayout()
            for texto, acao in (('Add…', self.adicionar), ('Remove', self.retirar)):
                b = QPushButton(texto)
                b.clicked.connect(acao)
                fila.addWidget(b)
            fila.addStretch(1)
            v.addLayout(fila)
            v.addSpacing(8)
            v.addWidget(rotulo('Appearance', 'secao'))
            for texto, chave in (('Window blur', 'blur'), ('Transitions and boat animation', 'transitions')):
                c = QCheckBox(texto)
                c.setChecked(opcoes().get(chave, True))
                c.toggled.connect(lambda n, k=chave: gravar_geral(k, n))
                v.addWidget(c)
            v.addSpacing(8)
            v.addWidget(rotulo('Shortcuts', 'secao'))
            atalho_ = QPushButton(f"Add {marca()['hub']} to Desktop")
            atalho_.clicked.connect(lambda: self.atalho(None))
            v.addWidget(atalho_, 0, Qt.AlignLeft)
            v.addStretch(1)
            v.addWidget(rotulo(f"{marca()['name']}  ·  Editor {versao_editor()}", 'mudo'))
            self.listar()
            return p

        def listar(self):
            self.confiaveis.clear()
            self.confiaveis.addItems([str(p) for p in pastas_confiaveis()])

        def adicionar(self):
            pasta = QFileDialog.getExistingDirectory(self, 'Trust Folder', str(CASA))
            if pasta:
                confiar(pasta)
                self.listar()

        def retirar(self):
            item = self.confiaveis.currentItem()
            if item:
                retirar_confianca(item.text())
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
                criar_atalho(app)
                QMessageBox.information(self, 'Desktop shortcut', f'Added {nome_app(app) if app else marca()["hub"]} to the desktop.')
            except OSError as e:
                QMessageBox.warning(self, 'Desktop shortcut', f'Could not create the shortcut: {e}')

    aplicacao = QApplication(sys.argv)
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
        for nome, pagina in (('tools', p.ferramentas), ('projects', p.projetos), ('settings', p.gerais)):
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
            s = Partida(app, f'Starting {nome_app(app)}…')
            s.show()
            aplicacao.processEvents()
            s.grab().save(str(destino / f'{app}-partida.png'))
            s.close()
        return 0
    j = Boasvindas(inicial) if inicial else Painel()
    surgir(j)
    return aplicacao.exec()


def main():
    args = sys.argv[1:]
    if args[:1] == ['--open']:
        porta = int(args[args.index('--port') + 1]) if '--port' in args else None
        alvos = [a for a in args[2:] if a != '--port' and a != str(porta)]
        processo = abrir_app(args[1], alvos, porta)
        print(processo.pid)
        return 0
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
    return janela()


if __name__ == '__main__':
    sys.exit(main())
