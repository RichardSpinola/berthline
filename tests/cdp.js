// Shared CDP helpers for the editor tests.
const fs = require('fs'), path = require('path'), http = require('http');

const SAIDA = process.env.SUITE_AUDIT_OUT || path.join(__dirname, 'out');
const dormir = ms => new Promise(r => setTimeout(r, ms));

const obter = url => new Promise((ok, no) => http.get(url, r => {
    let b = ''; r.on('data', d => b += d); r.on('end', () => ok(JSON.parse(b)));
}).on('error', no));

async function conectar(PORTA) {
    let alvo;
    for (let i = 0; i < 120 && !alvo; i++) {
        try { alvo = (await obter(`http://127.0.0.1:${PORTA}/json/list`)).find(t => t.type === 'page'); } catch { /* still starting */ }
        if (!alvo) await dormir(500);
    }
    if (!alvo) throw new Error('no editor window');
    const w = new WebSocket(alvo.webSocketDebuggerUrl);
    await new Promise(r => { w.onopen = r; });
    let id = 0; const pend = {};
    w.onmessage = m => { const d = JSON.parse(m.data); pend[d.id]?.(d); };
    const c = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; w.send(JSON.stringify({ id: i, method, params })); });
    const ev = async e => (await c('Runtime.evaluate', { expression: e, returnByValue: true })).result?.result?.value;
    const h = { c, ev };
    h.foto = async n => {
        const s = await c('Page.captureScreenshot', { format: 'png' });
        fs.writeFileSync(path.join(SAIDA, `${n}.png`), Buffer.from(s.result.data, 'base64'));
    };
    h.xy = async (x, y) => { for (const type of ['mousePressed', 'mouseReleased']) await c('Input.dispatchMouseEvent', { type, x, y, button: 'left', clickCount: 1 }); };
    h.acha = (sel, re = '') => ev(`(()=>{const R=new RegExp(${JSON.stringify(re)});const e=[...document.querySelectorAll(${JSON.stringify(sel)})].filter(e=>e.getBoundingClientRect().width>0).find(e=>R.test(e.getAttribute('aria-label')||e.innerText||''));if(!e)return null;const b=e.getBoundingClientRect();return {x:b.x+b.width/2,y:b.y+b.height/2}})()`);
    h.clica = async (sel, re) => { const r = await h.acha(sel, re); if (r) await h.xy(r.x, r.y); return !!r; };
    h.tecla = async (key, code, vk) => { for (const type of ['keyDown', 'keyUp']) await c('Input.dispatchKeyEvent', { type, key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, text: type === 'keyDown' && key === 'Enter' ? '\r' : undefined }); };
    h.escreve = async t => { for (const text of t) await c('Input.insertText', { text }); };
    h.terminal = () => ev(`[...document.querySelectorAll('.xterm-rows')].map(e=>e.innerText).join(' / ').replace(/\\s+/g,' ').trim()`);
    h.status = () => ev(`[...document.querySelectorAll('.statusbar-item')].map(e=>e.innerText).join(' ; ')`);
    h.ate = async (f, ms = 30000) => { const t = Date.now(); while (Date.now() - t < ms) { if (await f()) return true; await dormir(300); } return false; };
    h.fechar = () => Promise.race([c('Browser.close'), dormir(1500)]);
    return h;
}

// The next editor can't take the port until this one is really gone.
async function fechado(PORTA, ms = 30000) {
    const fim = Date.now() + ms;
    while (Date.now() < fim) {
        try { await obter(`http://127.0.0.1:${PORTA}/json/version`); } catch { return true; }
        await dormir(500);
    }
    return false;
}

module.exports = { SAIDA, dormir, conectar, fechado };
