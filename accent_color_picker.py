"""
accent_color_picker.py
Dynamic accent colour picker for Vault AI GUI.
Supports solid colours (via HSV colour wheel) and 2-colour gradients.
Drop-in module - import and call attach_accent_picker(gui_instance).

No external dependencies beyond stdlib (tkinter, math, colorsys, json).

Persistence: saves chosen colours to accent_config.json next to this file.
The saved scheme is restored automatically on next launch.
"""

import tkinter as tk
from tkinter import ttk
import math
import colorsys
import json
import os


# ===========================================================================
#  PERSISTENCE
# ===========================================================================

_HERE        = os.path.dirname(os.path.abspath(__file__))
_CONFIG_FILE = os.path.join(_HERE, "accent_config.json")

_CONFIG_DEFAULTS = {
    "c1":       "#e8c547",
    "c2":       None,
    "gradient": False,
}


def _load_config() -> dict:
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        c1       = data.get("c1",       _CONFIG_DEFAULTS["c1"])
        c2       = data.get("c2",       _CONFIG_DEFAULTS["c2"])
        gradient = bool(data.get("gradient", _CONFIG_DEFAULTS["gradient"]))
        hex_to_rgb(c1)
        if c2 is not None:
            hex_to_rgb(c2)
        return {"c1": c1, "c2": c2, "gradient": gradient}
    except Exception:
        return dict(_CONFIG_DEFAULTS)


def _save_config(c1: str, c2, gradient: bool) -> None:
    try:
        with open(_CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump({"c1": c1, "c2": c2, "gradient": gradient},
                      fh, indent=2)
    except Exception:
        pass


# ===========================================================================
#  COLOUR UTILITIES
# ===========================================================================

def hex_to_rgb(hex_color):
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Bad hex colour: {hex_color!r}")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(r, g, b):
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, int(r))),
        max(0, min(255, int(g))),
        max(0, min(255, int(b))),
    )


def rgb_to_hsv(r, g, b):
    return colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)


def hsv_to_rgb(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = hex_to_rgb(c1)
    r2, g2, b2 = hex_to_rgb(c2)
    return rgb_to_hex(
        r1 + (r2 - r1) * t,
        g1 + (g2 - g1) * t,
        b1 + (b2 - b1) * t,
    )


def is_dark(hex_color):
    try:
        r, g, b = hex_to_rgb(hex_color)
        return (0.299 * r + 0.587 * g + 0.114 * b) < 140
    except Exception:
        return True


def fg_for(hex_color):
    return "#111111" if not is_dark(hex_color) else "#eeeeee"


def colors_close(c1, c2, tol=35):
    try:
        r1, g1, b1 = hex_to_rgb(c1)
        r2, g2, b2 = hex_to_rgb(c2)
        return (abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)) < tol
    except Exception:
        return False


# ===========================================================================
#  PRESETS
# ===========================================================================

PRESETS = [
    ("Gold",     "#e8c547", None),
    ("Sky",      "#4fc3f7", None),
    ("Coral",    "#ff6b6b", None),
    ("Mint",     "#66bb6a", None),
    ("Lavender", "#b39ddb", None),
    ("Amber",    "#ffa726", None),
    ("Rose",     "#ec407a", None),
    ("Cyan",     "#26c6da", None),
    ("Sunset",   "#ff6b35", "#ffcc02"),
    ("Ocean",    "#0077b6", "#00b4d8"),
    ("Aurora",   "#43e97b", "#38f9d7"),
    ("Dusk",     "#f093fb", "#f5576c"),
    ("Neon",     "#39ff14", "#00eeff"),
    ("Lava",     "#ff4500", "#ff8c00"),
    ("Galaxy",   "#7b2ff7", "#f107a3"),
    ("Ice",      "#74ebd5", "#acb6e5"),
]

DEFAULT_C1 = "#e8c547"
DEFAULT_C2 = None


# ===========================================================================
#  COLOUR WHEEL
# ===========================================================================

