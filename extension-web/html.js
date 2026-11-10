// Small HTML scanner: finds start tags with their lines, without a full parser.
// Used to mark served pages with source lines and to find the element under the cursor.

const VAZIOS = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr']);
const CRUS = new Set(['script', 'style', 'textarea', 'title']);

/** Lists elements as { nome, linha, inicio, fimTag, fim } with 0-based lines and offsets into the text. */
function elementos(texto) {
    const saida = [];
    const pilha = [];
    let linha = 0;
    let visto = 0;
    const linhaEm = pos => {
        for (; visto < pos; visto++) if (texto.charCodeAt(visto) === 10) linha++;
        return linha;
    };
    let i = 0;
    while (i < texto.length) {
        const lt = texto.indexOf('<', i);
        if (lt < 0) break;
        if (texto.startsWith('<!--', lt)) {
            const f = texto.indexOf('-->', lt + 4);
            i = f < 0 ? texto.length : f + 3;
            continue;
        }
        if (texto[lt + 1] === '!' || texto[lt + 1] === '?') {
            const f = texto.indexOf('>', lt);
            i = f < 0 ? texto.length : f + 1;
            continue;
        }
        if (texto[lt + 1] === '/') {
            const m = /^<\/([a-zA-Z][\w:-]*)\s*>/.exec(texto.slice(lt, lt + 200));
            if (!m) { i = lt + 1; continue; }
            const nome = m[1].toLowerCase();
            const k = pilha.map(e => e.nome).lastIndexOf(nome);
            if (k >= 0) {
                // Elements left open inside (like <p> without </p>) end where their parent ends
                for (const e of pilha.splice(k)) e.fim = lt + m[0].length;
            }
            i = lt + m[0].length;
            continue;
        }
        const m = /^<([a-zA-Z][\w:.-]*)/.exec(texto.slice(lt, lt + 100));
        if (!m) { i = lt + 1; continue; }
        // Walk the attributes, respecting quotes, to the closing '>'
        let j = lt + m[0].length;
        let aspas = null;
        for (; j < texto.length; j++) {
            const c = texto[j];
            if (aspas) { if (c === aspas) aspas = null; }
            else if (c === '"' || c === "'") aspas = c;
            else if (c === '>') break;
        }
        const nome = m[1].toLowerCase();
        const fechado = texto[j - 1] === '/';
        const el = { nome, linha: linhaEm(lt), inicio: lt, fimTag: j, fim: j + 1 };
        saida.push(el);
        i = j + 1;
        if (VAZIOS.has(nome) || fechado) continue;
        if (CRUS.has(nome)) {
            const f = texto.toLowerCase().indexOf(`</${nome}`, i);
            const fim = f < 0 ? texto.length : texto.indexOf('>', f) + 1 || texto.length;
            el.fim = fim;
            i = fim;
            continue;
        }
        el.fim = texto.length;
        pilha.push(el);
    }
    return saida;
}

/** Adds data-bl="<line>" to each start tag, so a click in the preview can find its source line. */
function marcar(texto) {
    const partes = [];
    let ultimo = 0;
    for (const e of elementos(texto)) {
        if (e.nome === 'html' || e.nome === 'head' || CRUS.has(e.nome) && e.nome !== 'textarea') continue;
        const pos = texto[e.fimTag - 1] === '/' ? e.fimTag - 1 : e.fimTag;
        partes.push(texto.slice(ultimo, pos), ` data-bl="${e.linha}"`);
        ultimo = pos;
    }
    partes.push(texto.slice(ultimo));
    return partes.join('');
}

/** Line of the innermost element that holds the offset, or -1. */
function linhaDoElemento(texto, pos) {
    let melhor = null;
    for (const e of elementos(texto)) {
        if (e.inicio <= pos && pos < e.fim && e.nome !== 'html' && e.nome !== 'head') {
            if (!melhor || e.inicio >= melhor.inicio) melhor = e;
        }
    }
    return melhor ? melhor.linha : -1;
}

/** Puts a script tag before </body>, or at the end when there is none. */
function injetarScript(texto, tag) {
    const k = texto.toLowerCase().lastIndexOf('</body>');
    return k < 0 ? texto + tag : texto.slice(0, k) + tag + texto.slice(k);
}

module.exports = { elementos, marcar, linhaDoElemento, injetarScript };
