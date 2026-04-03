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