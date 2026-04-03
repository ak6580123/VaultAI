"""
vault_ai_gui.py
Tkinter GUI for Vault AI + TheHelpers.vercel.app browser/downloader

ABOUT THE DOWNLOAD MECHANISM:
==============================
TheHelpers website renders its "View" links via JavaScript (Next.js/React).
The actual URLs are Google Drive file links embedded dynamically — they are NOT
present in the raw HTML. This means:

  - Simple HTTP scraping (requests + BeautifulSoup) cannot see the actual file IDs.
  - To get real download URLs, we use a headless Selenium WebDriver to fully
    render the JS, then extract href attributes from the rendered DOM.
  - Once we have a Google Drive file ID (from a URL like
    https://drive.google.com/file/d/FILE_ID/view), we use the standard
    direct-download URL pattern:
      https://drive.google.com/uc?export=download&id=FILE_ID

REQUIREMENTS (pip install):
  pip install selenium webdriver-manager requests tk
  Also ensure Google Chrome is installed.
"""

import os
import re
import sys
import json
import pickle
import shutil
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from datetime import datetime
import urllib.parse
import urllib.request
import urllib.error

# ── Optional heavy deps (graceful degradation if missing) ──
try:
    import faiss
    import numpy as np
    from sentence_transformers import SentenceTransformer
    import ollama
    VAULT_AVAILABLE = True
except ImportError:
    VAULT_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.chrome.service import Service
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# ══════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════
NOTES_FOLDER   = os.path.expanduser(r"C:\Users\ASUS\Obsidian")
INDEX_FILE     = "faiss_index.bin"
META_FILE      = "metadata.pkl"
LOG_FILE       = "chat_logs.json"
CHUNK_SIZE     = 800
TOP_K          = 5
MODEL          = "llama3"
EMBED_MODEL    = "all-MiniLM-L6-v2"
MAX_TOKENS     = 2000
BASE_URL       = "https://thehelpers.vercel.app"
DOWNLOAD_DIR   = os.path.join(os.path.expanduser("~"), "Downloads", "TheHelper")

# ══════════════════════════════════════════════
#  COLOUR PALETTE  (dark industrial theme)
# ══════════════════════════════════════════════
BG       = "#0f0f0f"
BG2      = "#1a1a1a"
BG3      = "#222222"
ACCENT   = "#e8c547"      # warm gold
ACCENT2  = "#4fc3f7"      # sky blue for links
FG       = "#e0e0e0"
FG_DIM   = "#777777"
RED      = "#ef5350"
GREEN    = "#66bb6a"
BORDER   = "#333333"
FONT_MONO = ("Consolas", 10)
FONT_UI   = ("Segoe UI", 10)
FONT_H1   = ("Segoe UI", 14, "bold")
FONT_H2   = ("Segoe UI", 11, "bold")

# ══════════════════════════════════════════════
#  HELPERS SCRAPER (Selenium-based)
# ══════════════════════════════════════════════

def get_driver():
    """Spin up a headless Chrome driver."""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1280,800")
    opts.add_argument("--log-level=3")
    svc = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=svc, options=opts)


def fetch_semesters():
    return [str(i) for i in range(1, 9)]


def fetch_subjects(sem: str, log_fn=None):
    """Return list of subject names for a given semester."""
    url = f"{BASE_URL}/semesters/{sem}"
    if log_fn:
        log_fn(f"Fetching subjects for Semester {sem}…")

    if not SELENIUM_AVAILABLE:
        if log_fn:
            log_fn("⚠  Selenium not installed — cannot fetch live data.")
        return []

    driver = get_driver()
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "a"))
        )
        anchors = driver.find_elements(By.XPATH,
            f"//a[contains(@href,'/semesters/{sem}/subjects/')]")
        subjects = []
        for a in anchors:
            href = a.get_attribute("href")
            name = href.split("/subjects/")[-1]
            name = urllib.parse.unquote(name)
            if name:
                subjects.append(name)
        return list(dict.fromkeys(subjects))   # deduplicate preserving order
    finally:
        driver.quit()


