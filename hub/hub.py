"""Hub of the suite: opens each profile and keeps its settings."""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

JANELAS = sys.platform == 'win32'
RAIZ = Path(os.environ.get('SUITE_ROOT') or (sys.executable if getattr(sys, 'frozen', False) else __file__)).resolve()
RAIZ = RAIZ if RAIZ.is_dir() else RAIZ.parent
DADOS = RAIZ / 'data'
PERFIS = RAIZ / 'profiles'
FERRAMENTAS = DADOS / 'tools'
OPCOES = DADOS / 'hub.json'
ASSETS = RAIZ / 'assets'
CASA = Path.home()
PROJETOS = CASA / 'Projects'
MEMORIAS = ['768M', '1G', '2G', '3G']
PADRAO = {'telemetry': False, 'ai': False, 'visual': True, 'memory': '1G'}
CORES_ICONE = ['#A9C27F', '#C77DBB', '#6AAB73', '#56A8F5', '#E8A33D', '#F75464', '#9B8AE3']


def marca():
    try:
        return json.loads((RAIZ / 'brand.json').read_text(encoding='utf8'))
    except (OSError, ValueError):
        return {'name': 'Code Suite', 'hub': 'Code Suite Hub', 'tagline': '', 'folder': '.code-suite'}


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
    FERRAMENTAS.mkdir(parents=True, exist_ok=True)
    arquivo = usuario / 'settings.json'
    atual = ler_json(arquivo) if arquivo.exists() else {}
    base = modelo(app)
    for chave, valor in base.items():
        if chave not in atual or '${SUITE}' in json.dumps(valor):
            atual[chave] = caminhos(valor)
    atual['telemetry.telemetryLevel'] = 'all' if opcao(app, 'telemetry') else 'off'
    atual['chat.disableAIFeatures'] = not opcao(app, 'ai')
    atual['update.mode'] = 'none'
    if aplicativos()[app].get('base'):
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
    return RAIZ / 'editor' / ('Code.exe' if JANELAS else 'code')


def ripgrep():
    pasta = 'win32-x64/rg.exe' if JANELAS else 'linux-x64/rg'
    return RAIZ / 'editor/resources/app/node_modules.asar.unpacked/@vscode/ripgrep-universal/bin' / pasta


def node():
    return RAIZ / 'node' / ('node.exe' if JANELAS else 'bin/node')


def comando(app, alvos=(), porta=None):
    visual = opcao(app, 'visual') and aplicativos()[app].get('base')
    args = [str(editor()), f"--user-data-dir={DADOS / app / 'user'}", f"--extensions-dir={DADOS / app / 'extensions'}"]
    if not JANELAS:
        args.append('--ozone-platform=x11')
    if porta or visual:
        args.append(f'--remote-debugging-port={porta or 0}')
    return args + [str(a) for a in alvos]


def ambiente(app):
    amb = {**os.environ, 'SUITE_TOOLS': str(FERRAMENTAS), 'SUITE_VISUAL': '1' if opcao(app, 'visual') else '0'}
    if node().exists():
        amb['SUITE_NODE'] = str(node())
    amb.pop('SUITE_ROOT', None)
    return amb


def abrir_app(app, alvos=(), porta=None):
    preparar(app)
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


def recentes():
    vistos = {p['path']: p['app'] for p in opcoes().get('recent', [])}
    for app in aplicativos():
        for w in (pasta_usuario(app) / 'workspaceStorage').glob('*/workspace.json'):
            try:
                u = urlparse(json.loads(w.read_text(encoding='utf8'))['folder'])
                if u.scheme == 'file':
                    vistos.setdefault(unquote(u.path).lstrip('/') if JANELAS else unquote(u.path), app)
            except (OSError, KeyError, ValueError):
                pass
    return [(Path(p), a) for p, a in vistos.items() if Path(p).is_dir()]


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


def criar_projeto(app, modelo_, nome, local):
    raiz = Path(local) / nome
    shutil.copytree(PERFIS / app / 'templates' / modelo_, raiz)
    if not confiavel(raiz):
        confiar(raiz)
    return raiz


