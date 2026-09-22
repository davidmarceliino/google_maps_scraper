import io
import json
import os
import queue
import re
import tempfile
import threading
import time
import webbrowser

import bundle_paths

bundle_paths.configure_browser()

from flask import Flask, after_this_request, jsonify, render_template, request, send_file

from exporter import export_csv, export_excel
from filters import FilterManager
from scraper import Scraper
from whatsapp import WhatsAppChecker

app = Flask(__name__)

MAX_RESULTS_LIMIT = 500
MAX_CONCURRENT_JOBS = 2
JOB_TTL_SECONDS = 6 * 60 * 60

BASE_DIR = bundle_paths.data_dir()
LISTS_DIR = os.path.join(BASE_DIR, "saved_lists")
WHATSAPP_PROFILE = os.path.join(BASE_DIR, "whatsapp_profile")

WA = WhatsAppChecker(profile_dir=WHATSAPP_PROFILE)

JOBS = {}
JOBS_LOCK = threading.Lock()
_ID_COUNTER = 0
_ID_LOCK = threading.Lock()


def _new_job_id():
    global _ID_COUNTER
    with _ID_LOCK:
        _ID_COUNTER += 1
        return str(_ID_COUNTER)


class SearchJob:
    """Um job de busca que roda o scraper em segundo plano."""

    def __init__(self, query, max_results, require_phone):
        self.task_id = _new_job_id()
        self.query = query
        self.max_results = max_results
        self.require_phone = require_phone
        self.created_at = time.time()
        self.queue = queue.Queue()
        self.stop_event = threading.Event()
        self.filters = FilterManager(require_phone=require_phone)
        self.results = []
        self.processed = 0
        self.status = "Aguardando início..."
        self.running = False
        self.stopped = False
        self._lock = threading.Lock()
        self._scraper = None

    def start(self):
        self.running = True
        self._scraper = Scraper(
            self.query,
            self.max_results,
            self.stop_event,
            self.queue,
            headless=True,
        )
        self._scraper.start()
        threading.Thread(target=self._collect, daemon=True).start()

    def _collect(self):
        while not self.stop_event.is_set() or not self.queue.empty():
            try:
                msg = self.queue.get(timeout=0.6)
            except queue.Empty:
                if self._scraper is not None and not self._scraper.is_alive():
                    break
                continue
            kind = msg.get("type")
            if kind == "result":
                added, business = self.filters.process(msg.get("data") or {})
                if added:
                    with self._lock:
                        self.results.append(business)
            elif kind == "progress":
                self.processed = max(self.processed, int(msg.get("value", 0)))
            elif kind == "status":
                if msg.get("text"):
                    self.status = str(msg.get("text"))
        self.running = False

    def stop(self):
        self.stopped = True
        self.stop_event.set()

    def snapshot(self):
        with self._lock:
            results = [dict(r) for r in self.results]
        return {
            "query": self.query,
            "running": self.running,
            "stopped": self.stopped,
            "processed": self.processed,
            "found": len(results),
            "max_results": self.max_results,
            "status": self.status,
            "results": results,
        }


def _prune_jobs():
    now = time.time()
    with JOBS_LOCK:
        stale = [
            tid for tid, job in JOBS.items()
            if not job.running and now - job.created_at > JOB_TTL_SECONDS
        ]
        for tid in stale:
            JOBS.pop(tid, None)


# ------------------------------------------------------------------ rotas

@app.route("/")
def index():
    return render_template("index.html")


@app.post("/api/search")
def api_search():
    _prune_jobs()
    data = request.get_json(silent=True) or {}
    query = str(data.get("query", "")).strip()
    if not query:
        return jsonify({"error": "Termo de busca vazio."}), 400

    try:
        max_results = int(data.get("max_results", 50))
    except (TypeError, ValueError):
        max_results = 50
    max_results = max(1, min(MAX_RESULTS_LIMIT, max_results))

    with JOBS_LOCK:
        running = sum(1 for j in JOBS.values() if j.running)
        if running >= MAX_CONCURRENT_JOBS:
            return jsonify({"error": "Já existem buscas em andamento. Aguarde concluir."}), 429

    job = SearchJob(query, max_results, bool(data.get("only_with_phone", True)))
    with JOBS_LOCK:
        JOBS[job.task_id] = job
    job.start()
    return jsonify({"task_id": job.task_id})


@app.get("/api/jobs/<task_id>")
def api_job(task_id):
    job = JOBS.get(task_id)
    if job is None:
        return jsonify({"error": "Busca não encontrada."}), 404
    return jsonify(job.snapshot())


@app.post("/api/jobs/<task_id>/stop")
def api_stop(task_id):
    job = JOBS.get(task_id)
    if job is None:
        return jsonify({"error": "Busca não encontrada."}), 404
    job.stop()
    return jsonify({"ok": True})


def _deliver_rows(rows, fmt):
    ext = ".xlsx" if fmt == "excel" else ".csv"
    mime = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if fmt == "excel"
        else "text/csv"
    )
    fd, path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    try:
        if fmt == "excel":
            export_excel(rows, path)
        else:
            export_csv(rows, path)

        @after_this_request
        def _cleanup(resp):
            try:
                os.remove(path)
            except OSError:
                pass
            return resp

        return send_file(path, mimetype=mime, as_attachment=True, download_name="empresas{}".format(ext))
    except Exception as exc:
        try:
            os.remove(path)
        except OSError:
            pass
        return jsonify({"error": "Falha ao gerar arquivo: {}".format(exc)}), 500


