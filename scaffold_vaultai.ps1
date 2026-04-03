Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = Join-Path (Get-Location) "VaultAI"

function WF([string]$Path, [string]$Content) {
    $dir = Split-Path $Path -Parent
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, $Content,
        [System.Text.UTF8Encoding]::new($false))
    Write-Host "  created  $Path" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "Scaffolding VaultAI at: $root" -ForegroundColor Cyan
Write-Host ""
WF "$root\vaultai\__init__.py" @"
"""
VaultAI -- Obsidian-aware RAG assistant.
"""
__version__ = "1.0.0"
__author__  = "ASUS"
"@
WF "$root\vaultai\__main__.py" @"
"""
vaultai/__main__.py
Entry point for python -m vaultai and the vaultai console command.
"""
import sys, os

def main():
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    if pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)
    try:
        import tkinter as tk
    except ImportError:
        print("ERROR: tkinter not available.", file=sys.stderr)
        sys.exit(1)
    root = tk.Tk()
    root.withdraw()
    root.title("VaultAI")
    try:
        icon = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "resources", "icon.ico")
        if os.path.exists(icon):
            root.iconbitmap(icon)
    except Exception:
        pass
    from vaultai.dep_check import run_dependency_check
    def _launch_gui():
        root.deiconify()
        from vaultai.gui import VaultGUI
        VaultGUI(root)
        root.mainloop()
    run_dependency_check(root, _launch_gui)
    try:
        root.mainloop()
    except Exception:
        pass

if __name__ == "__main__":
    main()
"@
WF "$root\vaultai\dep_check.py" @"
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
"@
WF "$root\vaultai\accent_color_picker.py" @"
"""
vaultai/accent_color_picker.py
Replace this file with your working accent_color_picker.py
No edits to that file are needed.
Only change this import in gui.py:
    from vaultai.accent_color_picker import attach_accent_picker
"""
raise NotImplementedError("Replace with your accent_color_picker.py")
"@
WF "$root\vaultai\gui.py" @"
"""
vaultai/gui.py
Paste your vault_ai_gui_claude.py contents here.
Change only this one import line:
    from vaultai.accent_color_picker import attach_accent_picker
"""
raise NotImplementedError("Replace with your gui.py contents.")
"@
WF "$root\vaultai\resources\.gitkeep" ""
WF "$root\pyproject.toml" @"
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name            = "vaultai"
version         = "1.0.0"
description     = "Obsidian-aware RAG assistant with accent colour theming"
readme          = "README.md"
requires-python = ">=3.10"
license         = { text = "MIT" }

dependencies = [
    "faiss-cpu",
    "sentence-transformers",
    "ollama",
    "PyPDF2",
    "python-pptx",
    "python-docx",
    "PySide6",
    "requests",
]

[project.scripts]
vaultai = "vaultai.__main__:main"

[tool.setuptools.packages.find]
where   = ["."]
include = ["vaultai*"]

[tool.setuptools.package-data]
vaultai = ["resources/*"]
"@
WF "$root\setup.py" @"
from setuptools import setup
setup()
"@
WF "$root\MANIFEST.in" @"
include README.md
include requirements.txt
include LICENSE
recursive-include vaultai/resources *
"@
WF "$root\README.md" @"
# VaultAI

Obsidian-aware RAG assistant.

## External requirements

| App      | Required | Link                        | Purpose             |
|----------|----------|-----------------------------|---------------------|
| Ollama   | Yes      | https://ollama.com/download | Local LLM server    |
| Obsidian | Optional | https://obsidian.md         | Vault note indexing |

After installing Ollama:

    ollama pull llama3

## Quick start

    pip install -e .
    vaultai

## Build installer

    pip install pyinstaller build
    python build_installer.py
"@
WF "$root\requirements.txt" @"
faiss-cpu
sentence-transformers
ollama
PyPDF2
python-pptx
python-docx
PySide6
requests
"@
WF "$root\build_installer.py" @"
"""
build_installer.py  --  run: python build_installer.py
Builds wheel, PyInstaller bundle, NSIS script, and .exe installer.
Requires: pip install pyinstaller build
          NSIS from https://nsis.sourceforge.io  (for the .exe)
"""
import os, sys, shutil, subprocess
from pathlib import Path

