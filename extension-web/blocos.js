// Insert Block: plain HTML pieces that go in as snippets, with their CSS added to the page's stylesheet.

const BLOCOS = [
    {
        nome: 'Navigation',
        detalhe: 'Site name and links',
        html: [
            '<header class="site-nav">',
            '  <a class="site-nav-name" href="/">${1:Site name}</a>',
            '  <nav>',
            '    <a href="#${2:about}">${3:About}</a>',
            '    <a href="#${4:work}">${5:Work}</a>',
            '    <a href="#${6:contact}">${7:Contact}</a>',
            '  </nav>',
            '</header>',
            '$0',
        ],
        css: `.site-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 24px;
  border-bottom: 1px solid #ddd;
}
.site-nav-name {
  font-weight: 600;
  color: inherit;
  text-decoration: none;
}
.site-nav nav {
  display: flex;
  gap: 20px;
}
.site-nav nav a {
  color: inherit;
}`,
    },
    {
        nome: 'Hero',
        detalhe: 'Heading, text and a link',
        html: [
            '<section class="hero">',
            '  <h1>${1:Heading}</h1>',
            '  <p>${2:One or two sentences about the page.}</p>',
            '  <a class="hero-link" href="${3:#}">${4:Call to action}</a>',
            '</section>',
            '$0',
        ],
        css: `.hero {
  max-width: 720px;
  padding: 64px 24px;
}
.hero h1 {
  margin: 0 0 12px;
  font-size: 2.5rem;
  line-height: 1.15;
}
.hero p {
  margin: 0 0 24px;
  font-size: 1.125rem;
}
.hero-link {
  display: inline-block;
  padding: 10px 18px;
  border: 1px solid currentColor;
  border-radius: 4px;
  color: inherit;
  text-decoration: none;
}`,
    },
    {
        nome: 'Cards',
        detalhe: 'Three cards in a row',
        html: [
            '<section class="cards">',
            '  <article class="card">',
            '    <h3>${1:First}</h3>',
            '    <p>${2:Short text.}</p>',
            '  </article>',
            '  <article class="card">',
            '    <h3>${3:Second}</h3>',
            '    <p>${4:Short text.}</p>',
            '  </article>',
            '  <article class="card">',
            '    <h3>${5:Third}</h3>',
            '    <p>${6:Short text.}</p>',
            '  </article>',
            '</section>',
            '$0',
        ],
        css: `.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  padding: 24px;
}
.card {
  padding: 16px;
  border: 1px solid #ddd;
  border-radius: 4px;
}
.card h3 {
  margin: 0 0 8px;
}
.card p {
  margin: 0;
}`,
    },
    {
        nome: 'Card with image',
        detalhe: 'Image, title and text',
        html: [
            '<article class="media-card">',
            '  <img src="${1:image.jpg}" alt="${2:Describe the image}">',
            '  <div class="media-card-body">',
            '    <h3>${3:Title}</h3>',
            '    <p>${4:Short text.}</p>',
            '  </div>',
            '</article>',
            '$0',
        ],
        css: `.media-card {
  max-width: 320px;
  border: 1px solid #ddd;
  border-radius: 4px;
  overflow: hidden;
}
.media-card img {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
}
.media-card-body {
  padding: 12px 16px 16px;
}
.media-card-body h3 {
  margin: 0 0 6px;
}
.media-card-body p {
  margin: 0;
}`,
    },
    {
        nome: 'Gallery',
        detalhe: 'Grid of images',
        html: [
            '<section class="gallery">',
            '  <img src="${1:photo-1.jpg}" alt="${2:}">',
            '  <img src="${3:photo-2.jpg}" alt="${4:}">',
            '  <img src="${5:photo-3.jpg}" alt="${6:}">',
            '  <img src="${7:photo-4.jpg}" alt="${8:}">',
            '</section>',
            '$0',
        ],
        css: `.gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 8px;
  padding: 24px;
}
.gallery img {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
}`,
    },
    {
        nome: 'Contact form',
        detalhe: 'Name, email and message',
        html: [
            '<form class="contact-form" action="${1:#}" method="post">',
            '  <label>',
            '    Name',
            '    <input name="name" autocomplete="name" required>',
            '  </label>',
            '  <label>',
            '    Email',
            '    <input name="email" type="email" autocomplete="email" required>',
            '  </label>',
            '  <label>',
            '    Message',
            '    <textarea name="message" rows="5" required></textarea>',
            '  </label>',
            '  <button type="submit">${2:Send}</button>',
            '</form>',
            '$0',
        ],
        css: `.contact-form {
  display: grid;
  gap: 12px;
  max-width: 480px;
  padding: 24px;
}
.contact-form label {
  display: grid;
  gap: 4px;
}
.contact-form input,
.contact-form textarea {
  padding: 8px;
  border: 1px solid #bbb;
  border-radius: 4px;
  font: inherit;
}
.contact-form button {
  justify-self: start;
  padding: 8px 16px;
  font: inherit;
}`,
    },
    {
        nome: 'Two columns',
        detalhe: 'Side by side, stacked on phones',
        html: [
            '<section class="two-columns">',
            '  <div>',
            '    ${1:Left column}',
            '  </div>',
            '  <div>',
            '    ${2:Right column}',
            '  </div>',
            '</section>',
            '$0',
        ],
        css: `.two-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  padding: 24px;
}
@media (max-width: 640px) {
  .two-columns {
    grid-template-columns: 1fr;
  }
}`,
    },
    {
        nome: 'Footer',
        detalhe: 'Copyright and links',
        html: [
            '<footer class="site-footer">',
            '  <p>&copy; ${1:2026} ${2:Your name}</p>',
            '  <nav>',
            '    <a href="${3:#}">${4:Privacy}</a>',
            '    <a href="${5:#}">${6:Contact}</a>',
            '  </nav>',
            '</footer>',
            '$0',
        ],
        css: `.site-footer {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 12px;
  padding: 24px;
  border-top: 1px solid #ddd;
  font-size: 0.875rem;
}
.site-footer p {
  margin: 0;
}
.site-footer nav {
  display: flex;
  gap: 16px;
}
.site-footer a {
  color: inherit;
}`,
    },
];