def fetch_resources(sem: str, subject: str, log_fn=None):
    """Return list of (label, url) tuples for all 'View' links on a subject page."""
    encoded = urllib.parse.quote(subject)
    url = f"{BASE_URL}/semesters/{sem}/subjects/{encoded}"
    if log_fn:
        log_fn(f"Fetching resources for {subject}…")

    if not SELENIUM_AVAILABLE:
        if log_fn:
            log_fn("⚠  Selenium not installed.")
        return []

    driver = get_driver()
    try:
        driver.get(url)
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.TAG_NAME, "li"))
        )
        results = []
        items = driver.find_elements(By.XPATH, "//li")
        for item in items:
            try:
                label_text = item.text.strip()
                link = item.find_element(By.TAG_NAME, "a")
                href = link.get_attribute("href") or ""
                if href and label_text:
                    results.append((label_text, href))
            except Exception:
                pass
        return results
    finally:
        driver.quit()


def gdrive_id_from_url(url: str):
    """Extract Google Drive file ID from various Drive URL formats."""
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
        r"/d/([a-zA-Z0-9_-]+)/",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def make_direct_download(url: str):
    """Convert a Google Drive view/preview URL to a direct-download URL."""
    fid = gdrive_id_from_url(url)
    if fid:
        return f"https://drive.google.com/uc?export=download&id={fid}"
    # Fallback: return as-is (might be a direct PDF/link)
    return url


