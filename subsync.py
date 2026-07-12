r"""
Subsync  --  always-on-top .srt -> keystroke player for synced lyrics.

Plays a song's subtitle timeline into whatever app has keyboard focus, so you
can drive a synced-lyric display (YouTube Music, etc.) in time with the audio.

What it does:
  1. Load an .srt for the song.
  2. Pick a mode:
       - Hold/release space -- holds the spacebar for the duration of each
         lyric line and releases it in the gaps.
       - Type lyrics        -- types each line (paced ~25 ms/char) at its start;
         handy for testing against Notepad.
  3. Set the lead (ms). Keys fire this many ms BEFORE the .srt time to beat
     display lag. Default 500 ms; type a value or nudge in 10 ms steps.
  4. Hit GO. A 3 s count-in ticks down (screen RED) at 0.01 s resolution. At
     zero the screen turns GREEN ("CLICK PLAY NOW") -- click Play on the song.
     That instant is t = 0, and the keystrokes follow the .srt from there.

Keys go to whatever window has keyboard focus, so after you hit GO click into
the song/player window -- the keys land there, not on this app.

Windows only (uses SendInput). Pure stdlib -- runs on your global Python.
    python subsync.py  [optional\path\to.srt]
"""

__version__ = "1.0.0"

import os
import sys
import time
import ctypes
from collections import deque
from ctypes import wintypes
import tkinter as tk
from tkinter import filedialog, font as tkfont

# ---------------------------------------------------------------- key sending
user32 = ctypes.WinDLL("user32", use_last_error=True)
PUL = ctypes.POINTER(ctypes.c_ulong)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", PUL)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", PUL)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _IUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _IUNION)]


# MUST set these on Win64 or ctypes passes a truncated 32-bit pointer and
# SendInput silently fails (returns 0 -> no keys injected at all).
user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
SPACE_SCAN = 0x39   # spacebar scan code -- most compatible with games/players
ENTER_SCAN = 0x1C   # Enter/Return


def _send_scan(scan, down):
    flags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP)
    ki = KEYBDINPUT(0, scan, flags, 0, None)
    inp = INPUT(INPUT_KEYBOARD, _IUNION(ki=ki))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _send_space(down):
    _send_scan(SPACE_SCAN, down)


def _send_char(ch):
    code = ord(ch)
    for up in (0, KEYEVENTF_KEYUP):
        ki = KEYBDINPUT(0, code, KEYEVENTF_UNICODE | up, 0, None)
        inp = INPUT(INPUT_KEYBOARD, _IUNION(ki=ki))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def type_text(text):
    for ch in text:
        _send_char(ch)
    _send_scan(ENTER_SCAN, True)   # newline so each line lands on its own row
    _send_scan(ENTER_SCAN, False)


# ---------------------------------------------------------------- srt parsing
def _to_sec(ts):
    # 00:01:23,456  or  00:01:23.456
    ts = ts.strip().replace(".", ",")
    hms, _, ms = ts.partition(",")
    h, m, s = (hms.split(":") + ["0", "0", "0"])[:3]
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms or 0) / 1000.0


