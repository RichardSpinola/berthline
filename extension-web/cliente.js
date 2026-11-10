// Runs inside the previewed page: live reload, CSS swap and inspect. Served by servidor.js.
(() => {
    if (window.__berthline) return;
    window.__berthline = true;
    const pai = window.parent !== window ? window.parent : null;
    const avisar = msg => pai && pai.postMessage({ berthline: true, ...msg }, '*');

    // Reload and CSS swap
    let fonte;
    const ligar = () => {
        fonte = new EventSource('/__berthline/events');
        fonte.onmessage = e => {
            const m = JSON.parse(e.data);
            if (m.type === 'reload') location.reload();
            else if (m.type === 'css') trocarCss();
        };
    };
    ligar();
    function trocarCss() {
        const agora = Date.now();
        for (const link of document.querySelectorAll('link[rel~="stylesheet"][href]')) {
            const url = new URL(link.href, location.href);
            if (url.origin !== location.origin) continue;
            url.searchParams.set('bl', agora);
            // The new sheet loads beside the old one, so the page never shows unstyled
            const novo = link.cloneNode();
            novo.href = url.href;
            novo.onload = novo.onerror = () => link.remove();
            link.after(novo);
        }
    }

    // Inspect: an outline follows the mouse; a click sends the source line to the editor
    let inspecionando = false;
    const caixa = document.createElement('div');
    const nome = document.createElement('span');
    caixa.appendChild(nome);
    caixa.setAttribute('style', 'position:fixed;z-index:2147483647;pointer-events:none;display:none;box-sizing:border-box;' +
        'border:1px solid #3B82C4;background:rgba(59,130,196,.12)');
    nome.setAttribute('style', 'position:absolute;left:-1px;bottom:100%;padding:1px 5px;font:11px/16px monospace;' +
        'color:#fff;background:#3B82C4;white-space:nowrap');
    const mostrar = el => {
        if (!el || el === document.documentElement) { caixa.style.display = 'none'; return; }
        if (!caixa.isConnected) document.documentElement.appendChild(caixa);
        const r = el.getBoundingClientRect();
        Object.assign(caixa.style, { display: 'block', left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
        const classes = typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).join('.') : '';
        nome.textContent = el.tagName.toLowerCase() + (el.id ? `#${el.id}` : '') + classes;
        // The label sits above the box, or below it when the element touches the top
        nome.style.top = r.top < 18 ? '100%' : 'auto';
        nome.style.bottom = r.top < 18 ? 'auto' : '100%';
    };

    // Plain HTML carries data-bl from the server; frameworks are best effort through their dev metadata
    function origem(el) {
        const marcado = el.closest('[data-bl]');
        if (marcado) return { caminho: location.pathname, linha: Number(marcado.dataset.bl) };
        for (let e = el; e; e = e.parentElement) {
            const svelte = e.__svelte_meta?.loc;
            if (svelte) return { arquivo: svelte.file, linha: svelte.line - 1 };
            const chave = Object.keys(e).find(k => k.startsWith('__reactFiber$'));
            for (let f = chave && e[chave]; f; f = f.return) {
                const s = f._debugSource;
                if (s) return { arquivo: s.fileName, linha: s.lineNumber - 1 };
            }
            const vue = e.__vueParentComponent?.type?.__file;
            if (vue) return { arquivo: vue, linha: 0 };
        }
        return null;
    }

    const aoMover = e => mostrar(e.target);
    const aoClicar = e => {
        e.preventDefault();
        e.stopPropagation();
        const o = origem(e.target);
        avisar(o ? { type: 'pick', ...o } : { type: 'pick-none' });
    };
    const aoTeclar = e => { if (e.key === 'Escape') avisar({ type: 'inspect-off' }); };
    function inspecionar(ligado) {
        if (ligado === inspecionando) return;
        inspecionando = ligado;
        const f = (t, h, c) => window[ligado ? 'addEventListener' : 'removeEventListener'](t, h, c);
        f('mousemove', aoMover, true);
        f('click', aoClicar, true);
        f('keydown', aoTeclar, true);
        document.documentElement.style.cursor = ligado ? 'crosshair' : '';
        if (!ligado) caixa.style.display = 'none';
    }

    addEventListener('message', e => {
        if (e.source !== pai || !e.data?.berthline) return;
        const m = e.data;
        if (m.type === 'inspect') inspecionar(m.on);
        else if (m.type === 'highlight') {
            const el = m.caminho === location.pathname && document.querySelector(`[data-bl="${Number(m.linha)}"]`);
            if (!el) return mostrar(null);
            el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
            mostrar(el);
        } else if (m.type === 'reload') location.reload();
    });
    addEventListener('scroll', () => { if (!inspecionando) caixa.style.display = 'none'; }, true);
    // Console errors and warnings reach the editor (Output > Preview), so they are seen without DevTools
    const texto = v => { try { return typeof v === 'string' ? v : v instanceof Error ? v.stack || v.message : JSON.stringify(v); } catch { return String(v); } };
    let enviados = 0;
    const registrar = (nivel, partes) => { if (enviados++ < 200) avisar({ type: 'log', nivel, texto: partes.map(texto).join(' ') }); };
    for (const nivel of ['error', 'warn']) {
        const original = console[nivel];
        console[nivel] = (...a) => { registrar(nivel, a); return original.apply(console, a); };
    }
    addEventListener('error', e => { if (e.message) registrar('error', [`${e.message} (${e.filename || location.pathname}:${e.lineno})`]); });
    addEventListener('unhandledrejection', e => registrar('error', ['Unhandled rejection:', e.reason]));

    // Right-click: Inspect opens the editor's DevTools on this page; Reload reloads it
    let menu = null;
    const fecharMenu = () => { menu?.remove(); menu = null; };
    addEventListener('contextmenu', e => {
        if (!pai || inspecionando) return;
        e.preventDefault();
        fecharMenu();
        menu = document.createElement('div');
        menu.setAttribute('style', 'position:fixed;z-index:2147483647;min-width:160px;padding:4px 0;background:#252526;color:#ccc;' +
            'border:1px solid #454545;border-radius:5px;box-shadow:0 2px 8px rgba(0,0,0,.36);font:13px system-ui,sans-serif');
        for (const [rotulo, acao] of [['Inspect', () => avisar({ type: 'devtools' })], ['Reload', () => location.reload()]]) {
            const item = document.createElement('div');
            item.textContent = rotulo;
            item.setAttribute('style', 'padding:4px 24px;cursor:default;white-space:nowrap');
            item.onmouseenter = () => { item.style.background = '#04395e'; item.style.color = '#fff'; };
            item.onmouseleave = () => { item.style.background = ''; item.style.color = ''; };
            item.onclick = ev => { ev.stopPropagation(); fecharMenu(); acao(); };
            menu.appendChild(item);
        }
        document.documentElement.appendChild(menu);
        const r = menu.getBoundingClientRect();
        menu.style.left = `${Math.min(e.clientX, innerWidth - r.width - 4)}px`;
        menu.style.top = `${Math.min(e.clientY, innerHeight - r.height - 4)}px`;
    }, true);
    addEventListener('mousedown', e => { if (menu && !menu.contains(e.target)) fecharMenu(); }, true);
    addEventListener('keydown', e => { if (e.key === 'Escape') fecharMenu(); }, true);
    addEventListener('blur', fecharMenu);

    const pronto = () => avisar({ type: 'ready', url: location.href, title: document.title });
    document.readyState === 'loading' ? addEventListener('DOMContentLoaded', pronto) : pronto();
    addEventListener('hashchange', pronto);
})();
