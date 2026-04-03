"""
vaultai/dep_check.py  --  Runtime dependency checker.
Verifies Ollama and Obsidian before the main GUI opens.
"""
import os, sys, shutil, socket, subprocess, threading, webbrowser
import tkinter as tk
from tkinter import ttk

OLLAMA_DOWNLOAD   = "https://ollama.com/download"
OBSIDIAN_DOWNLOAD = "https://obsidian.md/"
OLLAMA_HOST, OLLAMA_PORT = "127.0.0.1", 11434
DEFAULT_MODEL = "llama3"

def _is_ollama_installed():
    return shutil.which("ollama") is not None

def _is_ollama_running():
    try:
        s = socket.create_connection((OLLAMA_HOST, OLLAMA_PORT), timeout=2)
        s.close(); return True
    except OSError:
        return False

def _ollama_list_models():
    try:
        r = subprocess.run(["ollama","list"], capture_output=True, text=True, timeout=10)
        models = []
        for line in r.stdout.strip().splitlines()[1:]:
            parts = line.split()
            if parts: models.append(parts[0].split(":")[0])
        return models
    except Exception:
        return []

def _start_ollama_server():
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0
        subprocess.Popen(["ollama","serve"], creationflags=flags,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return False
    import time
    for _ in range(30):
        time.sleep(0.5)
        if _is_ollama_running(): return True
    return False

def _is_obsidian_installed():
    if sys.platform == "win32":
        locs = [
            os.path.join(os.environ.get("LOCALAPPDATA",""),"Programs","obsidian","Obsidian.exe"),
            os.path.join(os.environ.get("PROGRAMFILES",""),"Obsidian","Obsidian.exe"),
        ]
        return any(os.path.exists(p) for p in locs)
    elif sys.platform == "darwin":
        return os.path.exists("/Applications/Obsidian.app")
    return bool(shutil.which("obsidian"))

def _pull_model(model, log_fn):
    try:
        proc = subprocess.Popen(["ollama","pull",model],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout: log_fn(line.rstrip())
        proc.wait()
        return proc.returncode == 0
    except Exception as exc:
        log_fn("Error: " + str(exc)); return False

class DepStatus:
    def __init__(self):
        self.ollama_installed = self.ollama_running = self.obsidian_installed = False
        self.models = []
    def ollama_ok(self):   return self.ollama_installed and self.ollama_running
    def has_model(self):   return bool(self.models)
    def can_proceed(self): return self.ollama_ok()

def check_dependencies():
    s = DepStatus()
    s.ollama_installed   = _is_ollama_installed()
    s.ollama_running     = _is_ollama_running()  if s.ollama_installed else False
    s.models             = _ollama_list_models() if s.ollama_running   else []
    s.obsidian_installed = _is_obsidian_installed()
    return s

BG,BG2,BG3   = "#0f0f0f","#1a1a1a","#222222"
FG,FG_DIM    = "#e0e0e0","#777777"
ACCENT,GREEN = "#e8c547","#66bb6a"
RED,ORANGE   = "#ef5350","#ffa726"
FONT_B  = ("Segoe UI",10,"bold")
FONT_SM = ("Segoe UI",9)
FONT_H  = ("Segoe UI",14,"bold")

class DependencyDialog(tk.Toplevel):
    def __init__(self, parent, status, on_continue):
        super().__init__(parent)
        self.title("VaultAI - Checking Dependencies")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._status = status
        self._on_continue = on_continue
        self._pulling = False
        self._build()
        self._refresh()
        self.update_idletasks()
        sw,sh = self.winfo_screenwidth(),self.winfo_screenheight()
        w,h   = self.winfo_reqwidth(),self.winfo_reqheight()
        self.geometry("+%d+%d" % ((sw-w)//2,(sh-h)//2))

    def _build(self):
        tk.Label(self,text="Dependency Check",font=FONT_H,
                 bg=BG,fg=ACCENT,pady=12).pack(fill="x",padx=20)
        tk.Label(self,
                 text="VaultAI needs these tools.\n"
                      "Items marked [!] must be fixed before continuing.",
                 font=FONT_SM,bg=BG,fg=FG_DIM,justify="center").pack(padx=20)
        rf = tk.Frame(self,bg=BG2,padx=16,pady=12)
        rf.pack(fill="x",padx=20,pady=(12,0))
        self._row_oi = self._make_row(rf,"Ollama installed",0,"Download",
            lambda: webbrowser.open(OLLAMA_DOWNLOAD))
        self._row_or = self._make_row(rf,"Ollama server running",1,
            "Start",self._start_server)
        self._row_m  = self._make_row(rf,"Model available ("+DEFAULT_MODEL+")",2,
            "Pull",self._pull_default_model)
        self._row_ob = self._make_row(rf,"Obsidian installed (optional)",3,
            "Download",lambda: webbrowser.open(OBSIDIAN_DOWNLOAD),optional=True)
        lf = tk.Frame(self,bg=BG)
        lf.pack(fill="x",padx=20,pady=(8,0))
        self._log = tk.Text(lf,height=5,bg=BG3,fg=FG_DIM,
            font=("Consolas",9),relief="flat",state="disabled",wrap="word")
        sb = ttk.Scrollbar(lf,command=self._log.yview)
        self._log.configure(yscrollcommand=sb.set)
        sb.pack(side="right",fill="y")
        self._log.pack(fill="x")
        bf = tk.Frame(self,bg=BG,pady=14)
        bf.pack(fill="x",padx=20)
        self._retry_btn = tk.Button(bf,text="Re-check",bg=BG3,fg=FG,
            font=FONT_SM,relief="flat",padx=12,pady=5,cursor="hand2",
            command=self._recheck)
        self._retry_btn.pack(side="left")
        self._continue_btn = tk.Button(bf,text="Continue ->",
            bg=ACCENT,fg="#111111",font=FONT_B,relief="flat",
            padx=14,pady=5,cursor="hand2",
            command=self._do_continue,state="disabled")
        self._continue_btn.pack(side="right")
        tk.Button(bf,text="Quit",bg=BG3,fg=FG_DIM,font=FONT_SM,
            relief="flat",padx=12,pady=5,cursor="hand2",
            command=self._on_close).pack(side="right",padx=(0,8))

    def _make_row(self,parent,label,row,action_text,action_cmd,optional=False):
        f = tk.Frame(parent,bg=BG2)
        f.grid(row=row,column=0,sticky="ew",pady=3)
        parent.columnconfigure(0,weight=1)
        icon = tk.Label(f,text="[!]",fg=RED,bg=BG2,font=FONT_B,width=4)
        icon.pack(side="left")
        tk.Label(f,text=label,bg=BG2,
                 fg=FG_DIM if optional else FG,
                 font=("Segoe UI",9,"italic") if optional else FONT_SM
                 ).pack(side="left",padx=(4,0))
        btn = tk.Button(f,text=action_text,bg=BG3,fg=FG,
            font=("Segoe UI",8),relief="flat",padx=8,pady=2,
            cursor="hand2",command=action_cmd)
        btn.pack(side="right")
        return {"icon":icon,"btn":btn,"optional":optional}

    def _refresh(self):
        s = self._status
        def _set(row,ok,hide_btn=False):
            if ok:
                row["icon"].configure(text="[OK]",fg=GREEN)
                row["btn"].configure(state="disabled",fg=FG_DIM)
            else:
                row["icon"].configure(text="[!]",
                    fg=ORANGE if row["optional"] else RED)
                if not hide_btn:
                    row["btn"].configure(state="normal",fg=FG)
        _set(self._row_oi, s.ollama_installed)
        _set(self._row_or, s.ollama_running, hide_btn=not s.ollama_installed)
        _set(self._row_m,  s.has_model(),    hide_btn=not s.ollama_running)
        _set(self._row_ob, s.obsidian_installed)
        can = s.can_proceed()
        self._continue_btn.configure(
            state="normal" if can else "disabled",
            bg=ACCENT if can else BG3,
            fg="#111111" if can else FG_DIM)

    def _log_write(self,text):
        def _do():
            self._log.configure(state="normal")
            self._log.insert("end",text+"\n")
            self._log.see("end")
            self._log.configure(state="disabled")
        self.after(0,_do)

    def _recheck(self):
        self._status = check_dependencies(); self._refresh()

    def _start_server(self):
        self._log_write("Starting Ollama server...")
        self._retry_btn.configure(state="disabled")
        def _run():
            if _start_ollama_server():
                self._log_write("Ollama started.")
                self._status.ollama_running = True
                self._status.models = _ollama_list_models()
            else:
                self._log_write("Failed. Run:  ollama serve")
            self.after(0,self._refresh)
            self.after(0,lambda: self._retry_btn.configure(state="normal"))
        threading.Thread(target=_run,daemon=True).start()

    def _pull_default_model(self):
        if self._pulling: return
        self._pulling = True
        self._log_write("Pulling "+DEFAULT_MODEL+" ...")
        self._row_m["btn"].configure(state="disabled")
        def _run():
            if _pull_model(DEFAULT_MODEL,self._log_write):
                self._log_write(DEFAULT_MODEL+" ready.")
                self._status.models = _ollama_list_models()
            else:
                self._log_write("Failed. Try:  ollama pull "+DEFAULT_MODEL)
            self._pulling = False
            self.after(0,self._refresh)
        threading.Thread(target=_run,daemon=True).start()

    def _do_continue(self):
        self.grab_release(); self.destroy(); self._on_continue()

    def _on_close(self):
        self.grab_release(); self.destroy(); sys.exit(0)

def run_dependency_check(root,on_ready):
    s = check_dependencies()
    if s.can_proceed() and s.has_model():
        on_ready(); return
    root.withdraw()
    DependencyDialog(root,s,on_ready)