def download_file(url: str, dest_dir: str, label: str, log_fn=None):
    """Download a file from url into dest_dir. Returns saved path or None."""
    os.makedirs(dest_dir, exist_ok=True)

    # Resolve Google Drive link
    if "drive.google.com" in url or "docs.google.com" in url:
        dl_url = make_direct_download(url)
    else:
        dl_url = url

    # Sanitise filename
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", label)
    if not safe_name.endswith(".pdf"):
        safe_name += ".pdf"

    dest_path = os.path.join(dest_dir, safe_name)

    if log_fn:
        log_fn(f"⬇  Downloading: {safe_name}")

    try:
        if REQUESTS_AVAILABLE:
            resp = requests.get(dl_url, stream=True, timeout=30,
                                headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
        else:
            req = urllib.request.Request(dl_url,
                headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                with open(dest_path, "wb") as f:
                    f.write(r.read())

        if log_fn:
            log_fn(f"✔  Saved → {dest_path}")
        return dest_path
    except Exception as e:
        if log_fn:
            log_fn(f"✘  Failed: {e}")
        return None


# ══════════════════════════════════════════════
#  VAULT AI CORE  (unchanged logic from original)
# ══════════════════════════════════════════════

embed_model = None
index       = None
metadata    = None

def load_vault(log_fn=None):
    global embed_model, index, metadata
    if not VAULT_AVAILABLE:
        if log_fn:
            log_fn("⚠  Vault deps missing (faiss, sentence-transformers, ollama).")
        return False
    embed_model = SentenceTransformer(EMBED_MODEL)
    index, metadata = _build_or_load(log_fn)
    return True

def _build_or_load(log_fn=None):
    if os.path.exists(INDEX_FILE) and os.path.exists(META_FILE):
        if log_fn: log_fn("Loading existing FAISS index…")
        return faiss.read_index(INDEX_FILE), pickle.load(open(META_FILE, "rb"))

    if log_fn: log_fn("Building FAISS index from notes…")
    docs, meta = [], []
    for root, _, files in os.walk(NOTES_FOLDER):
        for f in files:
            if f.endswith(".md"):
                path = os.path.join(root, f)
                try:
                    text = open(path, encoding="utf-8").read()
                    for c in [text[i:i+CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)]:
                        docs.append(c)
                        meta.append({"text": c, "path": path})
                except Exception:
                    pass

    emb = embed_model.encode(docs).astype("float32")
    idx = faiss.IndexFlatL2(emb.shape[1])
    idx.add(emb)
    faiss.write_index(idx, INDEX_FILE)
    pickle.dump(meta, open(META_FILE, "wb"))
    if log_fn: log_fn(f"Index built: {len(docs)} chunks.")
    return idx, meta

def retrieve(query: str) -> str:
    q = embed_model.encode([query]).astype("float32")
    _, ids = index.search(q, TOP_K)
    return "\n\n".join(metadata[i]["text"] for i in ids[0])

def build_prompt(context: str, topic: str):
    return [
        {"role": "system", "content":
            "You MUST answer fully.\n\n"
            "For the given topic, provide:\n"
            "1. Explanation\n2. Step-by-step Algorithm\n"
            "3. Pseudocode\n4. C code\n\n"
            "Do NOT skip anything. Do NOT stop early."},
        {"role": "user", "content": f"{context}\n\nTopic:\n{topic}"}
    ]

def stream_generate(messages, out_fn):
    stream = ollama.chat(model=MODEL, messages=messages, stream=True,
                         options={"num_predict": MAX_TOKENS})
    full = ""
    for chunk in stream:
        text = chunk["message"]["content"]
        out_fn(text)
        full += text
    return full

def append_log(q: str, a: str):
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            logs = json.load(open(LOG_FILE, "r", encoding="utf-8"))
        except Exception:
            logs = []
    logs.append({"timestamp": datetime.now().isoformat(), "query": q, "answer": a})
    json.dump(logs, open(LOG_FILE, "w", encoding="utf-8"), indent=2)


# ══════════════════════════════════════════════
#  GUI
# ══════════════════════════════════════════════

class VaultGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Vault AI  ·  TheHelper Browser")
        self.root.geometry("1260x780")
        self.root.minsize(900, 600)
        self.root.configure(bg=BG)

        self._apply_styles()
        self._build_ui()
        self._vault_ready = False
        self._thread = None

        # Pre-load vault in background
        threading.Thread(target=self._init_vault, daemon=True).start()

    # ── STYLE ─────────────────────────────────
    def _apply_styles(self):
        s = ttk.Style()
        s.theme_use("clam")

        s.configure(".",
            background=BG, foreground=FG,
            fieldbackground=BG2, bordercolor=BORDER,
            troughcolor=BG3, relief="flat")

        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab",
            background=BG2, foreground=FG_DIM,
            padding=[16, 6], font=FONT_UI, borderwidth=0)
        s.map("TNotebook.Tab",
            background=[("selected", BG3)],
            foreground=[("selected", ACCENT)])

        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=FG, font=FONT_UI)
        s.configure("TButton",
            background=BG3, foreground=FG,
            font=FONT_UI, relief="flat", borderwidth=0, padding=[10, 5])
        s.map("TButton",
            background=[("active", ACCENT), ("pressed", ACCENT)],
            foreground=[("active", BG)])

        s.configure("Accent.TButton",
            background=ACCENT, foreground=BG,
            font=(*FONT_UI[:2], "bold"), relief="flat", padding=[10, 5])
        s.map("Accent.TButton",
            background=[("active", "#f5d76e")])

        s.configure("TCombobox",
            selectbackground=ACCENT, selectforeground=BG,
            fieldbackground=BG2, background=BG2, foreground=FG)
        s.configure("TScrollbar",
            background=BG2, troughcolor=BG, arrowcolor=FG_DIM)
        s.configure("TEntry",
            fieldbackground=BG2, foreground=FG,
            insertcolor=ACCENT, relief="flat", padding=6)
        s.configure("Treeview",
            background=BG2, foreground=FG,
            fieldbackground=BG2, rowheight=26,
            font=FONT_UI)
        s.configure("Treeview.Heading",
            background=BG3, foreground=ACCENT,
            font=(*FONT_UI[:2], "bold"), relief="flat")
        s.map("Treeview",
            background=[("selected", ACCENT)],
            foreground=[("selected", BG)])

    # ── LAYOUT ────────────────────────────────
    def _build_ui(self):
        # ─ Header bar ─
        header = tk.Frame(self.root, bg=BG, pady=10)
        header.pack(fill="x", padx=20)

        tk.Label(header, text="VAULT AI", font=("Courier New", 18, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left")
        tk.Label(header, text=" + TheHelper Browser",
                 font=("Segoe UI", 11), bg=BG, fg=FG_DIM).pack(side="left", padx=4)

        self._status_var = tk.StringVar(value="Initialising…")
        tk.Label(header, textvariable=self._status_var,
                 font=FONT_UI, bg=BG, fg=FG_DIM).pack(side="right")

        # ─ Separator ─
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

        # ─ Notebook ─
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=0, pady=0)

        self._build_chat_tab()
        self._build_helper_tab()
        self._build_log_tab()

    # ── TAB 1: Vault AI Chat ──────────────────
    def _build_chat_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  🤖  Vault AI  ")

        # Output area
        out_frame = tk.Frame(tab, bg=BG)
        out_frame.pack(fill="both", expand=True, padx=16, pady=(12, 4))

        self.chat_out = scrolledtext.ScrolledText(
            out_frame, wrap="word", bg=BG2, fg=FG,
            insertbackground=ACCENT, font=FONT_MONO,
            relief="flat", borderwidth=0, state="disabled",
            selectbackground=ACCENT, selectforeground=BG)
        self.chat_out.pack(fill="both", expand=True)
        self.chat_out.tag_configure("accent",  foreground=ACCENT)
        self.chat_out.tag_configure("dim",     foreground=FG_DIM)
        self.chat_out.tag_configure("green",   foreground=GREEN)
        self.chat_out.tag_configure("red",     foreground=RED)
        self.chat_out.tag_configure("heading", foreground=ACCENT2,
                                    font=(*FONT_MONO[:1], FONT_MONO[1]+1, "bold"))

        # Input row
        inp_frame = tk.Frame(tab, bg=BG, pady=8)
        inp_frame.pack(fill="x", padx=16)

        self.chat_input = tk.Text(inp_frame, height=4, bg=BG2, fg=FG,
                                  insertbackground=ACCENT, font=FONT_MONO,
                                  relief="flat", wrap="word",
                                  selectbackground=ACCENT, selectforeground=BG)
        self.chat_input.pack(side="left", fill="both", expand=True)
        self.chat_input.bind("<Return>", self._on_enter)
        self.chat_input.bind("<Control-j>", self._insert_newline)

        btn_col = tk.Frame(inp_frame, bg=BG, padx=6)
        btn_col.pack(side="left", fill="y")

        ttk.Button(btn_col, text="Send\n(Enter)",
                   style="Accent.TButton",
                   command=self._send_query).pack(fill="x", pady=(0, 4))
        ttk.Button(btn_col, text="Clear",
                   command=self._clear_chat).pack(fill="x")

        tk.Label(tab, text="Enter = Send · Ctrl+J = Newline",
                 font=("Segoe UI", 8), bg=BG, fg=FG_DIM).pack(pady=2)

    def _on_enter(self, event):
        self._send_query()
        return "break"

    def _insert_newline(self, event):
        self.chat_input.insert("insert", "\n")
        return "break"

    def _send_query(self):
        query = self.chat_input.get("1.0", "end").strip()
        if not query:
            return
        self.chat_input.delete("1.0", "end")
        threading.Thread(target=self._run_query, args=(query,), daemon=True).start()

    def _run_query(self, query):
        if not self._vault_ready:
            self._chat_write("⚠  Vault not ready yet — wait a moment.\n", "red")
            return

        topics = [l.strip("─•- ") for l in query.split("\n") if l.strip()]
        topics = topics if len(topics) > 1 else [query]
        full_answer = ""

        for topic in topics:
            self._chat_write(f"\n══ {topic} ══\n", "heading")
            context  = retrieve(topic)
            messages = build_prompt(context, topic)
            ans = stream_generate(messages, lambda t: self._chat_write(t))
            full_answer += f"\n\n══ {topic} ══\n{ans}"

        append_log(query, full_answer)
        self._chat_write("\n\n── Done ──\n", "dim")

    def _chat_write(self, text, tag=None):
        self.chat_out.configure(state="normal")
        if tag:
            self.chat_out.insert("end", text, tag)
        else:
            self.chat_out.insert("end", text)
        self.chat_out.see("end")
        self.chat_out.configure(state="disabled")

    def _clear_chat(self):
        self.chat_out.configure(state="normal")
        self.chat_out.delete("1.0", "end")
        self.chat_out.configure(state="disabled")

    # ── TAB 2: TheHelper Browser ──────────────
    def _build_helper_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  📚  TheHelper  ")

        # ─ Top controls ─
        ctrl = tk.Frame(tab, bg=BG, pady=8)
        ctrl.pack(fill="x", padx=16)

        tk.Label(ctrl, text="Semester:", bg=BG, fg=FG, font=FONT_UI).pack(side="left")
        self.sem_var = tk.StringVar(value="1")
        sem_cb = ttk.Combobox(ctrl, textvariable=self.sem_var,
                              values=fetch_semesters(),
                              width=4, state="readonly")
        sem_cb.pack(side="left", padx=(4, 16))

        ttk.Button(ctrl, text="Load Subjects",
                   command=self._load_subjects).pack(side="left", padx=4)
        ttk.Button(ctrl, text="Load Resources",
                   command=self._load_resources).pack(side="left", padx=4)

        self.dl_dir_var = tk.StringVar(value=DOWNLOAD_DIR)
        ttk.Button(ctrl, text="Save To…",
                   command=self._choose_dl_dir).pack(side="left", padx=(24, 4))
        tk.Label(ctrl, textvariable=self.dl_dir_var,
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 8)).pack(side="left")

        # ─ Paned layout ─
        paned = tk.PanedWindow(tab, orient="horizontal",
                               bg=BORDER, sashwidth=4,
                               sashrelief="flat")
        paned.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        # Subject list
        subj_frame = tk.Frame(paned, bg=BG)
        tk.Label(subj_frame, text="Subjects", font=FONT_H2,
                 bg=BG, fg=ACCENT).pack(anchor="w", pady=(4, 2))

        self.subj_list = tk.Listbox(subj_frame,
                                    bg=BG2, fg=FG, selectbackground=ACCENT,
                                    selectforeground=BG, font=FONT_UI,
                                    relief="flat", borderwidth=0,
                                    activestyle="none", exportselection=False)
        self.subj_list.pack(fill="both", expand=True)
        self.subj_list.bind("<<ListboxSelect>>", lambda e: self._load_resources())
        paned.add(subj_frame, minsize=200)

        # Resource tree
        res_frame = tk.Frame(paned, bg=BG)
        tk.Label(res_frame, text="Resources", font=FONT_H2,
                 bg=BG, fg=ACCENT).pack(anchor="w", pady=(4, 2))

        tree_scroll = ttk.Scrollbar(res_frame, orient="vertical")
        self.res_tree = ttk.Treeview(res_frame,
                                     columns=("url",), show="tree",
                                     yscrollcommand=tree_scroll.set,
                                     selectmode="extended")
        tree_scroll.config(command=self.res_tree.yview)
        self.res_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        paned.add(res_frame, minsize=400)

        # ─ Action row ─
        action = tk.Frame(tab, bg=BG, pady=4)
        action.pack(fill="x", padx=16)

        ttk.Button(action, text="⬇  Download Selected",
                   style="Accent.TButton",
                   command=self._download_selected).pack(side="left", padx=4)
        ttk.Button(action, text="⬇  Download All",
                   command=self._download_all).pack(side="left", padx=4)
        ttk.Button(action, text="📂  Open Folder",
                   command=self._open_folder).pack(side="left", padx=4)

        # ─ Log area ─
        self.helper_log = scrolledtext.ScrolledText(
            tab, height=7, bg=BG2, fg=FG_DIM,
            font=("Consolas", 9), relief="flat", state="disabled",
            wrap="word", insertbackground=ACCENT)
        self.helper_log.pack(fill="x", padx=16, pady=(0, 8))

        self._resources_cache = []   # list of (label, url)

    def _hlog(self, msg):
        self.helper_log.configure(state="normal")
        self.helper_log.insert("end", msg + "\n")
        self.helper_log.see("end")
        self.helper_log.configure(state="disabled")

    def _choose_dl_dir(self):
        d = filedialog.askdirectory(title="Choose download folder",
                                    initialdir=self.dl_dir_var.get())
        if d:
            self.dl_dir_var.set(d)

    def _load_subjects(self):
        sem = self.sem_var.get()
        self.subj_list.delete(0, "end")
        self._hlog(f"Loading subjects for Semester {sem}…")

        if not SELENIUM_AVAILABLE:
            self._hlog("⚠  Selenium not installed.\n"
                       "   Run: pip install selenium webdriver-manager")
            return

        def task():
            subjects = fetch_subjects(sem, self._hlog)
            self.root.after(0, lambda: self._populate_subjects(subjects))
        threading.Thread(target=task, daemon=True).start()

    def _populate_subjects(self, subjects):
        self.subj_list.delete(0, "end")
        for s in subjects:
            self.subj_list.insert("end", s)
        self._hlog(f"✔  {len(subjects)} subjects loaded.")

    def _load_resources(self):
        sel = self.subj_list.curselection()
        if not sel:
            return
        subject = self.subj_list.get(sel[0])
        sem     = self.sem_var.get()
        self.res_tree.delete(*self.res_tree.get_children())
        self._resources_cache = []
        self._hlog(f"Loading resources: {subject}…")

        if not SELENIUM_AVAILABLE:
            self._hlog("⚠  Selenium not installed.")
            return

        def task():
            resources = fetch_resources(sem, subject, self._hlog)
            self.root.after(0, lambda: self._populate_resources(resources))
        threading.Thread(target=task, daemon=True).start()

    def _populate_resources(self, resources):
        self.res_tree.delete(*self.res_tree.get_children())
        self._resources_cache = resources

        # Group by section heuristic (PYQ / Study Notes / Exam Strategies)
        sections = {"Previous Year Questions": [], "Study Notes": [],
                    "Exam Strategies": [], "Other": []}
        for lbl, url in resources:
            low = lbl.lower()
            if "pyq" in low or "question" in low or "ct" in low or "mcq" in low:
                sections["Previous Year Questions"].append((lbl, url))
            elif "chapter" in low or "note" in low or "material" in low or "book" in low:
                sections["Study Notes"].append((lbl, url))
            elif "strateg" in low or "rule" in low:
                sections["Exam Strategies"].append((lbl, url))
            else:
                sections["Other"].append((lbl, url))

        for sec, items in sections.items():
            if not items:
                continue
            node = self.res_tree.insert("", "end", text=f"  {sec} ({len(items)})",
                                        open=True)
            for lbl, url in items:
                self.res_tree.insert(node, "end", text=f"  {lbl}",
                                     values=(url,))
        self._hlog(f"✔  {len(resources)} resources loaded.")

    def _selected_resources(self):
        items = []
        for iid in self.res_tree.selection():
            vals = self.res_tree.item(iid, "values")
            if vals and vals[0]:
                text = self.res_tree.item(iid, "text").strip()
                items.append((text, vals[0]))
        return items

    def _download_selected(self):
        items = self._selected_resources()
        if not items:
            messagebox.showinfo("No Selection",
                                "Please select at least one resource from the tree.")
            return
        threading.Thread(target=self._run_downloads, args=(items,), daemon=True).start()

    def _download_all(self):
        if not self._resources_cache:
            messagebox.showinfo("No Resources", "Load resources first.")
            return
        threading.Thread(target=self._run_downloads,
                         args=(self._resources_cache,), daemon=True).start()

    def _run_downloads(self, items):
        dest = self.dl_dir_var.get()
        for lbl, url in items:
            download_file(url, dest, lbl, self._hlog)
        self._hlog(f"\n✔  Download batch complete → {dest}\n")

    def _open_folder(self):
        dest = self.dl_dir_var.get()
        os.makedirs(dest, exist_ok=True)
        os.startfile(dest) if sys.platform == "win32" else os.system(f'open "{dest}"')

    # ── TAB 3: Chat Log ────────────────────────
    def _build_log_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  📋  Chat Log  ")

        ctrl = tk.Frame(tab, bg=BG, pady=8)
        ctrl.pack(fill="x", padx=16)
        ttk.Button(ctrl, text="Refresh", command=self._refresh_logs).pack(side="left")
        ttk.Button(ctrl, text="Clear Log File",
                   command=self._clear_log_file).pack(side="left", padx=8)

        self.log_view = scrolledtext.ScrolledText(
            tab, wrap="word", bg=BG2, fg=FG,
            font=FONT_MONO, relief="flat", state="disabled",
            selectbackground=ACCENT, selectforeground=BG)
        self.log_view.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.log_view.tag_configure("q", foreground=ACCENT,
                                    font=(*FONT_MONO[:1], FONT_MONO[1], "bold"))
        self.log_view.tag_configure("ts", foreground=FG_DIM)
        self._refresh_logs()

    def _refresh_logs(self):
        self.log_view.configure(state="normal")
        self.log_view.delete("1.0", "end")
        if not os.path.exists(LOG_FILE):
            self.log_view.insert("end", "No logs yet.")
        else:
            try:
                logs = json.load(open(LOG_FILE, "r", encoding="utf-8"))
                for entry in reversed(logs[-50:]):
                    self.log_view.insert("end",
                        f"[{entry['timestamp'][:19]}]\n", "ts")
                    self.log_view.insert("end",
                        f"Q: {entry['query'][:120]}\n", "q")
                    self.log_view.insert("end",
                        entry['answer'][:400] + "\n\n")
            except Exception as e:
                self.log_view.insert("end", f"Error reading log: {e}")
        self.log_view.configure(state="disabled")

    def _clear_log_file(self):
        if messagebox.askyesno("Clear Log", "Delete all chat history?"):
            with open(LOG_FILE, "w") as f:
                json.dump([], f)
            self._refresh_logs()

    # ── VAULT INIT ────────────────────────────
    def _init_vault(self):
        self._set_status("Loading vault…")
        ok = load_vault(self._log_to_chat_init)
        if ok:
            self._vault_ready = True
            self._set_status("✔  Vault ready")
            self._chat_write("Vault AI ready. Type a topic and press Enter.\n", "green")
        else:
            self._set_status("⚠  Vault unavailable")
            self._chat_write(
                "Vault deps missing. Install:\n"
                "  pip install faiss-cpu sentence-transformers ollama\n", "red")

    def _log_to_chat_init(self, msg):
        self._chat_write(msg + "\n", "dim")

    def _set_status(self, msg):
        self.root.after(0, lambda: self._status_var.set(msg))


# ══════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════

if __name__ == "__main__":
    root = tk.Tk()
    app  = VaultGUI(root)
    root.mainloop()
