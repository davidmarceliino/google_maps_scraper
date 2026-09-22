import queue
import re
import threading

from playwright.sync_api import sync_playwright

WA_URL = "https://web.whatsapp.com/"

# ----- seletores do WhatsApp Web (o layout muda com frequência; ajustar aqui) -----
QR_CONTAINER = "div[data-ref]"          # presente quando aparece o QR Code de login
SIDEBAR = "#pane-side"                  # presente quando já está logado
CHAT_HEADER = "#main header"            # cabeçalho da conversa aberta (número válido)
FALLBACK_BLOCK = "#fallback_block"      # presente quando o número não é válido
INVALID_TEXT = (
    "não está no whatsapp",
    "não e um whatsapp",
    "isn't on whatsapp",
    "not on whatsapp",
    "numero invalido",
    "invalid number",
    "phone number shared via url is invalid",
)

QR_WAIT_STEPS = 25           # x 1.5s de espera ao abrir a sessão (login ou QR)
DECISION_STEPS = 10          # x 1.5s de espera por número na verificação
CHECK_DELAY_SECONDS = 2      # intervalo gentil entre verificações
MAX_PHONES_PER_BATCH = 20


class WhatsAppChecker:
    """Verifica se números têm WhatsApp usando uma única sessão do WhatsApp Web.

    A sessão fica salva em `profile_dir`. Na primeira vez é preciso ler o QR Code
    com o celular (a interface mostra as rotas /api/whatsapp/*). Não é necessário
    API Key; também não envia mensagens (apenas verifica a existência).
    """

    def __init__(self, profile_dir="whatsapp_profile"):
        self.profile_dir = profile_dir
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self.status = "idle"          # idle | starting | waiting_scan | connected | error
        self.error = ""
        self.last_qr = None
        threading.Thread(target=self._loop, daemon=True).start()

    # ---------------------------------------------------------- estado interno

    def _set(self, **kwargs):
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def _snapshot(self):
        with self._lock:
            return {"status": self.status, "error": self.error}

    def _command(self, payload, timeout):
        holder = {"result": None, "event": threading.Event()}
        try:
            self._queue.put((payload, holder))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if not holder["event"].wait(timeout):
            return {"ok": False, "error": "timeout"}
        return holder["result"]

    # --------------------------------------------------------------- API pública

    def snapshot(self):
        return self._snapshot()

    def open(self):
        return self._command({"type": "open"}, 90)

    def qr(self):
        return self._command({"type": "qr"}, 10)

    def check(self, phones):
        phones = [str(p).strip() for p in phones if str(p).strip()]
        if not phones:
            return {"ok": False, "error": "Nenhum telefone informado."}
        phones = phones[:MAX_PHONES_PER_BATCH]
        return self._command({"type": "check", "phones": phones}, 30 + len(phones) * 30)

    # ------------------------------------------------------------- thread worker

    def _loop(self):
        self._pw = None
        self._ctx = None
        try:
            while True:
                payload, holder = self._queue.get()
                if payload.get("type") == "stop":
                    break
                try:
                    if self._ctx is None:
                        self._start_browser()
                    result = self._dispatch(payload)
                except Exception as exc:
                    self._set(status="error", error=str(exc))
                    result = {"ok": False, "error": str(exc)}
                holder["result"] = result
                holder["event"].set()
        except Exception:
            pass
        finally:
            try:
                if self._ctx is not None:
                    self._ctx.close()
                if self._pw is not None:
                    self._pw.stop()
            except Exception:
                pass

    def _start_browser(self):
        self._set(status="starting", error="")
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            self.profile_dir,
            headless=True,
            args=["--no-sandbox"],
        )
        if not self._ctx.pages:
            self._ctx.new_page()
        self._set(status="connected" if self._is_logged(self._page()) else "waiting_scan")
        if self.status == "waiting_scan":
            self._snap_qr()

    def _page(self):
        return self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def _is_logged(self, page):
        try:
            return page.locator(SIDEBAR).count() > 0
        except Exception:
            return False

    # -------------------------------------------------------- comandos (worker)

    def _dispatch(self, payload):
        kind = payload["type"]
        if kind == "open":
            return self._do_open()
        if kind == "qr":
            return self._do_qr()
        if kind == "check":
            return self._do_check(payload.get("phones") or [])
        return {"ok": False, "error": "comando desconhecido"}

    def _do_open(self):
        self._set(error="")
        page = self._page()
        page.goto(WA_URL, wait_until="domcontentloaded", timeout=60000)
        for _ in range(QR_WAIT_STEPS):
            if self._is_logged(page):
                self._set(status="connected")
                return {"ok": True, "status": "connected"}
            if page.locator(QR_CONTAINER).count():
                self._set(status="waiting_scan")
                self._snap_qr()
                return {"ok": True, "status": "waiting_scan"}
            page.wait_for_timeout(1500)
        self._set(status="error", error="Não foi possível conectar ao WhatsApp Web.")
        return {"ok": False, "error": "Sessão não identificada (tempo esgotado)."}

    def _do_qr(self):
        if self.status != "waiting_scan":
            return {"ok": True, "png": None}
        page = self._page()
        self._snap_qr(page)
        with self._lock:
            return {"ok": True, "png": self.last_qr}

    def _snap_qr(self, page=None):
        try:
            page = page or self._page()
            loc = page.locator(QR_CONTAINER).first
            if loc.count():
                png = loc.screenshot(timeout=8000)
            else:
                png = page.screenshot(timeout=8000)
            self._set(last_qr=png)
        except Exception:
            pass

    def _do_check(self, phones):
        page = self._page()
        if not self._is_logged(page):
            self._do_open()
            if not self._is_logged(self._page()):
                return {"ok": False, "need_login": True,
                        "message": "Você precisa conectar o WhatsApp (QR Code) antes de verificar."}

        results = []
        for phone in phones:
            digits = re.sub(r"\D", "", phone)
            if not digits:
                results.append({"phone": phone, "valid": False, "name": "", "error": "sem número"})
                continue
            if not digits.startswith("55"):
                if len(digits) in (10, 11):
                    digits = "55" + digits
            url = "https://web.whatsapp.com/send?phone={}".format(digits)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                results.append(self._decide(page, phone))
            except Exception as exc:
                results.append({"phone": phone, "valid": False, "name": "", "error": str(exc)[:120]})
            page.wait_for_timeout(CHECK_DELAY_SECONDS * 1000)
        return {"ok": True, "results": results}

    def _decide(self, page, phone):
        for _ in range(DECISION_STEPS):
            if page.locator(QR_CONTAINER).count():
                return {"phone": phone, "valid": False, "name": "", "error": "login_required"}
            if page.locator(FALLBACK_BLOCK).count():
                return {"phone": phone, "valid": False, "name": ""}
            try:
                body = page.locator("body").inner_text(timeout=1500).lower()
                if any(token in body for token in INVALID_TEXT):
                    return {"phone": phone, "valid": False, "name": ""}
            except Exception:
                pass
            try:
                header = page.locator(CHAT_HEADER).first
                if header.is_visible(timeout=1500):
                    name = header.inner_text().strip().splitlines()
                    name = name[0].strip() if name else ""
                    return {"phone": phone, "valid": True, "name": name}
            except Exception:
                pass
            page.wait_for_timeout(1500)
        return {"phone": phone, "valid": False, "name": "", "error": "tempo esgotado"}