def janela():
    from PySide6.QtCore import QSize, Qt, QUrl
    from PySide6.QtGui import QDesktopServices, QFontDatabase, QIcon
    from PySide6.QtWidgets import (
        QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QGridLayout,
        QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QStackedWidget,
        QVBoxLayout, QWidget,
    )

    ESTILO = """
    * { font-family: 'Inter', 'Segoe UI', 'Noto Sans', sans-serif; font-size: 13px; color: #DFE1E5; }
    QWidget#raiz, QWidget#pagina, QStackedWidget { background: #1E1F22; border: none; }
    QDialog, QMenu { background: #2B2D30; }
    QFrame#linhaV, QFrame#linhaH { background: #393B40; border: none; }
    QLabel#mudo { color: #868A91; font-size: 12px; }
    QLabel#titulo { font-size: 14px; font-weight: 600; }
    QLabel#grande { font-size: 20px; font-weight: 600; }
    QLabel#secao { font-weight: 600; }
    QPushButton { background: transparent; border: 1px solid #4E5157; border-radius: 4px; padding: 5px 13px; }
    QPushButton:hover { background: #2B2D30; }
    QPushButton#azul { background: #3574F0; border-color: #3574F0; color: #FFFFFF; }
    QPushButton#aba { border: none; border-radius: 4px; text-align: left; padding: 7px 23px; }
    QPushButton#aba:hover { background: #2B2D30; }
    QPushButton#aba:checked { background: #2E436E; }
    QLineEdit, QComboBox { background: #2B2D30; border: 1px solid #4E5157; border-radius: 4px; padding: 4px 7px; }
    QLineEdit:focus, QComboBox:focus { border-color: #3574F0; }
    QComboBox::drop-down { border: none; width: 22px; }
    QComboBox::down-arrow { image: url(SETA); }
    QComboBox QAbstractItemView { background: #2B2D30; selection-background-color: #2E436E; }
    QListWidget { background: transparent; border: none; outline: 0; }
    QListWidget::item { border-radius: 4px; }
    QListWidget::item:hover { background: #2B2D30; }
    QFrame#cartao { background: #2B2D30; border-radius: 8px; }
    QCheckBox { spacing: 7px; }
    QScrollBar:vertical { background: transparent; width: 8px; }
    QScrollBar::handle:vertical { background: #4E5157; border-radius: 4px; min-height: 24px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    """

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

    class Combo(QComboBox):
        def wheelEvent(self, evento):
            evento.ignore()

    class Apps(QWidget):
        def __init__(self, janela_):
            super().__init__()
            self.setObjectName('pagina')
            v = QVBoxLayout(self)
            v.setContentsMargins(24, 22, 24, 22)
            v.setSpacing(12)
            v.addWidget(rotulo('Apps', 'grande'))
            grade = QGridLayout()
            grade.setSpacing(12)
            for i, (app, info) in enumerate(aplicativos().items()):
                c = QFrame()
                c.setObjectName('cartao')
                h = QHBoxLayout(c)
                h.setContentsMargins(16, 14, 16, 14)
                h.setSpacing(14)
                t = QVBoxLayout()
                t.setSpacing(3)
                t.addWidget(rotulo(info['title'], 'titulo'))
                t.addWidget(rotulo(info['description'], 'mudo'))
                ir = QPushButton('Open')
                ir.setObjectName('azul')
                ir.clicked.connect(lambda _=False, a=app: abrir(a))
                ajuste = QPushButton('Settings')
                ajuste.clicked.connect(lambda _=False, a=app: janela_.ajustes_de(a))
                h.addWidget(icone(app, 44))
                h.addLayout(t, 1)
                h.addWidget(ajuste)
                h.addWidget(ir)
                grade.addWidget(c, i, 0)
            v.addLayout(grade)
            v.addStretch(1)

    class NovoProjeto(QDialog):
        def __init__(self, pai):
            super().__init__(pai)
            self.setWindowTitle('New Project')
            self.setMinimumWidth(460)
            self.resultado = None
            self.modelo = Combo()
            for app, info in aplicativos().items():
                for m in info.get('templates', []):
                    self.modelo.addItem(f"{info['title']}: {m}", (app, m))
            self.nome = QLineEdit('untitled')
            self.nome.selectAll()
            self.local = QLineEdit(str(PROJETOS))
            pasta = QPushButton('Browse…')
            pasta.clicked.connect(self.escolher)
            fila = QHBoxLayout()
            fila.addWidget(self.local)
            fila.addWidget(pasta)
            self.erro = rotulo('', 'mudo')
            criar = QPushButton('Create')
            criar.setObjectName('azul')
            criar.setDefault(True)
            criar.clicked.connect(self.criar)
            cancelar = QPushButton('Cancel')
            cancelar.clicked.connect(self.reject)
            form = QFormLayout()
            form.addRow('Template:', self.modelo)
            form.addRow('Name:', self.nome)
            form.addRow('Location:', fila)
            rodape = QHBoxLayout()
            rodape.addWidget(self.erro, 1)
            rodape.addWidget(cancelar)
            rodape.addWidget(criar)
            v = QVBoxLayout(self)
            v.addLayout(form)
            v.addSpacing(10)
            v.addLayout(rodape)

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
                app, m = self.modelo.currentData()
                self.resultado = app, criar_projeto(app, m, nome, local)
                self.accept()

    class Projetos(QWidget):
        def __init__(self):
            super().__init__()
            self.setObjectName('pagina')
            v = QVBoxLayout(self)
            v.setContentsMargins(24, 22, 24, 12)
            v.setSpacing(10)
            topo = QHBoxLayout()
            topo.addWidget(rotulo('Projects', 'grande'), 1)
            for texto, acao in (('New Project', self.novo), ('Open Folder', self.pasta)):
                b = QPushButton(texto)
                b.clicked.connect(acao)
                topo.addWidget(b)
            v.addLayout(topo)
            self.vazio = rotulo('Create a project or open a folder to start.', 'mudo')
            v.addWidget(self.vazio)
            self.lista = QListWidget()
            self.lista.itemClicked.connect(lambda i: abrir(*i.data(Qt.UserRole)))
            v.addWidget(self.lista, 1)
            self.recarregar()

        def recarregar(self):
            self.lista.clear()
            todos = recentes()
            self.vazio.setVisible(not todos)
            for caminho, app in todos:
                item = QListWidgetItem(self.lista)
                item.setData(Qt.UserRole, (app, str(caminho)))
                item.setSizeHint(QSize(0, 48))
                w = QWidget()
                w.setAttribute(Qt.WA_TransparentForMouseEvents)
                h = QHBoxLayout(w)
                h.setContentsMargins(10, 5, 10, 5)
                h.setSpacing(12)
                cor = CORES_ICONE[int(hashlib.md5(caminho.name.encode()).hexdigest(), 16) % len(CORES_ICONE)]
                letra = QLabel(re.sub(r'[^A-Za-z0-9]', '', caminho.name)[:2].upper() or 'PR')
                letra.setFixedSize(20, 20)
                letra.setAlignment(Qt.AlignCenter)
                letra.setStyleSheet(f'background:{cor};color:#1E1F22;border-radius:4px;font-size:10px;font-weight:600;')
                t = QVBoxLayout()
                t.setSpacing(1)
                t.addWidget(QLabel(caminho.name))
                t.addWidget(rotulo(str(caminho), 'mudo'))
                h.addWidget(letra, 0, Qt.AlignTop)
                h.addLayout(t, 1)
                h.addWidget(rotulo(aplicativos()[app]['title'], 'mudo'))
                self.lista.setItemWidget(item, w)

        def novo(self):
            d = NovoProjeto(self)
            if d.exec():
                abrir(*d.resultado)

        def pasta(self):
            pasta = QFileDialog.getExistingDirectory(self, 'Open Folder', str(CASA))
            if not pasta:
                return
            nomes = list(aplicativos())
            web = any(Path(pasta).glob(p) for p in ('*.html', 'package.json', '*.js', '*.ts'))
            abrir('web' if web and 'web' in nomes else nomes[0], pasta)

    class Ajustes(QWidget):
        def __init__(self):
            super().__init__()
            self.setObjectName('pagina')
            v = QVBoxLayout(self)
            v.setContentsMargins(24, 22, 24, 22)
            v.setSpacing(10)
            v.addWidget(rotulo('Settings', 'grande'))
            self.app = Combo()
            for app, info in aplicativos().items():
                self.app.addItem(info['title'], app)
            form = QFormLayout()
            form.setHorizontalSpacing(14)
            form.addRow('App:', self.app)
            v.addLayout(form)
            v.addSpacing(6)
            v.addWidget(rotulo('Privacy', 'secao'))
            self.telemetria = QCheckBox('Allow editor telemetry')
            self.ia = QCheckBox('Enable AI features')
            v.addWidget(self.telemetria)
            v.addWidget(self.ia)
            v.addSpacing(6)
            v.addWidget(rotulo('Appearance', 'secao'))
            self.visual = QCheckBox('Visual extras (needs a local debugging port)')
            v.addWidget(self.visual)
            v.addWidget(rotulo('Tree icons, background image and the configuration selector label.', 'mudo'))
            v.addSpacing(6)
            self.memoria = Combo()
            self.memoria.addItems(MEMORIAS)
            self.caixa = QWidget()
            f2 = QFormLayout(self.caixa)
            f2.setContentsMargins(0, 0, 0, 0)
            f2.addRow('Java memory limit:', self.memoria)
            v.addWidget(self.caixa)
            v.addSpacing(6)
            v.addWidget(rotulo('Trusted folders', 'secao'))
            v.addWidget(rotulo('Projects in these folders open with every feature on, without a prompt. Applies to all apps.', 'mudo'))
            self.confiaveis = QListWidget()
            self.confiaveis.setFixedHeight(64)
            fila_c = QHBoxLayout()
            fila_c.addWidget(self.confiaveis, 1)
            botoes_c = QVBoxLayout()
            for texto, acao in (('Add…', self.adicionar), ('Remove', self.retirar)):
                b = QPushButton(texto)
                b.clicked.connect(acao)
                botoes_c.addWidget(b)
            botoes_c.addStretch(1)
            fila_c.addLayout(botoes_c)
            v.addLayout(fila_c)
            v.addSpacing(6)
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
            v.addStretch(1)
            v.addWidget(rotulo('Changes apply the next time the app opens.', 'mudo'))
            self.app.currentIndexChanged.connect(self.carregar)
            self.telemetria.toggled.connect(lambda n: self.gravar('telemetry', n))
            self.ia.toggled.connect(lambda n: self.gravar('ai', n))
            self.visual.toggled.connect(lambda n: self.gravar('visual', n))
            self.memoria.currentTextChanged.connect(lambda t: self.gravar('memory', t))
            self.pronto = False
            self.carregar()
            self.listar()

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

        def atual(self):
            return self.app.currentData()

        def carregar(self):
            self.pronto = False
            app = self.atual()
            info = aplicativos()[app]
            self.telemetria.setChecked(opcao(app, 'telemetry'))
            self.ia.setChecked(opcao(app, 'ai'))
            self.visual.setChecked(opcao(app, 'visual'))
            self.visual.setEnabled(bool(info.get('base')))
            self.memoria.setCurrentText(opcao(app, 'memory'))
            self.caixa.setVisible(bool(info.get('memory')))
            self.pronto = True

        def gravar(self, chave, valor):
            if self.pronto:
                gravar_opcao(self.atual(), chave, valor)

        def importar(self, origem, nome_):
            importar(self.atual(), origem)
            QMessageBox.information(self, 'Import', f'{nome_} settings copied to {self.app.currentText()}.')

    class Janela(QWidget):
        def __init__(self):
            super().__init__()
            self.setObjectName('raiz')
            b = marca()
            self.setWindowTitle(b['hub'])
            self.resize(860, 700)
            self.paginas = QStackedWidget()
            self.ajustes = Ajustes()
            self.abas = {}
            grupo = QButtonGroup(self)
            esquerda = QWidget()
            esquerda.setFixedWidth(215)
            e = QVBoxLayout(esquerda)
            e.setContentsMargins(12, 18, 12, 14)
            e.setSpacing(4)
            topo = QHBoxLayout()
            topo.setContentsMargins(4, 0, 0, 12)
            topo.setSpacing(10)
            nome = QVBoxLayout()
            nome.setSpacing(0)
            nome.addWidget(QLabel(b['name']))
            nome.addWidget(rotulo(f'Editor {versao_editor()}', 'mudo'))
            topo.addWidget(icone('hub', 28))
            topo.addLayout(nome, 1)
            e.addLayout(topo)
            for titulo, pagina in (('Apps', Apps(self)), ('Projects', Projetos()), ('Settings', self.ajustes)):
                bt = QPushButton(titulo)
                bt.setObjectName('aba')
                bt.setCheckable(True)
                bt.clicked.connect(lambda _=False, w=pagina: self.paginas.setCurrentWidget(w))
                grupo.addButton(bt)
                e.addWidget(bt)
                self.abas[titulo] = bt
                self.paginas.addWidget(pagina)
            self.abas['Apps'].setChecked(True)
            e.addStretch(1)
            h = QHBoxLayout(self)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(0)
            h.addWidget(esquerda)
            h.addWidget(linha('linhaV'))
            h.addWidget(self.paginas, 1)

        def ajustes_de(self, app):
            self.ajustes.app.setCurrentIndex(self.ajustes.app.findData(app))
            self.abas['Settings'].click()

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

    def abrir(app, *alvos):
        if alvos and not pode_abrir(alvos[0]):
            return
        abrir_app(app, alvos)
        QApplication.quit()

    aplicacao = QApplication(sys.argv)
    aplicacao.setApplicationName(marca()['hub'])
    aplicacao.setStyle('Fusion')
    for f in ASSETS.glob('*.[to]tf'):
        QFontDatabase.addApplicationFont(str(f))
    aplicacao.setStyleSheet(ESTILO.replace('SETA', (ASSETS / 'seta.svg').as_posix()))
    aplicacao.setWindowIcon(QIcon(str(ASSETS / 'hub.svg')))
    j = Janela()
    if '--shots' in sys.argv:
        destino = Path(sys.argv[sys.argv.index('--shots') + 1])
        for titulo in j.abas:
            j.abas[titulo].click()
            j.show()
            aplicacao.processEvents()
            j.grab().save(str(destino / f'hub-{titulo.lower()}.png'))
        return 0
    j.show()
    return aplicacao.exec()


def main():
    args = sys.argv[1:]
    if args[:1] == ['--open']:
        porta = int(args[args.index('--port') + 1]) if '--port' in args else None
        alvos = [a for a in args[2:] if a != '--port' and a != str(porta)]
        processo = abrir_app(args[1], alvos, porta)
        print(processo.pid)
        return 0
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