class ColorWheel(tk.Canvas):
    """
    Interactive HSV colour wheel.

    Coordinate conventions used throughout
    ────────────────────────────────────────
    HSV hue = 0.0  → red, increases clockwise (standard for colorsys).

    Tkinter canvas Y axis points DOWN, so clockwise in screen space means
    increasing angle in math.atan2 (which also increases clockwise when Y
    is flipped).

    tk.create_arc(start=…) uses DEGREES, measured counter-clockwise from
    the 3-o'clock position.  To map hue → tk angle:

        tk_angle_deg = -(hue * 360)     # negate to flip CCW→CW
                                         # no offset: hue 0 = 3 o'clock = red

    But we want red (hue 0) at the top (12 o'clock), which is 90° in tk:

        tk_angle_deg = 90 - hue * 360

    The marker uses math.atan2, where:
        angle = 0       → 3 o'clock
        angle = π/2     → 6 o'clock  (Y is down)
    To place the marker at the same position as the arc start:

        screen_angle = -hue * 2π + π/2     →  12 o'clock when hue=0
        mx = cx + r * cos(screen_angle)
        my = cy - r * sin(screen_angle)    ← subtract because Y is down

    The SV square drag maps:
        x increasing → saturation increasing   (left = grey, right = vivid)
        y increasing → value decreasing        (top = bright, bottom = dark)
    """

    SIZE   = 180
    RING_W = 22
    STEPS  = 60       # more steps → smoother ring
    SQ_RES = 24

    def __init__(self, parent, on_change, **kw):
        super().__init__(
            parent,
            width=self.SIZE, height=self.SIZE,
            bg="#111111", highlightthickness=0,
            **kw,
        )
        self._on_change = on_change
        # Initialise to gold
        h, s, v    = rgb_to_hsv(*hex_to_rgb(DEFAULT_C1))
        self._hue  = h
        self._sat  = s
        self._val  = v
        self._drag = None   # "ring" | "square"

        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<B1-Motion>",       self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.after(10, self._render_all)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _cx(self):      return self.SIZE // 2
    def _cy(self):      return self.SIZE // 2
    def _r_out(self):   return self._cx() - 3
    def _r_in(self):    return self._r_out() - self.RING_W
    def _sq_half(self): return self._r_in() - 6

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_all(self):
        self.delete("all")
        self._render_hue_ring()
        self._render_sv_square()
        self._render_markers()

    def _render_hue_ring(self):
        """
        Draw STEPS arc wedges.

        For hue h, the tk arc starts at:
            start_deg = 90 - h * 360          (12 o'clock = hue 0 = red)
        and sweeps clockwise (negative extent in tk convention):
            extent    = -(360 / STEPS)

        We add a tiny 0.5° overlap on each wedge to close gaps caused by
        floating-point rounding.
        """
        cx, cy  = self._cx(), self._cy()
        r_out   = self._r_out()
        r_in    = self._r_in()
        step    = 360.0 / self.STEPS
        extent  = -(step + 0.5)             # negative = clockwise in tk

        for i in range(self.STEPS):
            hue         = i / self.STEPS
            start_deg   = 90.0 - hue * 360.0   # 12-o'clock origin, CW
            r, g, b     = hsv_to_rgb(hue, 1.0, 1.0)
            color       = rgb_to_hex(r, g, b)
            self.create_arc(
                cx - r_out, cy - r_out,
                cx + r_out, cy + r_out,
                start=start_deg,
                extent=extent,
                fill=color,
                outline=color,
                tags="ring",
            )

        # Punch out inner circle to make the ring hollow
        self.create_oval(
            cx - r_in, cy - r_in,
            cx + r_in, cy + r_in,
            fill="#111111", outline="#111111",
            tags="ring_hole",
        )

    def _render_sv_square(self):
        """
        Fill the inner square with a sat/val grid for the current hue.
        Top-left  = (sat=0, val=1) = white
        Top-right  = (sat=1, val=1) = pure hue colour
        Bottom-left  = (sat=0, val=0) = black
        Bottom-right = (sat=1, val=0) = black
        """
        cx, cy  = self._cx(), self._cy()
        half    = self._sq_half()
        x0, y0  = cx - half, cy - half
        side    = half * 2
        cell    = side / self.SQ_RES

        self.delete("sv_sq")
        for row in range(self.SQ_RES):
            v = 1.0 - row / (self.SQ_RES - 1)      # top → bottom: bright → dark
            for col in range(self.SQ_RES):
                s     = col / (self.SQ_RES - 1)     # left → right: grey → vivid
                r, g, b = hsv_to_rgb(self._hue, s, v)
                color   = rgb_to_hex(r, g, b)
                rx0 = x0 + col * cell
                ry0 = y0 + row * cell
                self.create_rectangle(
                    rx0,        ry0,
                    rx0 + cell + 1,
                    ry0 + cell + 1,
                    fill=color, outline="",
                    tags="sv_sq",
                )

    def _render_markers(self):
        """
        Place two crosshair markers:
          1. On the ring at the current hue angle.
          2. Inside the square at the current sat/val position.

        Ring marker screen position:
            The ring arc for hue h starts at tk angle (90 - h*360)°.
            The midpoint of that arc in screen coordinates:
                screen_rad = hue * 2π          (clockwise from 3 o'clock)
            But we want 12 o'clock = hue 0, so shift by +π/2:
                screen_rad = hue * 2π - π/2    ... wait, let's derive it:

            tk start_deg = 90 - hue*360
            In standard math (CCW from 3 o'clock):
                math_deg = start_deg           (tk CCW = math CCW, same)
            In screen coords (Y down, CW):
                We use cos/sin directly:
                  mx = cx + r * cos(math.radians(start_deg))
                  my = cy - r * sin(math.radians(start_deg))
                       ↑ minus because screen Y is inverted vs math Y

            Simplified:
                angle_rad = math.radians(90 - hue * 360)
                mx = cx + r_mid * cos(angle_rad)
                my = cy - r_mid * sin(angle_rad)
        """
        self.delete("marker")
        cx, cy = self._cx(), self._cy()
        r_mid  = (self._r_out() + self._r_in()) / 2.0

        # ── Hue ring marker ────────────────────────────────────────────
        angle_rad = math.radians(90.0 - self._hue * 360.0)
        mx = cx + r_mid * math.cos(angle_rad)
        my = cy - r_mid * math.sin(angle_rad)   # minus: Y axis is flipped
        self._draw_crosshair(mx, my, 8)

        # ── SV square marker ───────────────────────────────────────────
        half = self._sq_half()
        x0   = cx - half
        y0   = cy - half
        side = half * 2
        sx   = x0 + self._sat * side                   # sat: left→right
        sy   = y0 + (1.0 - self._val) * side           # val: top=bright
        self._draw_crosshair(sx, sy, 6)

    def _draw_crosshair(self, x, y, r):
        self.create_oval(
            x - r, y - r, x + r, y + r,
            outline="white", width=2, fill="",
            tags="marker",
        )
        self.create_oval(
            x - r + 2, y - r + 2,
            x + r - 2, y + r - 2,
            outline="#444444", width=1, fill="",
            tags="marker",
        )

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _on_press(self, e):
        cx, cy = self._cx(), self._cy()
        dist   = math.hypot(e.x - cx, e.y - cy)
        r_out  = self._r_out()
        r_in   = self._r_in()
        half   = self._sq_half()

        if r_in - 4 <= dist <= r_out + 4:
            self._drag = "ring"
        elif abs(e.x - cx) <= half + 4 and abs(e.y - cy) <= half + 4:
            self._drag = "square"
        else:
            self._drag = None
        self._handle_drag(e)

    def _on_motion(self, e):
        self._handle_drag(e)

    def _on_release(self, _e):
        self._drag = None

    def _handle_drag(self, e):
        if self._drag is None:
            return
        cx, cy = self._cx(), self._cy()

        if self._drag == "ring":
            # atan2 gives angle CCW from 3 o'clock in standard math,
            # but screen Y is inverted, so atan2(dy, dx) where dy = e.y - cy
            # actually gives CW angle from 3 o'clock.
            # We want hue 0 at 12 o'clock (90° from 3 o'clock CW),
            # so subtract π/2 and negate to go CW→hue-increasing:
            #
            #   raw_rad = atan2(e.y - cy, e.x - cx)
            #             [0 = 3 o'clock, increases CW because Y is down]
            #   We want hue increasing CW from 12 o'clock:
            #   hue = (-(raw_rad - π/2)) / (2π)  mod 1
            #       = (π/2 - raw_rad) / (2π)      mod 1
            raw_rad   = math.atan2(e.y - cy, e.x - cx)
            self._hue = ((math.pi / 2 - raw_rad) / (2 * math.pi)) % 1.0
            self._render_sv_square()
            self._render_markers()
            self._fire()

        elif self._drag == "square":
            half      = self._sq_half()
            x0, y0    = cx - half, cy - half
            side      = half * 2
            self._sat = max(0.0, min(1.0, (e.x - x0) / side))
            self._val = max(0.0, min(1.0, 1.0 - (e.y - y0) / side))
            self._render_markers()
            self._fire()

    def _fire(self):
        r, g, b = hsv_to_rgb(self._hue, self._sat, self._val)
        self._on_change(rgb_to_hex(r, g, b))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_color(self, hex_color):
        """Snap the wheel to the given hex colour."""
        try:
            r, g, b    = hex_to_rgb(hex_color)
            h, s, v    = rgb_to_hsv(r, g, b)
            self._hue  = h
            self._sat  = s
            self._val  = v
            self._render_sv_square()
            self._render_markers()
        except Exception:
            pass

    def get_color(self):
        r, g, b = hsv_to_rgb(self._hue, self._sat, self._val)
        return rgb_to_hex(r, g, b)