ROOT      = Path(__file__).parent.resolve()
APP_NAME  = "VaultAI"
VERSION   = "1.0.0"
ENTRY     = ROOT / "vaultai" / "__main__.py"
DIST_DIR  = ROOT / "dist"
BUILD_DIR = ROOT / "build"
NSI_DIR   = ROOT / "installer"
NSI_FILE  = NSI_DIR / "vaultai_setup.nsi"
ICON_FILE = ROOT / "vaultai" / "resources" / "icon.ico"

def run(cmd):
    print("\n>>> " + " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)

def step_wheel():
    print("\n" + "="*50 + "\nSTEP 1 - wheel\n" + "="*50)
    run([sys.executable, "-m", "build", "--wheel", "--outdir", str(DIST_DIR)])

def step_pyinstaller():
    print("\n" + "="*50 + "\nSTEP 2 - PyInstaller\n" + "="*50)
    cmd = [sys.executable, "-m", "PyInstaller",
           "--noconfirm", "--clean",
           "--name", APP_NAME,
           "--distpath", str(DIST_DIR),
           "--workpath", str(BUILD_DIR),
           "--windowed", "--onedir"]
    if ICON_FILE.exists():
        cmd += ["--icon", str(ICON_FILE)]
    for h in ["faiss","numpy","sentence_transformers","ollama",
              "PyPDF2","pptx","docx","requests","colorsys",
              "tkinter","tkinter.ttk","tkinter.scrolledtext",
              "tkinter.messagebox","tkinter.filedialog",
              "vaultai.dep_check","vaultai.gui",
              "vaultai.accent_color_picker"]:
        cmd += ["--hidden-import", h]
    for pkg in ["sentence_transformers","transformers",
                "tokenizers","huggingface_hub","PySide6"]:
        cmd += ["--collect-all", pkg]
    cmd.append(str(ENTRY))
    run(cmd)

def step_nsi():
    print("\n" + "="*50 + "\nSTEP 3 - NSIS script\n" + "="*50)
    NSI_DIR.mkdir(exist_ok=True)
    bundle  = str(DIST_DIR / APP_NAME)
    out_exe = str(DIST_DIR / (APP_NAME + "_Setup_" + VERSION + ".exe"))
    readme  = bundle + os.sep + ".." + os.sep + ".." + os.sep + "README.md"
    icon_i  = ("Icon \\"" + str(ICON_FILE) + "\\""
               if ICON_FILE.exists() else "; no icon")
    icon_u  = ("UninstallIcon \\"" + str(ICON_FILE) + "\\""
               if ICON_FILE.exists() else "; no icon")
    nsi = [
        "Unicode True",
        "!define APP     \\"" + APP_NAME + "\\"",
        "!define VER     \\"" + VERSION  + "\\"",
        "!define EXEC    \\"" + APP_NAME + ".exe\\"",
        "!define BUNDLE  \\"" + bundle   + "\\"",
        "!define OLLAMA_URL   \\"https://ollama.com/download/OllamaSetup.exe\\"",
        "!define OBSIDIAN_URL \\"https://obsidian.md/download\\"",
        "",
        "Name \\"${APP} ${VER}\\"",
        "OutFile \\"" + out_exe + "\\"",
        "InstallDir \\"$PROGRAMFILES64\\\\${APP}\\"",
        "InstallDirRegKey HKLM \\"Software\\\\${APP}\\" \\"InstallDir\\"",
        "RequestExecutionLevel admin",
        "SetCompressor /SOLID lzma",
        icon_i, icon_u, "",
        "!include \\"MUI2.nsh\\"", "!include \\"LogicLib.nsh\\"",
        "!define MUI_ABORTWARNING",
        "!insertmacro MUI_PAGE_WELCOME",
        "!insertmacro MUI_PAGE_LICENSE \\"" + readme + "\\"",
        "Page custom DepsPage DepsPageLeave",
        "!insertmacro MUI_PAGE_DIRECTORY",
        "!insertmacro MUI_PAGE_INSTFILES",
        "!insertmacro MUI_PAGE_FINISH",
        "!insertmacro MUI_UNPAGE_CONFIRM",
        "!insertmacro MUI_UNPAGE_INSTFILES",
        "!insertmacro MUI_LANGUAGE \\"English\\"",
        "Var OllamaFound", "Var ObsidianFound", "",
        "!macro DetectOllama",
        "  StrCpy $OllamaFound \\"0\\"",
        "  ReadRegStr $0 HKLM \\\\",
        "    \\"Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Uninstall\\\\Ollama\\" \\\\",
        "    \\"DisplayName\\"",
        "  ${If} $0 != \\"\\"",
        "    StrCpy $OllamaFound \\"1\\"",
        "  ${EndIf}",
        "  ${If} $OllamaFound == \\"0\\"",
        "    nsExec::ExecToStack \\"where ollama\\"",
        "    Pop $0", "    Pop $1",
        "    ${If} $0 == \\"0\\"",
        "      StrCpy $OllamaFound \\"1\\"",
        "    ${EndIf}",
        "  ${EndIf}",
        "!macroend", "",
        "!macro DetectObsidian",
        "  StrCpy $ObsidianFound \\"0\\"",
        "  ${If} ${FileExists} \\"$LOCALAPPDATA\\\\Programs\\\\obsidian\\\\Obsidian.exe\\"",
        "    StrCpy $ObsidianFound \\"1\\"",
        "  ${EndIf}",
        "!macroend", "",
        "Function DepsPage",
        "  !insertmacro DetectOllama",
        "  !insertmacro DetectObsidian",
        "  ${If} $OllamaFound == \\"1\\"",
        "  ${AndIf} $ObsidianFound == \\"1\\"",
        "    Abort",
        "  ${EndIf}",
        "  nsDialogs::Create 1018", "  Pop $0",
        "  ${If} $0 == error", "    Abort", "  ${EndIf}",
        "  ${NSD_CreateLabel} 0 0 100% 16u \\"External Dependencies\\"",
        "  Pop $0",
        "  ${NSD_CreateLabel} 0 20u 100% 12u \\"VaultAI works with these apps:\\"",
        "  Pop $0",
        "  ${If} $OllamaFound == \\"1\\"",
        "    ${NSD_CreateLabel} 0 42u 100% 14u \\"[OK] Ollama installed\\"",
        "    Pop $0",
        "  ${Else}",
        "    ${NSD_CreateLabel} 0 42u 72% 14u \\"[!] Ollama NOT found (required)\\"",
        "    Pop $0",
        "    ${NSD_CreateButton} 74% 40u 26% 16u \\"Download Ollama\\"",
        "    Pop $0", "    ${NSD_OnClick} $0 OnOllamaBtn",
        "  ${EndIf}",
        "  ${If} $ObsidianFound == \\"1\\"",
        "    ${NSD_CreateLabel} 0 64u 100% 14u \\"[OK] Obsidian installed\\"",
        "    Pop $0",
        "  ${Else}",
        "    ${NSD_CreateLabel} 0 64u 72% 14u \\"[i] Obsidian not found (optional)\\"",
        "    Pop $0",
        "    ${NSD_CreateButton} 74% 62u 26% 16u \\"Download Obsidian\\"",
        "    Pop $0", "    ${NSD_OnClick} $0 OnObsidianBtn",
        "  ${EndIf}",
        "  ${NSD_CreateLabel} 0 86u 100% 20u \\"You can install these later.\\"",
        "  Pop $0", "  nsDialogs::Show",
        "FunctionEnd", "",
        "Function OnOllamaBtn",
        "  ExecShell \\"open\\" \\"${OLLAMA_URL}\\"",
        "FunctionEnd", "",
        "Function OnObsidianBtn",
        "  ExecShell \\"open\\" \\"${OBSIDIAN_URL}\\"",
        "FunctionEnd", "",
        "Function DepsPageLeave",
        "  ${If} $OllamaFound == \\"0\\"",
        "    MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION \\\\",
        "      \\"Ollama not installed. AI will not work. Continue?\\" \\\\",
        "      IDOK +2",
        "    Abort",
        "  ${EndIf}",
        "FunctionEnd", "",
        "Section \\"Install\\" SEC01",
        "  SetOutPath \\"$INSTDIR\\"",
        "  File /r \\"${BUNDLE}\\\\*.*\\"",
        "  WriteUninstaller \\"$INSTDIR\\\\Uninstall.exe\\"",
        "  WriteRegStr HKLM \\\\",
        "    \\"Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Uninstall\\\\${APP}\\" \\\\",
        "    \\"DisplayName\\" \\"${APP}\\"",
        "  WriteRegStr HKLM \\\\",
        "    \\"Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Uninstall\\\\${APP}\\" \\\\",
        "    \\"UninstallString\\" \\"$INSTDIR\\\\Uninstall.exe\\"",
        "  WriteRegStr HKLM \\\\",
        "    \\"Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Uninstall\\\\${APP}\\" \\\\",
        "    \\"DisplayVersion\\" \\"${VER}\\"",
        "  WriteRegStr HKLM \\\\",
        "    \\"Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Uninstall\\\\${APP}\\" \\\\",
        "    \\"InstallLocation\\" \\"$INSTDIR\\"",
        "  CreateDirectory \\"$SMPROGRAMS\\\\${APP}\\"",
        "  CreateShortcut \\"$SMPROGRAMS\\\\${APP}\\\\${APP}.lnk\\" \\"$INSTDIR\\\\${EXEC}\\"",
        "  CreateShortcut \\"$DESKTOP\\\\${APP}.lnk\\" \\"$INSTDIR\\\\${EXEC}\\"",
        "  WriteRegStr HKLM \\"Software\\\\${APP}\\" \\"InstallDir\\" \\"$INSTDIR\\"",
        "SectionEnd", "",
        "Section \\"Uninstall\\"",
        "  RMDir /r \\"$INSTDIR\\"",
        "  Delete \\"$SMPROGRAMS\\\\${APP}\\\\${APP}.lnk\\"",
        "  RMDir  \\"$SMPROGRAMS\\\\${APP}\\"",
        "  Delete \\"$DESKTOP\\\\${APP}.lnk\\"",
        "  DeleteRegKey HKLM \\\\",
        "    \\"Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Uninstall\\\\${APP}\\"",
        "  DeleteRegKey HKLM \\"Software\\\\${APP}\\"",
        "SectionEnd",
    ]
    NSI_FILE.write_text("\n".join(nsi), encoding="utf-8")
    print("Written: " + str(NSI_FILE))

def step_compile():
    print("\n" + "="*50 + "\nSTEP 4 - compile NSIS\n" + "="*50)
    m = shutil.which("makensis")
    if not m:
        print("  makensis not found.\n  Install NSIS: https://nsis.sourceforge.io\n  Then: makensis " + str(NSI_FILE))
        return
    run([m, str(NSI_FILE)])
    out = DIST_DIR / (APP_NAME + "_Setup_" + VERSION + ".exe")
    if out.exists(): print("\n  Installer: " + str(out))

def main():
    if not ENTRY.exists(): sys.exit("ERROR: " + str(ENTRY) + " not found")
    for pkg in ("build","PyInstaller"):
        try: __import__(pkg.lower().replace("-","_"))
        except ImportError: sys.exit("Run: pip install build pyinstaller")
    step_wheel(); step_pyinstaller(); step_nsi(); step_compile()
    print("\n" + "="*50 + "\nBUILD COMPLETE\n" + "="*50)

if __name__ == "__main__":
    main()
"@
Write-Host ""
Write-Host "All files created:" -ForegroundColor Green
Write-Host ""
function Show-Tree([string]$Path,[string]$Prefix="") {
    $items = Get-ChildItem -LiteralPath $Path |
             Where-Object { $_.Name -notin @("__pycache__",".git") } |
             Sort-Object { -not $_.PSIsContainer },Name
    for ($i=0;$i -lt $items.Count;$i++) {
        $item=$items[$i]; $last=($i -eq $items.Count-1)
        $br=if($last){"+-- "}else{"|-- "}
        $nx=if($last){"    "}else{"|   "}
        if($item.PSIsContainer){
            Write-Host "$Prefix$br$($item.Name)/" -ForegroundColor Cyan
            Show-Tree $item.FullName "$Prefix$nx"
        } else {
            $col=switch($item.Extension){".py"{"Yellow"}".toml"{"Magenta"}".md"{"Green"}".txt"{"White"}default{"Gray"}}
            Write-Host "$Prefix$br$($item.Name)" -ForegroundColor $col
        }
    }
}
Write-Host "VaultAI/" -ForegroundColor Cyan
Show-Tree $root
Write-Host ""
Write-Host ("=" * 55) -ForegroundColor DarkGray
Write-Host " Next steps" -ForegroundColor Cyan
Write-Host ("=" * 55) -ForegroundColor DarkGray
Write-Host " 1. Copy accent_color_picker.py  ->  $root\vaultai\accent_color_picker.py" -ForegroundColor Yellow
Write-Host " 2. Copy vault_ai_gui_claude.py  ->  $root\vaultai\gui.py" -ForegroundColor Yellow
Write-Host "    Change the import line in gui.py to:" -ForegroundColor White
Write-Host "      from vaultai.accent_color_picker import attach_accent_picker" -ForegroundColor Yellow
Write-Host " 3. pip install -e . && vaultai" -ForegroundColor Yellow
Write-Host " 4. pip install pyinstaller build && python build_installer.py" -ForegroundColor Yellow
Write-Host ("=" * 55) -ForegroundColor DarkGray