const cssDoBloco = b => `/* Block: ${b.nome} */\n${b.css}\n`;

/** The stylesheet the page links to (first local one), else style.css beside it. */
function folhaDaPagina(texto, pastaPagina, path) {
    for (const m of texto.matchAll(/<link\b[^>]*>/gi)) {
        if (!/rel\s*=\s*["']?stylesheet/i.test(m[0])) continue;
        const href = /href\s*=\s*["']?([^"'\s>]+)/i.exec(m[0])?.[1];
        if (href && !/^([a-z]+:)?\/\//i.test(href)) return path.join(pastaPagina, href.split(/[?#]/)[0].replace(/^\//, ''));
    }
    return path.join(pastaPagina, 'style.css');
}

async function inserirBloco() {
    const vscode = require('vscode');
    const path = require('path');
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'html') {
        return vscode.window.showInformationMessage('Open an HTML file to insert a block.');
    }
    const escolha = await vscode.window.showQuickPick(
        BLOCOS.map(b => ({ label: b.nome, description: b.detalhe, bloco: b })),
        { title: 'Insert Block', placeHolder: 'Plain HTML, with its CSS added to the stylesheet' },
    );
    if (!escolha) return;
    const b = escolha.bloco;
    await editor.insertSnippet(new vscode.SnippetString(b.html.join('\n')));
    if (editor.document.uri.scheme !== 'file') return;
    const folha = vscode.Uri.file(folhaDaPagina(editor.document.getText(), path.dirname(editor.document.uri.fsPath), path));
    let atual = '';
    try { atual = Buffer.from(await vscode.workspace.fs.readFile(folha)).toString('utf8'); } catch { }
    if (atual.includes(`/* Block: ${b.nome} */`)) return;
    const aberto = vscode.workspace.textDocuments.find(d => d.uri.toString() === folha.toString());
    const texto = (atual && !atual.endsWith('\n') ? '\n' : '') + (atual.trim() ? '\n' : '') + cssDoBloco(b);
    if (aberto) {
        const edicao = new vscode.WorkspaceEdit();
        edicao.insert(folha, aberto.lineAt(aberto.lineCount - 1).range.end, texto);
        await vscode.workspace.applyEdit(edicao);
        await aberto.save();
    } else {
        await vscode.workspace.fs.writeFile(folha, Buffer.from(atual + texto, 'utf8'));
    }
    vscode.window.setStatusBarMessage(`${b.nome}: CSS added to ${path.basename(folha.fsPath)}`, 4000);
}

module.exports = { BLOCOS, cssDoBloco, folhaDaPagina, inserirBloco };
