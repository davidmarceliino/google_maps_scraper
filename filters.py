import re
import unicodedata


class FilterManager:
    """Aplica filtros e remove duplicatas sobre empresas coletadas."""

    def __init__(self, require_phone=True):
        self.require_phone = require_phone
        self._seen = set()

    @staticmethod
    def normalize_phone(phone):
        if not phone:
            return ""
        return re.sub(r"[^\d+]", "", phone)

    @staticmethod
    def _slugify(text):
        text = unicodedata.normalize("NFD", text or "")
        text = "".join(c for c in text if unicodedata.category(c) != "Mn")
        return re.sub(r"[^a-z0-9]+", "", text.lower())

    @staticmethod
    def parse_address(address):
        city = state = cep = ""
        address = (address or "").strip()
        m = re.search(r"\b(\d{5})-?(\d{3})\b", address)
        if m:
            cep = "{}-{}".format(m.group(1), m.group(2))
        matches = list(re.finditer(r",\s*([^,\-]+?)\s*-\s*([A-Z]{2})(?:,|$)", address))
        if matches:
            last = matches[-1]
            city = last.group(1).strip()
            state = last.group(2).strip()
        return city, state, cep

    def process(self, raw):
        """Recebe dados brutos e devolve (adicionado, empresa|None)."""
        name = (raw.get("name") or "").strip()
        address = (raw.get("address") or "").strip()
        phone = self.normalize_phone(raw.get("phone") or "")

        if not name:
            return False, None
        if self.require_phone and not phone:
            return False, None

        link = raw.get("maps_link") or ""
        if link.startswith("/"):
            link = "https://www.google.com" + link

        key = self._make_key(name, phone, link)
        if key in self._seen:
            return False, None
        self._seen.add(key)

        city, state, cep = self.parse_address(address)
        business = {
            "name": name,
            "phone": raw.get("phone") or "",
            "address": address,
            "city": city,
            "state": state,
            "cep": cep,
            "website": raw.get("website") or "",
            "google_maps": link,
        }
        return True, business

    def _make_key(self, name, phone, link):
        if phone:
            return ("phone", phone)
        return ("name", self._slugify(name), link)