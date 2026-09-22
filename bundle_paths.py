"""Resolve caminhos de dados quando o app roda como executável (PyInstaller).

Quando congelado (--onefile), tudo é extraído para `sys._MEIPASS` em tempo de
execução. Este módulo aponta o Playwright para o navegador embutido e as
pastas de trabalho para fora do executável (para não se perderem a cada execução).
"""
import os
import sys


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def resource_path(*names):
    """Caminho de um recurso que foi embutido no .exe (extraído em _MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *names)


def data_dir():
    """Pasta persistente de dados (listas salvas, perfil WhatsApp).

    Fica ao lado do .exe quando congelado; na raiz do projeto em desenvolvimento.
    """
    if is_frozen():
        return os.path.join(os.path.dirname(sys.executable), "dados")
    return os.path.dirname(os.path.abspath(__file__))


def configure_browser():
    """Aponta o Playwright para o Chromium embutido no .exe.

    Deve ser chamado ANTES de importar o Playwright (ou antes de lançar o
    navegador), pois ele lê essa variável ao resolver o executável do browser.
    """
    if not is_frozen():
        return
    browsers_root = resource_path("browsers")
    if os.path.isdir(browsers_root):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_root


def browser_exists():
    if is_frozen():
        root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or resource_path("browsers")
        return any(name.startswith("chromium_headless_shell-") for name in os.listdir(root)) if os.path.isdir(root) else False
    return True