@app.get("/api/jobs/<task_id>/download")
def api_download(task_id):
    job = JOBS.get(task_id)
    if job is None:
        return jsonify({"error": "Busca não encontrada."}), 404

    fmt = request.args.get("format", "excel")
    if fmt not in ("excel", "csv"):
        return jsonify({"error": "Formato inválido."}), 400

    with job._lock:
        results = [dict(r) for r in job.results]
    if not results:
        return jsonify({"error": "Nenhuma empresa para exportar."}), 400
    return _deliver_rows(results, fmt)


@app.post("/api/export")
def api_export():
    """Exporta a lista atual exibida na interface (permite acumular buscas)."""
    data = request.get_json(silent=True) or {}
    fmt = "excel"
    if data.get("format") not in ("excel", "csv"):
        pass
    else:
        fmt = data.get("format")
    rows = data.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return jsonify({"error": "Nada para exportar."}), 400
    return _deliver_rows(rows, fmt)


# ----------------------------------------------------------- listas salvas

def _safe_list_name(name):
    return re.sub(r"[^\w\- ]+", "", name or "").strip()[:80]


def _ensure_lists_dir():
    os.makedirs(LISTS_DIR, exist_ok=True)


def _list_path(name):
    safe = _safe_list_name(name)
    return os.path.join(LISTS_DIR, safe + ".json"), safe


def _row_key(r):
    phone = re.sub(r"\D", "", str(r.get("phone") or ""))
    if phone:
        return "p:" + phone
    return "n:" + (r.get("name") or "").strip().lower()


@app.get("/api/lists")
def api_lists():
    _ensure_lists_dir()
    items = []
    for fn in os.listdir(LISTS_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(LISTS_DIR, fn), encoding="utf-8") as fh:
                data = json.load(fh)
            items.append({
                "name": data.get("name", fn[:-5]),
                "created_at": data.get("created_at", 0),
                "count": len(data.get("rows") or []),
            })
        except Exception:
            continue
    items.sort(key=lambda i: i["created_at"], reverse=True)
    return jsonify({"lists": items})


@app.post("/api/lists/save")
def api_lists_save():
    data = request.get_json(silent=True) or {}
    name = _safe_list_name(data.get("name"))
    rows = data.get("rows") or []
    if not name:
        return jsonify({"error": "Informe um nome para a lista."}), 400
    if not isinstance(rows, list) or not rows:
        return jsonify({"error": "Nada para salvar."}), 400

    path, safe = _list_path(name)
    _ensure_lists_dir()

    existing = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                existing = json.load(fh)
        except Exception:
            existing = {}

    if bool(data.get("merge")) and isinstance(existing.get("rows"), list):
        seen = {_row_key(r) for r in existing["rows"]}
        merged = existing["rows"]
        for r in rows:
            key = _row_key(r)
            if key and key not in seen:
                seen.add(key)
                merged.append(r)
        rows = merged
    else:
        rows = list(rows)

    payload = {"name": safe, "created_at": time.time(), "rows": rows}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return jsonify({"ok": True, "name": safe, "count": len(rows)})


@app.get("/api/lists/<path:name>")
def api_lists_get(name):
    path, safe = _list_path(name)
    if not os.path.exists(path):
        return jsonify({"error": "Lista não encontrada."}), 404
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        return jsonify({"error": "Falha ao ler a lista: {}".format(exc)}), 500
    return jsonify({"name": data.get("name", safe), "rows": data.get("rows") or []})


@app.delete("/api/lists/<path:name>")
def api_lists_delete(name):
    path, _ = _list_path(name)
    if not os.path.exists(path):
        return jsonify({"error": "Lista não encontrada."}), 404
    try:
        os.remove(path)
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True})


# -------------------------------------------------------------- WhatsApp (web)

@app.get("/api/whatsapp/status")
def wa_status():
    return jsonify(WA.snapshot())


@app.post("/api/whatsapp/open")
def wa_open():
    return jsonify(WA.open())


@app.get("/api/whatsapp/qr")
def wa_qr():
    result = WA.qr()
    png = result.get("png")
    if not png:
        return jsonify({"error": "QR indisponível agora."}), 404
    return send_file(io.BytesIO(png), mimetype="image/png", cache_timeout=0)


@app.post("/api/whatsapp/check")
def wa_check():
    data = request.get_json(silent=True) or {}
    phones = [str(p) for p in data.get("phones", [])]
    result = WA.check(phones)
    if result.get("need_login"):
        result["need_login"] = True
        result["ok"] = False
    elif not result.get("ok"):
        result["ok"] = False
    return jsonify(result)


# --------------------------------------------------------------------- main

def _local_ip():
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    import socket
    import urllib.parse

    host = os.environ.get("APP_HOST", "0.0.0.0")
    port = int(os.environ.get("APP_PORT", "8000"))
    local_url = "http://127.0.0.1:{}".format(port)
    lan_url = "http://{}:{}".format(_local_ip(), port)

    def _open_browser():
        for _ in range(40):
            try:
                parsed = urllib.parse.urlparse(local_url)
                socket.create_connection((parsed.hostname, parsed.port), timeout=1)
                webbrowser.open(local_url)
                return
            except Exception:
                pass
            time.sleep(0.25)

    print("=" * 52)
    print("  Buscador Google Maps - Servidor")
    print("=" * 52)
    print("  Local:  {}".format(local_url))
    print("  Rede:   {}".format(lan_url))
    print("  Para PARAR: feche esta janela.")
    print("=" * 52)

    threading.Thread(target=_open_browser, daemon=True).start()

    try:
        from waitress import serve

        serve(app, host=host, port=port, threads=8)
    except ImportError:
        app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()