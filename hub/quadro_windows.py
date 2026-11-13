"""Native Windows frame handling for the Hub window (Windows only; imported lazily by hub.py)."""


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