def parse_srt(path):
    """Return list of (start_sec, end_sec, text)."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        raw = f.read()
    subs = []
    block = []
    for line in raw.splitlines() + [""]:
        if line.strip() == "":
            if block:
                subs.append(block)
                block = []
        else:
            block.append(line)
    out = []
    for b in subs:
        timing = next((ln for ln in b if "-->" in ln), None)
        if not timing:
            continue
        start, _, end = timing.partition("-->")
        text = " ".join(ln for ln in b
                         if "-->" not in ln and not ln.strip().isdigit()).strip()
        try:
            out.append((_to_sec(start), _to_sec(end), text))
        except ValueError:
            continue
    out.sort(key=lambda s: s[0])
    return out


def build_events(subs, merge_gap=0.02):
    """Merge touching/overlapping lines, then emit (time, 'down'/'up')."""
    merged = []
    for s, e, _ in subs:
        if merged and s <= merged[-1][1] + merge_gap:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    ev = []
    for s, e in merged:
        ev.append((s, "down"))
        ev.append((e, "up"))
    ev.sort(key=lambda x: (x[0], x[1] == "down"))  # 'up' before 'down' at ties
    return ev


# ---------------------------------------------------------------------- colors
# Shared "family" palette, lifted from Subtap so the two tools look related.
BG = "#12141a"        # window background when idle
PANEL2 = "#232734"    # inputs / dropdown / secondary buttons
PANEL2_HI = "#2c3242"  # same, hover/lit
LINE = "#2c3040"      # hairline separators / borders
TXT = "#e6e8ee"       # primary text
DIM = "#9aa0b0"       # muted labels
ACCENT = "#4fd1ff"    # cyan  -- primary action (GO)
ACCENT_HI = "#8adcff"  # cyan, hover
ACCENT_TX = "#06131a"  # dark ink for text on a cyan fill
DANGER = "#ff6b6b"    # red   -- stop / warnings

# Run states drive the rounded "state" outline (not a full-window flood, which
# fought the theme). Re-hued to sit inside the cool dark palette: a rose for
# "wait", a teal-green (leaning toward the cyan accent) for "go". Tuned a touch
# bright since a thin outline needs more punch than a fill did. The state shows
# ONLY in the outline; space-held shows in the status TEXT.
C_IDLE = BG
C_ARMED = "#d13a52"  # rose       -- pre-roll countdown (time is negative)
C_PLAY = "#17a074"   # teal-green -- click play NOW / running
FG = TXT


# ---------------------------------------------------- rounded-corner widgets
# Tk's stock button/entry are hard rectangles. These Canvas-based widgets draw a
# smooth rounded rect so the controls match Subtap's pill styling. Each one is
# "transparent" at the corners: its canvas bg tracks the window color (idle /
# red / green) via App._transparent so the rounding blends into the backdrop.
def _round_rect(cv, x1, y1, x2, y2, r, **kw):
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


class RoundButton(tk.Canvas):
    """Flat pill button. kind: normal | primary | warn."""

    def __init__(self, parent, text, command=None, kind="normal",
                 w=100, h=40, r=13, font=None, app=None):
        super().__init__(parent, width=w, height=h, highlightthickness=0, bd=0,
                         bg=parent["bg"], takefocus=0)
        self.text, self.command, self.kind = text, command, kind
        self.w, self.h, self.r, self.font = w, h, r, font
        self.enabled, self.hover, self.pressed = True, False, False
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        if app is not None:
            app._transparent.append(self)
        self._draw()

    def _skin(self):
        if not self.enabled:
            return PANEL2, LINE, DIM
        if self.kind == "primary":
            return (ACCENT_HI if self.hover else ACCENT), ACCENT, ACCENT_TX
        if self.kind == "warn":
            return (LINE if self.hover else PANEL2), DANGER, DANGER
        return (PANEL2_HI if self.hover else PANEL2), LINE, TXT

    def _draw(self):
        self.delete("all")
        fill, outline, fg = self._skin()
        _round_rect(self, 1, 1, self.w - 1, self.h - 1, self.r,
                    fill=fill, outline=outline, width=1)
        self.create_text(self.w / 2, self.h / 2 + (1 if self.pressed else 0),
                         text=self.text, fill=fg, font=self.font)

    def _enter(self, _):
        if self.enabled:
            self.hover = True
            self.configure(cursor="hand2")
            self._draw()

    def _leave(self, _):
        self.hover = self.pressed = False
        self._draw()

    def _press(self, _):
        if self.enabled:
            self.pressed = True
            self._draw()

    def _release(self, _):
        if self.enabled and self.pressed:
            self.pressed = False
            self._draw()
            if self.command:
                self.command()

    def set_enabled(self, on):
        self.enabled = bool(on)
        self.configure(cursor="hand2" if on else "arrow")
        self._draw()

    def set_text(self, t):
        self.text = t
        self._draw()


class RoundEntry(tk.Canvas):
    """Rounded box hosting a borderless Entry; border lights cyan on focus."""

    def __init__(self, parent, textvariable, w=66, h=36, r=11, font=None,
                 app=None):
        super().__init__(parent, width=w, height=h, highlightthickness=0, bd=0,
                         bg=parent["bg"])
        self.w, self.h, self.r, self.focused = w, h, r, False
        self.entry = tk.Entry(self, textvariable=textvariable, bd=0,
                              relief="flat", bg=PANEL2, fg=TXT,
                              disabledbackground=PANEL2, disabledforeground=DIM,
                              insertbackground=TXT, justify="center", font=font,
                              highlightthickness=0)
        self.entry.bind("<FocusIn>", lambda e: self._focus(True))
        self.entry.bind("<FocusOut>", lambda e: self._focus(False))
        self.create_window(w / 2, h / 2, window=self.entry,
                           width=w - 16, height=h - 12)
        if app is not None:
            app._transparent.append(self)
        self._draw()

    def _draw(self):
        self.delete("bg")
        _round_rect(self, 1, 1, self.w - 1, self.h - 1, self.r, fill=PANEL2,
                    outline=ACCENT if self.focused else LINE, width=1, tags="bg")
        self.tag_lower("bg")

    def _focus(self, on):
        self.focused = on
        self._draw()

    def set_state(self, state):
        self.entry.configure(state=state)


class RoundMenu(tk.Canvas):
    """Rounded dropdown: shows the current choice + caret, pops a menu on click."""

    def __init__(self, parent, variable, options, w=210, h=36, r=11, font=None,
                 app=None):
        super().__init__(parent, width=w, height=h, highlightthickness=0, bd=0,
                         bg=parent["bg"], takefocus=0)
        self.var, self.w, self.h, self.r, self.font = variable, w, h, r, font
        self.enabled, self.hover = True, False
        self.menu = tk.Menu(self, tearoff=0, bg=PANEL2, fg=TXT, bd=0,
                            activebackground=ACCENT, activeforeground=ACCENT_TX,
                            font=font)
        for opt in options:
            self.menu.add_command(label=opt,
                                  command=lambda o=opt: self._choose(o))
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._popup)
        if app is not None:
            app._transparent.append(self)
        self._draw()

    def _draw(self):
        self.delete("all")
        fill = PANEL2_HI if (self.hover and self.enabled) else PANEL2
        fg = TXT if self.enabled else DIM
        _round_rect(self, 1, 1, self.w - 1, self.h - 1, self.r, fill=fill,
                    outline=LINE, width=1)
        self.create_text(13, self.h / 2, text=self.var.get(), fill=fg,
                         font=self.font, anchor="w")
        self.create_text(self.w - 13, self.h / 2, text="▾", fill=DIM,
                         font=self.font, anchor="e")

    def _choose(self, opt):
        self.var.set(opt)
        self._draw()

    def _popup(self, _):
        if self.enabled:
            self.menu.post(self.winfo_rootx(), self.winfo_rooty() + self.h)

    def _enter(self, _):
        if self.enabled:
            self.hover = True
            self.configure(cursor="hand2")
            self._draw()

    def _leave(self, _):
        self.hover = False
        self._draw()

    def set_enabled(self, on):
        self.enabled = bool(on)
        self.configure(cursor="hand2" if on else "arrow")
        self._draw()

# output modes -- add more here later (e.g. mouse click, custom key)
MODE_SPACE = "Hold/release space"
MODE_TYPE = "Type lyrics"
MODES = [MODE_SPACE, MODE_TYPE]

# typing is paced out one char at a time so we don't overrun the target app's
# input queue. flat 25 ms/char = 40 chars/sec -- reliable, snappy, and still
# faster than Eminem "Rap God" peak (~30-37 chars/sec). line start stays synced.
CHAR_DELAY = 0.025

# The three transport buttons (Load SRT / GO / Stop) MUST stay one uniform size --
# they read as a single row. Size them here, together; never tweak one alone.
BTN_W, BTN_H, BTN_R = 100, 40, 13

# Lyric line: fixed 2-line area so the window never resizes. LYRIC_WRAP is chosen
# so the longest real lyric (~79 chars, "You Were Always Enough") fills two lines
# with a little slack; anything longer is truncated with an ellipsis (_fit_lyric).
LYRIC_WRAP = 344
LYRIC_LINES = 2

# Window + the "state" outline. The window background never changes color; instead
# a rounded outline is drawn in the padding around the UI and only appears while
# running (rose during the count-in, teal while playing). FRAME_PAD insets the UI
# from the edges; the outline sits in that margin.
WIN_W, WIN_H = 380, 468
FRAME_PAD_X, FRAME_PAD_Y = 16, 14
BORDER_INSET, BORDER_W, BORDER_R = 6, 3, 18


def _set_app_icon(root):
    """Give the window + taskbar a real icon (subsync.ico); silent if absent.

    Tk's iconbitmap only feeds a small frame, so at high DPI the taskbar upscales
    it and it looks fuzzy. We additionally push crisp big/small icons straight to
    the window via Win32 WM_SETICON -- LoadImageW picks the exact-size frame from
    the .ico (and handles its PNG frames), so no blurry upscale. Regenerate the
    icon with `python make_icon.py`.
    """
    ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subsync.ico")
    if not os.path.exists(ico):
        return
    try:
        # group under our own taskbar identity instead of python's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "RelentlessOldMan.Subsync")
    except Exception:  # noqa: BLE001
        pass
    try:
        root.iconbitmap(default=ico)
    except Exception:  # noqa: BLE001
        pass
    try:
        # NOTE: restype/argtypes matter on Win64 -- HANDLE/HWND are pointers and
        # ctypes truncates them to 32 bits without these (same class of bug as
        # SendInput). Set them before calling.
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR,
                                      wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                      wintypes.UINT)
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT,
                                        wintypes.WPARAM, wintypes.LPARAM)
        root.update_idletasks()
        hwnd = user32.GetAncestor(root.winfo_id(), 2)   # GA_ROOT (real toplevel)
        IMAGE_ICON, WM_SETICON, LR_LOADFROMFILE = 1, 0x0080, 0x0010
        # ICON_BIG (taskbar / alt-tab) big enough to downscale crisply; ICON_SMALL
        for which, size in ((1, 64), (0, 32)):
            h = user32.LoadImageW(None, ico, IMAGE_ICON, size, size,
                                  LR_LOADFROMFILE)
            if h:
                user32.SendMessageW(hwnd, WM_SETICON, which, h)
    except Exception:  # noqa: BLE001
        pass


class App:
    def __init__(self, root, srt_path=None):
        self.root = root
        self.subs = []
        self.events = []
        self.sched = []
        self.evt_idx = 0
        self.t0 = None          # perf_counter at the "click play" instant
        self.offset = 3.000     # seconds of pre-roll countdown (-offset -> 0)
        self.lead = 0.500       # fire keys this many seconds BEFORE the srt time
        self.state = "idle"     # idle | armed | running
        self.space_down = False
        self._painted = None    # last background color painted
        self._type_q = deque()  # pending (char/enter) keystrokes to pace out
        self._pumping = False
        self.srt_path = None

        root.title("Subsync")
        root.configure(bg=C_IDLE)
        _set_app_icon(root)
        root.attributes("-topmost", True)
        root.geometry(f"{WIN_W}x{WIN_H}")
        root.resizable(False, False)   # also drops the maximize box
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.mode_var = tk.StringVar(value=MODE_SPACE)
        self._transparent = []  # canvases whose bg tracks the window color

        big = tkfont.Font(family="Consolas", size=48, weight="bold")
        mid = tkfont.Font(family="Segoe UI", size=11)
        small = tkfont.Font(family="Segoe UI", size=9)
        brand = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self._btn_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        val = tkfont.Font(family="Segoe UI", size=11)

        # A full-window canvas hosts the UI (inset by FRAME_PAD) and draws the
        # rounded "state" outline in the surrounding margin. The window bg stays
        # dark at all times -- only the outline color signals armed/running.
        self.border = tk.Canvas(root, bg=C_IDLE, highlightthickness=0, bd=0)
        self.border.pack(fill="both", expand=True)
        self.frame = tk.Frame(self.border, bg=C_IDLE)
        self._frame_win = self.border.create_window(
            FRAME_PAD_X, FRAME_PAD_Y, anchor="nw", window=self.frame)
        self._border_color = None
        self.border.bind("<Configure>", self._on_resize)

        # ---- brand bar: "〰️ Subsync"  ....  version ------------------------
        top = tk.Frame(self.frame, bg=C_IDLE)
        top.pack(fill="x")
        tk.Label(top, text="〰️  Subsync", bg=C_IDLE, fg=ACCENT,
                 font=brand, anchor="w").pack(side="left")
        tk.Label(top, text=f"v{__version__}", bg=C_IDLE, fg=DIM,
                 font=small, anchor="e").pack(side="right")

        self.file_lbl = tk.Label(self.frame, text="No .srt loaded",
                                 bg=C_IDLE, fg=DIM, font=small, anchor="center")
        self.file_lbl.pack(fill="x", pady=(8, 0))

        self.clock = tk.Label(self.frame, text="--.--", bg=C_IDLE, fg=DIM,
                              font=big)
        self.clock.pack(pady=(6, 0))

        self.status = tk.Label(self.frame, text="load an .srt to begin",
                               bg=C_IDLE, fg=DIM, font=mid)
        self.status.pack(pady=(2, 0))

        # lyric: a fixed LYRIC_LINES-tall area so the window never jumps; text is
        # pre-wrapped/truncated to fit (see _fit_lyric).
        self._lyric_font = mid
        self.lyric = tk.Label(self.frame, text="", bg=C_IDLE, fg=TXT, font=mid,
                              height=LYRIC_LINES, wraplength=LYRIC_WRAP,
                              justify="center")
        self.lyric.pack(fill="x", pady=(4, 8))

        # hairline separator between the "display" and the "controls"
        self.sep = tk.Frame(self.frame, bg=LINE, height=1)
        self.sep.pack(fill="x", pady=(0, 10))

        # controls block -- lead + mode share a grid so their labels line up in
        # one right-aligned column and their controls in one left-aligned column,
        # and the whole block is centered (keeps the rows from looking ragged).
        ctrl = tk.Frame(self.frame, bg=C_IDLE)
        ctrl.pack()

        tk.Label(ctrl, text="lead", bg=C_IDLE, fg=DIM, font=small, anchor="e"
                 ).grid(row=0, column=0, sticky="e", padx=(0, 10))
        lgrp = tk.Frame(ctrl, bg=C_IDLE)
        lgrp.grid(row=0, column=1, sticky="w")
        RoundButton(lgrp, "−", lambda: self.bump_lead(-0.010), "normal",
                    w=36, h=36, r=11, font=self._btn_font, app=self
                    ).pack(side="left", padx=(0, 4))
        self.lead_var = tk.StringVar(value="500")
        self.lead_entry = RoundEntry(lgrp, self.lead_var, w=66, h=36, r=11,
                                     font=val, app=self)
        self.lead_entry.pack(side="left")
        self.lead_entry.entry.bind("<Return>", lambda e: self._commit_lead())
        self.lead_entry.entry.bind("<FocusOut>", lambda e: self._commit_lead())
        RoundButton(lgrp, "+", lambda: self.bump_lead(0.010), "normal",
                    w=36, h=36, r=11, font=self._btn_font, app=self
                    ).pack(side="left", padx=(4, 8))
        self.lead_hint = tk.Label(lgrp, text="ms early", bg=C_IDLE, fg=DIM,
                                  font=small, width=7, anchor="w")
        self.lead_hint.pack(side="left")

        tk.Label(ctrl, text="mode", bg=C_IDLE, fg=DIM, font=small, anchor="e"
                 ).grid(row=1, column=0, sticky="e", padx=(0, 10), pady=(12, 0))
        self.mode_menu = RoundMenu(ctrl, self.mode_var, MODES, w=214, h=36,
                                   r=11, font=mid, app=self)
        self.mode_menu.grid(row=1, column=1, sticky="w", pady=(12, 0))

        # transport buttons -- all three the same size (BTN_W x BTN_H); centered
        brow = tk.Frame(self.frame, bg=C_IDLE)
        brow.pack(pady=(16, 0))
        self.load_btn = RoundButton(brow, "Load SRT", self.load, "normal",
                                    w=BTN_W, h=BTN_H, r=BTN_R,
                                    font=self._btn_font, app=self)
        self.load_btn.pack(side="left", padx=5)
        self.go_btn = RoundButton(brow, "GO", self.go, "primary",
                                  w=BTN_W, h=BTN_H, r=BTN_R,
                                  font=self._btn_font, app=self)
        self.go_btn.pack(side="left", padx=5)
        self.stop_btn = RoundButton(brow, "Stop", self.stop, "warn",
                                    w=BTN_W, h=BTN_H, r=BTN_R,
                                    font=self._btn_font, app=self)
        self.stop_btn.pack(side="left", padx=5)
        self._set_go_enabled(False)
        self._set_stop_enabled(False)

        # footer hint + copyright, pinned to the bottom (copyright lowest)
        self.copyright = tk.Label(self.frame, text="© 2026 RelentlessOldMan",
                                  bg=C_IDLE, fg=DIM, font=small)
        self.copyright.pack(side="bottom", pady=(0, 4))
        self.footer = tk.Label(
            self.frame, text="Esc  stop + release      ↑ / ↓  nudge lead",
            bg=C_IDLE, fg=DIM, font=small)
        self.footer.pack(side="bottom", pady=(12, 4))

        root.bind("<Escape>", lambda e: self.stop())
        root.bind("<Up>", lambda e: self.bump_lead(0.010))
        root.bind("<Down>", lambda e: self.bump_lead(-0.010))

        if srt_path:
            self._set_srt(srt_path)

    # ---------------------------------------------------------- widget state
    def _set_go_enabled(self, on):
        self.go_btn.set_enabled(on)

    def _set_stop_enabled(self, on):
        self.stop_btn.set_enabled(on)

    # ---------------------------------------------------------------- helpers
    def _set_color(self, color):
        # "color" is the run state: C_IDLE (no outline), C_ARMED (rose) or
        # C_PLAY (teal). Repaint only on change to avoid per-tick redraws.
        if color != self._painted:
            self._painted = color
            self._border_color = None if color == C_IDLE else color
            self._draw_border(self._border_color)

    def _draw_border(self, color):
        cv = self.border
        cv.delete("stateborder")
        if not color:
            return
        w = cv.winfo_width() or WIN_W
        h = cv.winfo_height() or WIN_H
        _round_rect(cv, BORDER_INSET, BORDER_INSET, w - BORDER_INSET,
                    h - BORDER_INSET, BORDER_R, outline=color, width=BORDER_W,
                    fill="", tags="stateborder")

    def _on_resize(self, e):
        # keep the UI inset from the edges, then redraw the outline to fit
        self.border.itemconfigure(self._frame_win, width=e.width - 2 * FRAME_PAD_X,
                                  height=e.height - 2 * FRAME_PAD_Y)
        self._draw_border(self._border_color)

    def _type_mode(self):
        return self.mode_var.get() == MODE_TYPE

    def _fit_lyric(self, text):
        # Pre-wrap to LYRIC_LINES lines at LYRIC_WRAP px so the fixed-height label
        # never overflows; truncate the last line with an ellipsis if it can't fit.
        if not text:
            return ""
        f, W = self._lyric_font, LYRIC_WRAP
        lines, cur = [], ""
        for word in text.split():
            trial = word if not cur else cur + " " + word
            if f.measure(trial) <= W or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        if len(lines) <= LYRIC_LINES:
            return "\n".join(lines)
        head = lines[:LYRIC_LINES - 1]
        tail = " ".join(lines[LYRIC_LINES - 1:])
        while tail and f.measure(tail + "…") > W:
            tail = tail.rsplit(" ", 1)[0] if " " in tail else tail[:-1]
        head.append((tail + "…") if tail else "…")
        return "\n".join(head)

    def bump_lead(self, d):
        if self.state != "idle":
            return
        self._set_lead(round(self.lead + d, 3))

    def _commit_lead(self):
        # parse whatever is typed in the box (accepts "500", "-200", "500 ms")
        raw = self.lead_var.get().lower().replace("ms", "").strip()
        try:
            ms = int(round(float(raw)))
        except ValueError:
            ms = int(round(self.lead * 1000))   # bad input -> revert
        self._set_lead(ms / 1000.0)

    def _set_lead(self, sec):
        self.lead = max(-2.0, min(5.0, round(sec, 3)))
        ms = int(round(self.lead * 1000))
        self.lead_var.set(str(ms))
        self.lead_hint.configure(
            text="ms early" if ms > 0 else "ms late" if ms < 0 else "ms")

    def load(self):
        path = filedialog.askopenfilename(
            title="Pick an .srt", filetypes=[("SubRip", "*.srt"), ("All", "*.*")])
        if path:
            self._set_srt(path)

    def _set_srt(self, path):
        try:
            subs = parse_srt(path)
        except Exception as ex:  # noqa: BLE001
            self.status.configure(text=f"parse error: {ex}")
            return
        if not subs:
            self.status.configure(text="no subtitles found in that file")
            return
        self.srt_path = path
        self.subs = subs
        self.events = build_events(subs)
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        self.file_lbl.configure(text=f"{name}  ({len(subs)} lines)")
        self.status.configure(text="ready — press GO, then click Play on cue",
                              fg=DIM)
        self.clock.configure(text="--.--", fg=DIM)
        self.lyric.configure(text="")
        self._set_go_enabled(True)

    # ------------------------------------------------------------------- run
    def go(self):
        if self.state != "idle" or not self.events:
            return
        self._commit_lead()          # apply whatever is typed in the box
        self.evt_idx = 0
        self._type_q.clear()
        self._pumping = False
        lead = self.lead
        # subtract the lead so keys fire early; keep hold-durations intact
        if self._type_mode():
            self.sched = [(s - lead, "type", txt)
                          for (s, e, txt) in self.subs if txt]
        else:
            self.sched = [(t - lead, "space", a == "down")
                          for (t, a) in self.events]
        self.state = "running"
        self._set_go_enabled(False)
        self.load_btn.set_enabled(False)
        self.mode_menu.set_enabled(False)
        self.lead_entry.set_state("disabled")
        self._set_stop_enabled(True)
        # t0 is the projected "click play" instant; elapsed runs -offset -> 0 -> dur
        self.t0 = time.perf_counter() + self.offset
        self._set_color(C_ARMED)
        # live text goes white while the rose/teal outline signals the state
        self.clock.configure(fg=TXT)
        self.status.configure(fg=TXT)
        self.lyric.configure(fg=TXT, text="")
        self._tick()

    def _tick(self):
        if self.state != "running":
            return
        elapsed = time.perf_counter() - self.t0
        # fire every scheduled key event that is now due (may fire during count-in)
        while self.evt_idx < len(self.sched) and \
                self.sched[self.evt_idx][0] <= elapsed:
            _, kind, payload = self.sched[self.evt_idx]
            if kind == "space":
                self._set_space(payload)
            else:
                self._enqueue_line(payload)
            self.evt_idx += 1

        if elapsed < 0:                          # ---- count-in (red) ----
            self.clock.configure(text=f"-{-elapsed:05.2f}")
            self.status.configure(text="GET READY — hit PLAY at 0")
            self.lyric.configure(text="")
            self._set_color(C_ARMED)
        else:                                    # ---- song running (green) ----
            self.clock.configure(text=f"{elapsed:06.2f}")
            cur = ""
            for s, e, txt in self.subs:
                if s <= elapsed < e:
                    cur = txt
                    break
            self.lyric.configure(text=self._fit_lyric(cur))
            if elapsed < 0.6:
                self.status.configure(text="▶  CLICK PLAY NOW")
            elif self.space_down:
                self.status.configure(text="●  SPACE HELD")
            else:
                self.status.configure(text="⌨  typing" if self._type_mode()
                                      else "▶  running")
            self._set_color(C_PLAY)

        # in type mode, wait for the paced-out queue to finish before ending
        if self.evt_idx >= len(self.sched) and elapsed >= 0 \
                and not self._type_q and not self._pumping:
            self._finish()
            return
        self.root.after(4, self._tick)

    def _enqueue_line(self, txt):
        for ch in txt:
            self._type_q.append(("char", ch, CHAR_DELAY))
        self._type_q.append(("enter", None, CHAR_DELAY))
        if not self._pumping:
            self._pumping = True
            self._pump()

    def _pump(self):
        # drain one keystroke, then schedule the next -- self-throttling so the
        # target app's input queue never floods
        if self.state != "running" or not self._type_q:
            self._pumping = False
            return
        kind, ch, delay = self._type_q.popleft()
        if kind == "char":
            _send_char(ch)
        else:
            _send_scan(ENTER_SCAN, True)
            _send_scan(ENTER_SCAN, False)
        self.root.after(max(1, int(round(delay * 1000))), self._pump)

    def _set_space(self, down):
        if down and not self.space_down:
            _send_space(True)
            self.space_down = True
        elif not down and self.space_down:
            _send_space(False)
            self.space_down = False

    def _finish(self):
        self._set_space(False)
        self.status.configure(text="done ✓")
        self.lyric.configure(text="")
        self._reset_buttons()
        self.state = "idle"
        self._set_color(C_IDLE)

    def stop(self):
        if self.state == "idle":
            return
        self._set_space(False)
        self.state = "idle"
        self._type_q.clear()
        self._pumping = False
        self.status.configure(text="stopped", fg=DIM)
        self.clock.configure(text="--.--", fg=DIM)
        self.lyric.configure(text="")
        self._set_color(C_IDLE)
        self._reset_buttons()

    def _reset_buttons(self):
        self._set_go_enabled(bool(self.events))
        self.load_btn.set_enabled(True)
        self.mode_menu.set_enabled(True)
        self.lead_entry.set_state("normal")
        self._set_stop_enabled(False)

    def on_close(self):
        self._set_space(False)
        self.root.destroy()

    # ------------------------------------------------------------- posed demo
    def _pose(self, variant="ready"):
        """Render a real UI state with sample content, for a docs screenshot.

        "ready" = dark resting state after loading; "run" = teal running state
        with the space held; "armed" = rose count-in. All mirror what the app
        actually shows -- no fabricated states.
        """
        self.file_lbl.configure(text="You Were Always Enough.srt  (41 lines)")
        if variant in ("run", "armed"):
            self.state = "running"
            self._set_go_enabled(False)
            self.load_btn.set_enabled(False)
            self.mode_menu.set_enabled(False)
            self.lead_entry.set_state("disabled")
            self._set_stop_enabled(True)
            self.clock.configure(fg=TXT)
            self.status.configure(fg=TXT)
            self.lyric.configure(fg=TXT)
        if variant == "run":
            self.clock.configure(text="34.62")
            self.status.configure(text="●  SPACE HELD")
            self.lyric.configure(text=self._fit_lyric(
                "You were loved for just being, for the small "
                "and simple fact of where you stand"))
            self._set_color(C_PLAY)
        elif variant == "armed":
            self.clock.configure(text="-1.30")
            self.status.configure(text="GET READY — hit PLAY at 0")
            self.lyric.configure(text="")
            self._set_color(C_ARMED)
        else:
            self.clock.configure(text="--.--", fg=DIM)
            self.status.configure(text="ready — press GO, then click Play on cue",
                                  fg=DIM)
            self.lyric.configure(text="")
            self._set_go_enabled(True)


def main():
    srt = None
    args = list(sys.argv[1:])
    pose = None
    if "--demo" in args:
        i = args.index("--demo")
        pose = "ready"
        if i + 1 < len(args) and args[i + 1] in ("ready", "run", "armed"):
            pose = args[i + 1]
        args = [a for a in args if a not in ("--demo", "ready", "run", "armed")]
    if args and args[0].lower().endswith(".srt"):
        srt = args[0]
    root = tk.Tk()
    app = App(root, srt)
    if pose:
        app._pose(pose)
    root.mainloop()


if __name__ == "__main__":
    main()
