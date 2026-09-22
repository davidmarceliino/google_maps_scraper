import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from exporter import COLUMNS, HEADER_TO_FIELD, export_csv, export_excel
from filters import FilterManager
from scraper import Scraper

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLUMNS_WIDTH = {
    "Nome": 260,
    "Telefone": 150,
    "Endereço": 330,
    "Cidade": 130,
    "Estado": 60,
    "CEP": 95,
    "Site": 240,
    "Google Maps": 300,
}


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Buscador de Empresas - Google Maps")
        self.geometry("1280x760")
        self.minsize(1024, 640)

        self.queue = queue.Queue()
        self.stop_event = threading.Event()
        self.scraper_thread = None
        self.running = False
        self.results = []
        self.filters = FilterManager(require_phone=True)
        self.processed = 0

        self.var_nome = tk.StringVar()
        self.var_categoria = tk.StringVar()
        self.var_cidade = tk.StringVar()
        self.var_palavra = tk.StringVar()
        self.var_quantidade = tk.StringVar(value="50")
        self.var_phone = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Preencha os filtros e clique em Iniciar busca.")
        self.counters_var = tk.StringVar(value="Encontradas: 0    Processadas: 0")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._poll)

    # ------------------------------------------------------------- interface

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        form = ctk.CTkFrame(self)
        form.grid(row=0, column=0, padx=10, pady=(10, 4), sticky="ew")
        for col in range(6):
            form.grid_columnconfigure(col, weight=1)

        self.entry_nome = ctk.CTkEntry(form, textvariable=self.var_nome, placeholder_text="Ex.: Churrascaria")
        self.entry_categoria = ctk.CTkEntry(form, textvariable=self.var_categoria, placeholder_text="Ex.: Restaurantes")
        self.entry_palavra = ctk.CTkEntry(form, textvariable=self.var_palavra, placeholder_text="Opcional")
        self.entry_cidade = ctk.CTkEntry(form, textvariable=self.var_cidade, placeholder_text="Ex.: Campinas")
        self.entry_quantidade = ctk.CTkEntry(form, textvariable=self.var_quantidade, placeholder_text="1 a 500")

        self._stack(form, "Nome da empresa", self.entry_nome, 0, 0)
        self._stack(form, "Segmento / Categoria", self.entry_categoria, 0, 1)
        self._stack(form, "Palavra-chave", self.entry_palavra, 0, 2)
        self._stack(form, "Cidade ou região", self.entry_cidade, 1, 0)
        self._stack(form, "Quantidade máxima", self.entry_quantidade, 1, 1)

        tel_block = ctk.CTkFrame(form, fg_color="transparent")
        tel_block.grid(row=1, column=2, sticky="nw", padx=8, pady=6)
        ctk.CTkLabel(tel_block, text="Filtro").pack(anchor="w")
        self.chk_phone = ctk.CTkCheckBox(tel_block, text="Somente com telefone", variable=self.var_phone)
        self.chk_phone.pack(anchor="w", pady=(4, 0))

        btns = ctk.CTkFrame(form, fg_color="transparent")
        btns.grid(row=2, column=0, columnspan=6, sticky="ew", padx=8, pady=(10, 8))
        btns.grid_columnconfigure(2, weight=1)
        self.btn_start = ctk.CTkButton(
            btns, text="Iniciar busca", command=self._start,
            fg_color="#1E6B3A", hover_color="#25874A", width=170,
        )
        self.btn_start.grid(row=0, column=0, padx=(0, 8))
        self.btn_stop = ctk.CTkButton(
            btns, text="Parar busca", command=self._stop,
            fg_color="#8B2E2E", hover_color="#A83838", width=170, state="disabled",
        )
        self.btn_stop.grid(row=0, column=1)
        ctk.CTkLabel(
            btns,
            text="Ex.: Barbearias em Campinas · Clínicas em Sumaré · Restaurantes em Americana",
            text_color="gray",
        ).grid(row=0, column=2, sticky="e")

        table = ttk.Frame(self)
        table.grid(row=1, column=0, padx=10, pady=4, sticky="nsew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Treeview",
            background="#212121", fieldbackground="#212121",
            foreground="#e6e6e6", rowheight=24, borderwidth=0,
        )
        style.configure("Treeview.Heading", background="#333333", foreground="#ffffff",
                        font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#1F6AA5")])

        self.tree = ttk.Treeview(table, columns=COLUMNS, show="headings", selectmode="browse")
        for col in COLUMNS:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=COLUMNS_WIDTH.get(col, 150), anchor="w", stretch=False)
        vsb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        bottom = ctk.CTkFrame(self)
        bottom.grid(row=2, column=0, padx=10, pady=4, sticky="ew")
        bottom.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(bottom, textvariable=self.counters_var, anchor="w").grid(row=0, column=0, padx=12)
        self.prog = ctk.CTkProgressBar(bottom, mode="determinate")
        self.prog.set(0)
        self.prog.grid(row=0, column=1, sticky="ew", padx=12)
        ctk.CTkButton(
            bottom, text="Exportar Excel", width=140,
            command=lambda: self._export("excel"),
        ).grid(row=0, column=2, padx=(0, 8))
        ctk.CTkButton(
            bottom, text="Exportar CSV", width=140,
            command=lambda: self._export("csv"),
        ).grid(row=0, column=3, padx=(0, 12))

        ctk.CTkLabel(self, textvariable=self.status_var, anchor="w").grid(
            row=3, column=0, sticky="ew", padx=12, pady=(0, 6)
        )

    def _stack(self, parent, text, entry, row, col):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=col, sticky="ew", padx=8, pady=6)
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text=text).grid(row=0, column=0, sticky="w")
        entry.grid(row=1, column=0, sticky="ew")

    # ---------------------------------------------------------------- actions

    def _start(self):
        if self.running:
            return
        max_results = self._read_max()
        if max_results is None:
            messagebox.showwarning("Quantidade inválida", "Informe um número inteiro de 1 a 500.")
            return
        query = self._build_query()
        if not query:
            messagebox.showwarning("Busca vazia", "Preencha ao menos um dos campos para buscar.")
            return

        self.results = []
        self.processed = 0
        self.filters = FilterManager(require_phone=self.var_phone.get())
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.counters_var.set("Encontradas: 0    Processadas: 0")
        self.prog.set(0)

        self.stop_event = threading.Event()
        self.scraper_thread = Scraper(query, max_results, self.stop_event, self.queue)
        self.running = True
        self._set_running_ui(True)
        self.status_var.set("Iniciando busca: {}".format(query))
        self.scraper_thread.start()

    def _stop(self):
        if not self.running:
            return
        self.stop_event.set()
        self.status_var.set("Interrompendo busca. Aguarde o navegador fechar...")

    def _export(self, kind):
        if not self.results:
            messagebox.showinfo("Sem dados", "Nenhuma empresa para exportar.")
            return
        if kind == "excel":
            filetypes = [("Excel", "*.xlsx")]
            default_ext = ".xlsx"
        else:
            filetypes = [("CSV", "*.csv")]
            default_ext = ".csv"
        path = filedialog.asksaveasfilename(
            defaultextension=default_ext,
            filetypes=filetypes,
            initialfile="empresas_google_maps{}".format(default_ext),
        )
        if not path:
            return
        try:
            if kind == "excel":
                export_excel(self.results, path)
            else:
                export_csv(self.results, path)
        except Exception as exc:
            messagebox.showerror("Erro ao exportar", str(exc))
            return
        messagebox.showinfo("Exportado", "Dados salvos em:\n{}".format(path))

    # ------------------------------------------------------------------ poll

    def _poll(self):
        if self.running and self.scraper_thread is not None and not self.scraper_thread.is_alive():
            self._finish()

        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg.get("type")
                if kind == "result":
                    added, business = self.filters.process(msg.get("data") or {})
                    if added:
                        self.tree.insert("", "end", values=self._display(business))
                        self.results.append(business)
                elif kind == "progress":
                    self.processed = max(self.processed, int(msg.get("value", 0)))
                elif kind == "status":
                    self.status_var.set(str(msg.get("text", "")))
        except queue.Empty:
            pass

        self.counters_var.set(
            "Encontradas: {}    Processadas: {}".format(len(self.results), self.processed)
        )
        if self.running:
            total = self._read_max() or 1
            self.prog.set(min(self.processed / max(total, 1), 1.0))
        self.after(120, self._poll)

    def _finish(self):
        if not self.running:
            return
        self.running = False
        self._set_running_ui(False)
        self.prog.set(1.0)
        if self.stop_event.is_set():
            self.status_var.set(
                "Busca interrompida. {} empresa(s) com telefone.".format(len(self.results))
            )
        else:
            self.status_var.set(
                "Busca finalizada. {} empresa(s) com telefone.".format(len(self.results))
            )

    def _set_running_ui(self, running):
        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")
        for widget in (self.entry_nome, self.entry_categoria, self.entry_cidade,
                       self.entry_palavra, self.entry_quantidade):
            widget.configure(state="disabled" if running else "normal")
        self.chk_phone.configure(state="disabled" if running else "normal")

    def _display(self, business):
        return [business.get(HEADER_TO_FIELD[h], "") or "" for h in COLUMNS]

    def _build_query(self):
        parts = [
            p for p in (
                self.var_nome.get().strip(),
                self.var_categoria.get().strip(),
                self.var_palavra.get().strip(),
            ) if p
        ]
        cidade = self.var_cidade.get().strip()
        if cidade:
            parts.append("em {}".format(cidade))
        return " ".join(parts).strip()

    def _read_max(self):
        try:
            n = int(self.var_quantidade.get().strip())
        except ValueError:
            return None
        return max(1, min(500, n))

    def _on_close(self):
        self.stop_event.set()
        self.destroy()