# ===========================================================================
#  ACCENT PICKER DIALOG
# ===========================================================================

_DIALOG_BG   = "#111111"
_DIALOG_BG2  = "#1a1a1a"
_DIALOG_BG3  = "#222222"
_DIALOG_FG   = "#e0e0e0"
_DIALOG_DIM  = "#666666"
_DIALOG_GOLD = "#e8c547"


class AccentPickerDialog(tk.Toplevel):

    def __init__(self, parent, current_c1, current_c2, on_apply):
        super().__init__(parent)
        self.title("Accent Colour")
        self.resizable(False, False)
        self.configure(bg=_DIALOG_BG)
        self.grab_set()

        self._on_apply         = on_apply
        self._c1               = current_c1
        self._c2               = current_c2
        self._gradient_mode    = (current_c2 is not None)
        self._active_slot      = 1
        self._tip_window       = None
        self._hex_trace_paused = False

        self._build()
        self._refresh_all()

        self.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        w  = self.winfo_reqwidth()
        h  = self.winfo_reqheight()
        self.geometry(f"+{px + (pw - w)//2}+{py + (ph - h)//2}")

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build(self):
        B    = _DIALOG_BG
        B2   = _DIALOG_BG2
        B3   = _DIALOG_BG3
        FG   = _DIALOG_FG
        DIM  = _DIALOG_DIM
        GOLD = _DIALOG_GOLD

        # Header
        hdr = tk.Frame(self, bg=B, pady=8, padx=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Accent Colour",
                 font=("Consolas", 13, "bold"),
                 bg=B, fg=GOLD).pack(side="left")

        # Preset grid
        pre_outer = tk.Frame(self, bg=B, padx=12, pady=4)
        pre_outer.pack(fill="x")
        tk.Label(pre_outer, text="Presets",
                 font=("Segoe UI", 8, "bold"),
                 bg=B, fg=DIM).pack(anchor="w")

        pre_grid = tk.Frame(pre_outer, bg=B)
        pre_grid.pack(fill="x", pady=(2, 0))
        COLS = 8
        for i, (label, c1, c2) in enumerate(PRESETS):
            r, col = divmod(i, COLS)
            cell   = tk.Frame(pre_grid, bg=B)
            cell.grid(row=r, column=col, padx=3, pady=2)
            self._make_preset_swatch(cell, label, c1, c2)

        # Gradient toggle
        mode_f = tk.Frame(self, bg=B, padx=12, pady=6)
        mode_f.pack(fill="x")
        self._grad_var = tk.BooleanVar(value=self._gradient_mode)
        tk.Checkbutton(
            mode_f,
            text="Gradient (2 colours)",
            variable=self._grad_var,
            command=self._toggle_gradient,
            bg=B, fg=FG,
            selectcolor=B3,
            activebackground=B,
            activeforeground=GOLD,
            font=("Segoe UI", 9),
        ).pack(side="left")

        # Colour slots
        slots_f = tk.Frame(self, bg=B, padx=12)
        slots_f.pack(fill="x")
        self._slot_frames   = {}
        self._slot_swatches = {}
        self._hex_vars      = {}

        for slot in (1, 2):
            sf = tk.Frame(
                slots_f, bg=B2,
                padx=8, pady=6,
                highlightthickness=2,
                highlightbackground="#333333",
            )
            sf.pack(
                side="left", expand=True, fill="both",
                padx=(0, 0) if slot == 1 else (8, 0),
            )
            self._slot_frames[slot] = sf

            tk.Label(
                sf,
                text="Colour 1 (main)" if slot == 1 else "Colour 2 (end)",
                font=("Segoe UI", 8, "bold"),
                bg=B2, fg=DIM,
            ).pack(anchor="w")

            swatch = tk.Label(sf, text="", height=2, relief="flat")
            swatch.pack(fill="x", pady=(2, 4))
            self._slot_swatches[slot] = swatch

            hex_var = tk.StringVar()
            self._hex_vars[slot] = hex_var
            ttk.Entry(sf, textvariable=hex_var,
                      width=9, font=("Consolas", 9)).pack(side="left")
            hex_var.trace_add(
                "write",
                lambda *_a, s=slot: self._on_hex_entry(s),
            )

            edit_btn = tk.Label(
                sf, text="Edit",
                font=("Segoe UI", 8),
                bg="#333333", fg=FG,
                padx=6, pady=2,
                cursor="hand2",
            )
            edit_btn.pack(side="left", padx=(6, 0))
            edit_btn.bind(
                "<Button-1>",
                lambda _e, s=slot: self._activate_slot(s),
            )

        # Colour wheel
        wheel_f = tk.Frame(self, bg=B, padx=12, pady=8)
        wheel_f.pack()
        tk.Label(
            wheel_f,
            text="Drag ring = Hue   Drag square = Sat / Bright",
            font=("Segoe UI", 8),
            bg=B, fg=DIM,
        ).pack()
        self._wheel = ColorWheel(wheel_f, on_change=self._wheel_changed)
        self._wheel.pack(pady=(4, 0))

        # Preview strip
        prev_f = tk.Frame(self, bg=B, padx=12, pady=6)
        prev_f.pack(fill="x")
        tk.Label(prev_f, text="Preview",
                 font=("Segoe UI", 8, "bold"),
                 bg=B, fg=DIM).pack(anchor="w")
        self._preview_canvas = tk.Canvas(
            prev_f, height=40, bg=B2,
            highlightthickness=0,
        )
        self._preview_canvas.pack(fill="x", pady=(2, 0))
        self._preview_canvas.bind(
            "<Configure>", lambda _e: self._draw_preview())

        # Action buttons
        btn_f = tk.Frame(self, bg=B, padx=12, pady=10)
        btn_f.pack(fill="x")

        tk.Button(
            btn_f, text="Reset to Default",
            bg=B3, fg=DIM,
            font=("Segoe UI", 9),
            relief="flat", padx=10, pady=5,
            cursor="hand2",
            command=self._reset,
        ).pack(side="left")

        tk.Button(
            btn_f, text="Cancel",
            bg="#333333", fg=FG,
            font=("Segoe UI", 10),
            relief="flat", padx=14, pady=5,
            cursor="hand2",
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            btn_f, text="Apply",
            bg=GOLD, fg="#111111",
            font=("Segoe UI", 10, "bold"),
            relief="flat", padx=14, pady=5,
            cursor="hand2",
            command=self._apply,
        ).pack(side="right")

    # ------------------------------------------------------------------
    # Preset swatches
    # ------------------------------------------------------------------

    def _make_preset_swatch(self, parent, label, c1, c2):
        SIZE = 26
        cnv  = tk.Canvas(
            parent, width=SIZE, height=SIZE,
            highlightthickness=1,
            highlightbackground="#333333",
            cursor="hand2",
            bg=_DIALOG_BG,
        )
        cnv.pack()

        if c2 is not None:
            for i in range(SIZE):
                col = lerp_color(c1, c2, i / SIZE)
                cnv.create_line(i, 0, i, SIZE, fill=col)
        else:
            cnv.create_rectangle(0, 0, SIZE, SIZE,
                                  fill=c1, outline="")

        cnv.bind("<Button-1>",
                 lambda _e, a=c1, b=c2: self._apply_preset(a, b))
        cnv.bind("<Enter>",
                 lambda _e, lbl=label, w=cnv: self._show_tip(w, lbl))
        cnv.bind("<Leave>", lambda _e: self._hide_tip())

        tk.Label(parent, text=label[:5],
                 font=("Segoe UI", 6),
                 bg=_DIALOG_BG, fg=_DIALOG_DIM).pack()

    def _show_tip(self, widget, text):
        self._hide_tip()
        self._tip_window = tk.Toplevel(self)
        self._tip_window.wm_overrideredirect(True)
        x = widget.winfo_rootx() + 14
        y = widget.winfo_rooty() - 24
        self._tip_window.geometry(f"+{x}+{y}")
        tk.Label(self._tip_window, text=text,
                 bg="#333333", fg="#ffffff",
                 font=("Segoe UI", 8),
                 padx=4, pady=2).pack()

    def _hide_tip(self):
        if self._tip_window is not None:
            try:
                self._tip_window.destroy()
            except Exception:
                pass
            self._tip_window = None

    # ------------------------------------------------------------------
    # Slot / wheel interaction
    # ------------------------------------------------------------------

    def _activate_slot(self, slot):
        self._active_slot = slot
        for s, sf in self._slot_frames.items():
            sf.configure(
                highlightbackground=(
                    _DIALOG_GOLD if s == slot else "#333333"
                )
            )
        color = self._c1 if slot == 1 else (self._c2 or self._c1)
        self._wheel.set_color(color)

    def _wheel_changed(self, hex_color):
        if self._active_slot == 1:
            self._c1 = hex_color
        else:
            self._c2 = hex_color
        self._hex_trace_paused = True
        self._hex_vars[1].set(self._c1)
        self._hex_vars[2].set(self._c2 or self._c1)
        self._hex_trace_paused = False
        self._update_slot_swatches()
        self._draw_preview()

    def _on_hex_entry(self, slot):
        if self._hex_trace_paused:
            return
        try:
            raw = self._hex_vars[slot].get().strip()
            if not raw.startswith("#"):
                raw = "#" + raw
            if len(raw) != 7:
                return
            hex_to_rgb(raw)
            if slot == 1:
                self._c1 = raw
            else:
                self._c2 = raw
            self._update_slot_swatches()
            self._draw_preview()
            if self._active_slot == slot:
                self._wheel.set_color(raw)
        except (ValueError, Exception):
            pass

    def _apply_preset(self, c1, c2):
        self._c1            = c1
        self._c2            = c2
        self._gradient_mode = (c2 is not None)
        self._grad_var.set(self._gradient_mode)
        self._refresh_all()
        self._wheel.set_color(c1)

    def _toggle_gradient(self):
        self._gradient_mode = self._grad_var.get()
        if self._gradient_mode and self._c2 is None:
            self._c2 = lerp_color(self._c1, "#ffffff", 0.4)
        self._refresh_all()

    def _reset(self):
        self._apply_preset(DEFAULT_C1, DEFAULT_C2)

    def _apply(self):
        c2 = self._c2 if self._gradient_mode else None
        self._on_apply(self._c1, c2)
        self.destroy()

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _refresh_all(self):
        self._activate_slot(self._active_slot)
        self._update_slot_swatches()
        self._update_slot2_state()
        self._draw_preview()

    def _update_slot_swatches(self):
        c1 = self._c1
        c2 = self._c2 or self._c1
        self._slot_swatches[1].configure(bg=c1, fg=fg_for(c1), text=c1)
        self._slot_swatches[2].configure(bg=c2, fg=fg_for(c2), text=c2)
        self._hex_trace_paused = True
        self._hex_vars[1].set(c1)
        self._hex_vars[2].set(c2)
        self._hex_trace_paused = False

    def _update_slot2_state(self):
        enabled = self._gradient_mode
        for child in self._slot_frames[2].winfo_children():
            try:
                child.configure(
                    state="normal" if enabled else "disabled"
                )
            except Exception:
                pass

    def _draw_preview(self):
        c  = self._preview_canvas
        c.delete("all")
        w  = c.winfo_width()
        h  = c.winfo_height()
        if w < 2:
            return

        c2     = self._c2 if self._gradient_mode else None
        half_h = h // 2

        for i in range(w):
            col = lerp_color(
                self._c1, c2 or self._c1,
                i / max(w - 1, 1),
            )
            c.create_line(i, 0, i, half_h, fill=col)

        mid = lerp_color(self._c1, c2 or self._c1, 0.5)
        bx0, by0 = w // 4,     half_h + 3
        bx1, by1 = 3 * w // 4, h - 3
        c.create_rectangle(bx0, by0, bx1, by1, fill=mid, outline="")
        c.create_text(
            (bx0 + bx1) // 2, (by0 + by1) // 2,
            text="Sample Button",
            fill=fg_for(mid),
            font=("Segoe UI", 8, "bold"),
        )

    def destroy(self):
        self._hide_tip()
        super().destroy()


