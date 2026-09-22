import threading
import time

from playwright.sync_api import sync_playwright

MAPS_URL = "https://www.google.com/maps"

PLACE_LINK_SELECTOR = "a.hfpxzc"
NAME_LIST_SELECTOR = "div.qBF1Pd"
NAME_PANEL_SELECTOR = "h1.DUwDvf"
FEED_SELECTOR = "div[role='feed']"

SEARCH_INPUT_SELECTORS = [
    "input[role='combobox']",
    "#searchboxinput",
]

CLOSE_PANEL_BUTTONS = [
    "button[aria-label='Fechar'].VfPpkd-icon-LgbsSe",
    "button[aria-label='Fechar']",
    "button[aria-label='Close'].VfPpkd-icon-LgbsSe",
    "button[aria-label='Close']",
]

MAX_SCROLL_CYCLES = 30


class Scraper(threading.Thread):
    """Coleta dados públicos de empresas no Google Maps via Playwright."""

    def __init__(self, query, max_results, stop_event, queue, headless=False):
        super().__init__(daemon=True)
        self.query = query
        self.max_results = max_results
        self.stop_event = stop_event
        self.queue = queue
        self.headless = headless
        self.page = None
        self._seen_hrefs = set()

    def run(self):
        self._post_status("Abrindo navegador...")
        try:
            with sync_playwright() as p:
                launch_args = ["--no-sandbox"] if self.headless else None
                browser = p.chromium.launch(headless=self.headless, args=launch_args)
                try:
                    self._post_status("Navegador aberto. Carregando o Google Maps...")
                    page = browser.new_page()
                    self.page = page
                    self._goto_and_wait()
                    if self.stop_event.is_set():
                        return
                    self._dismiss_consent()
                    self._run_search()
                finally:
                    browser.close()
        except Exception as exc:
            if not self.stop_event.is_set():
                self._post_status("Erro: {}".format(exc))
        self._post_status("Navegador fechado.")

    # ------------------------------------------------------------- helpers

    def _post_status(self, text):
        self._put({"type": "status", "text": text})

    def _post_progress(self, value):
        self._put({"type": "progress", "value": value})

    def _post_result(self, raw):
        self._put({"type": "result", "data": raw})

    def _put(self, msg):
        try:
            self.queue.put(msg)
        except Exception:
            pass

    def _goto_and_wait(self):
        self.page.goto(MAPS_URL, wait_until="domcontentloaded", timeout=60000)
        if self._wait_searchbox() is None:
            raise RuntimeError("Campo de busca do Google Maps não foi encontrado.")

    def _dismiss_consent(self):
        for label in ("Rejeitar tudo", "Reject all", "Aceitar tudo", "Accept all", "Concordar"):
            try:
                btn = self.page.get_by_role("button", name=label).first
                if btn.is_visible(timeout=1200):
                    btn.click(timeout=3000)
                    self.page.wait_for_timeout(1000)
                    return
            except Exception:
                continue

    def _detect_blocked(self):
        try:
            body = self.page.locator("body").inner_text(timeout=2000)
        except Exception:
            return False
        tokens = ("not a robot", "recaptcha", "verify you are human",
                  "captcha", "verificação", "uma verificação")
        return any(token in body.lower() for token in tokens)

    def _stop_requested(self):
        return self.stop_event.is_set()

    def _wait_searchbox(self, timeout_ms=30000):
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            for selector in SEARCH_INPUT_SELECTORS:
                try:
                    loc = self.page.locator(selector)
                    if loc.count() and loc.first.is_visible(timeout=400):
                        return loc.first
                except Exception:
                    continue
            self.page.wait_for_timeout(500)
        return None

    # --------------------------------------------------------------- search

    def _run_search(self):
        if self._detect_blocked():
            self._post_status(
                "Verificação do Google detectada (CAPTCHA). "
                "Não é possível contornar; a busca foi encerrada."
            )
            return

        box = self._wait_searchbox(15000)
        if box is None:
            self._post_status("Campo de busca não encontrado. O layout do Google Maps pode ter mudado.")
            return
        box.click()
        box.fill(self.query)
        self.page.keyboard.press("Enter")
        self._post_status("Buscando por: {}".format(self.query))

        feed = self.page.locator(FEED_SELECTOR).first
        try:
            feed.wait_for(state="visible", timeout=25000)
        except Exception:
            self._post_status(
                "A página não carregou os resultados. "
                "Verifique a conexão ou o termo de busca."
            )
            return

        self.page.wait_for_timeout(2000)

        if self._detect_blocked():
            self._post_status("Verificação do Google detectada. Encerrando busca.")
            return

        processed = 0
        scroll_cycles = 0

        while not self._stop_requested():
            if processed >= self.max_results:
                break

            items = self._current_items()
            fresh = [it for it in items if self._item_ref(it) not in self._seen_hrefs]

            if not fresh:
                self._scroll_feed()
                scroll_cycles += 1
                if scroll_cycles >= MAX_SCROLL_CYCLES:
                    self._post_status("Não foi possível carregar mais resultados.")
                    break
                continue

            scroll_cycles = 0

            for item in fresh:
                if self._stop_requested() or processed >= self.max_results:
                    break
                ref = self._item_ref(item)
                if ref in self._seen_hrefs:
                    continue
                self._seen_hrefs.add(ref)
                processed += 1
                self._post_progress(processed)
                try:
                    raw = self._read_item(item)
                    if raw and raw.get("name"):
                        self._post_result(raw)
                        self._post_status("({}) {}".format(processed, raw["name"]))
                    else:
                        self._post_status("Aviso: empresa sem dados legíveis ignorada.")
                except Exception as exc:
                    self._post_status("Aviso: não foi possível ler uma empresa: {}".format(exc))
                    self._close_panel()

            if processed >= self.max_results or self._stop_requested():
                break
            self._scroll_feed()

        if self._stop_requested():
            self._post_status("Busca interrompida pelo usuário.")
        elif processed >= self.max_results:
            self._post_status("Busca concluída: limite de resultados atingido.")

    def _current_items(self):
        for selector in (FEED_SELECTOR + " div.Nv2PK", FEED_SELECTOR + " > div"):
            loc = self.page.locator(selector)
            try:
                count = loc.count()
                if count > 0:
                    return [loc.nth(i) for i in range(count)]
            except Exception:
                continue
        return []

    def _item_ref(self, item):
        for field in (PLACE_LINK_SELECTOR, NAME_LIST_SELECTOR):
            try:
                if field == PLACE_LINK_SELECTOR:
                    value = item.locator(field).first.get_attribute("href") or ""
                else:
                    value = item.locator(field).first.inner_text().strip()
                if value:
                    return value
            except Exception:
                continue
        return id(item)

    def _read_item(self, item):
        raw = {}
        try:
            raw["name"] = item.locator(NAME_LIST_SELECTOR).first.inner_text().strip()
        except Exception:
            raw["name"] = ""
        try:
            raw["maps_link"] = (
                item.locator(PLACE_LINK_SELECTOR).first.get_attribute("href") or ""
            )
        except Exception:
            raw["maps_link"] = ""

        self._open_item(item)
        self.page.wait_for_timeout(3000)
        self._read_panel(raw)
        self._close_panel()
        return raw

    def _open_item(self, item):
        try:
            item.locator(PLACE_LINK_SELECTOR).first.click(timeout=5000)
            return
        except Exception:
            pass
        item.click(timeout=5000)

    def _read_panel(self, raw):
        try:
            panel_name = self.page.locator(NAME_PANEL_SELECTOR).first.inner_text(timeout=6000).strip()
            if panel_name:
                raw["name"] = panel_name
        except Exception:
            pass

        try:
            self.page.wait_for_selector(
                "button[data-item-id^='address:'], div[data-item-id^='address:'], "
                "button[data-item-id^='authority:'], a[data-item-id^='authority:']",
                timeout=12000,
            )
        except Exception:
            pass

        fields = {"address": "", "phone": "", "website": ""}
        try:
            items = self.page.locator("[data-item-id]").evaluate_all(
                "els => els.map(el => ({"
                "tag: el.tagName, "
                "did: el.getAttribute('data-item-id') || '', "
                "tx: el.innerText || ''}))"
            )
        except Exception:
            items = []

        for item in items:
            prefix = (item.get("did") or "").split(":")[0]
            if prefix in fields and not fields[prefix]:
                fields[prefix] = self._clean_text(item.get("tx") or "")

        raw["address"] = fields["address"]
        raw["phone"] = fields["phone"]
        raw["website"] = fields["website"]

    @staticmethod
    def _clean_text(text):
        if not text:
            return ""
        lines = [line.strip() for line in str(text).splitlines() if line.strip()]
        cleaned = [
            line for line in lines
            if not all(ord(ch) in range(0xE000, 0xF900) for ch in line)
        ]
        return " ".join(cleaned).strip()

    def _close_panel(self):
        for selector in CLOSE_PANEL_BUTTONS:
            try:
                btn = self.page.locator(selector).first
                if btn.is_visible(timeout=1200):
                    btn.click(timeout=2500)
                    self.page.wait_for_timeout(500)
                    return
            except Exception:
                continue
        try:
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(500)
        except Exception:
            pass

    def _scroll_feed(self):
        try:
            self.page.locator(FEED_SELECTOR).first.hover(timeout=3000)
        except Exception:
            pass
        self.page.wait_for_timeout(300)
        for _ in range(6):
            try:
                self.page.mouse.wheel(0, 4000)
            except Exception:
                pass
            self.page.wait_for_timeout(600)