# ===========================================================================
#  ACCENT MANAGER
# ===========================================================================

class AccentManager:

    def __init__(self):
        cfg            = _load_config()
        self._c1       = cfg["c1"]
        self._c2       = cfg["c2"]
        self._gradient = cfg["gradient"]
        if not self._gradient:
            self._c2 = None

        self._gui        = None
        self._root       = None
        self._picker_btn = None
        self._known      = {self._c1, DEFAULT_C1}
        if self._c2:
            self._known.add(self._c2)

    def attach(self, gui):
        self._gui  = gui
        self._root = gui.root
        self._inject_picker_button()
        self._apply_to_gui()

    def open_picker(self):
        if self._root is None:
            return
        AccentPickerDialog(
            self._root,
            self._c1,
            self._c2,
            self._on_apply,
        )

    def _on_apply(self, c1, c2):
        self._c1       = c1
        self._c2       = c2
        self._gradient = (c2 is not None)
        _save_config(c1, c2, self._gradient)
        self._apply_to_gui()

    def _apply_to_gui(self):
        gui  = self._gui
        root = self._root
        c1, c2 = self._c1, self._c2
        mid   = lerp_color(c1, c2, 0.5) if c2 else c1
        hover = lerp_color(mid, "#ffffff", 0.18)
        fg    = fg_for(mid)

        s = ttk.Style()
        s.configure("Accent.TButton", background=mid, foreground=fg)
        s.map("Accent.TButton",
              background=[("active",  hover), ("pressed", hover)],
              foreground=[("active",  fg),    ("pressed", fg)])
        s.map("TButton",
              background=[("active",  mid), ("pressed", mid)],
              foreground=[("active",  fg),  ("pressed", fg)])
        s.map("TNotebook.Tab",
              foreground=[("selected", mid)])

        self._walk_recolour(root, mid, fg)

        for attr in ("chat_out", "log_view", "doc_preview"):
            w = getattr(gui, attr, None)
            if w is not None:
                try:
                    w.tag_configure("accent",  foreground=mid)
                    w.tag_configure("heading", foreground=mid)
                except Exception:
                    pass

        lb = getattr(gui, "docs_listbox", None)
        if lb is not None:
            try:
                lb.configure(selectbackground=mid, selectforeground=fg)
            except Exception:
                pass

        if self._picker_btn is not None:
            try:
                self._picker_btn.configure(
                    bg=mid, fg=fg,
                    activebackground=mid,
                    activeforeground=fg,
                )
            except Exception:
                pass

        self._known.add(c1)
        self._known.add(mid)
        if c2:
            self._known.add(c2)

    def _walk_recolour(self, widget, new_mid, new_fg):
        for child in widget.winfo_children():
            try:
                if isinstance(child, tk.Label):
                    if self._is_known_accent(child.cget("fg")):
                        child.configure(fg=new_mid)
                elif isinstance(child, tk.Button):
                    if self._is_known_accent(child.cget("bg")):
                        child.configure(
                            bg=new_mid, fg=new_fg,
                            activebackground=new_mid,
                            activeforeground=new_fg,
                        )
            except Exception:
                pass
            self._walk_recolour(child, new_mid, new_fg)

    def _is_known_accent(self, color_str):
        if not color_str:
            return False
        for known in self._known:
            if color_str.lower() == known.lower():
                return True
            try:
                if colors_close(color_str, known, tol=35):
                    return True
            except Exception:
                pass
        return False

    def _inject_picker_button(self):
        gui    = self._gui
        root   = self._root
        header = getattr(gui, "header_frame", None)

        if header is None:
            for child in root.winfo_children():
                if isinstance(child, tk.Frame):
                    header = child
                    break
        if header is None:
            header = root

        mid = lerp_color(self._c1, self._c2, 0.5) if self._c2 else self._c1
        f   = fg_for(mid)

        self._picker_btn = tk.Button(
            header,
            text="\U0001f3a8 Accent",
            bg=mid, fg=f,
            activebackground=mid,
            activeforeground=f,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=10, pady=3,
            cursor="hand2",
            command=self.open_picker,
        )
        self._picker_btn.pack(side="right", padx=(0, 8), pady=4)


# ===========================================================================
#  PUBLIC API
# ===========================================================================

_manager = AccentManager()


def attach_accent_picker(gui_instance):
    _manager.attach(gui_instance)