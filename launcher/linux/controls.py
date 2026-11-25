"""Game input bindings: SDL names, an interactive dual-screen diagram and capture."""
from __future__ import annotations

import ctypes as c
from ctypes.util import find_library
import sys

BINDINGS = {
    "l": ("L", "Q", "leftshoulder"), "zl": ("ZL", "1", "lefttrigger"),
    "up": ("D-pad Up", "Up", "dpup"), "down": ("D-pad Down", "Down", "dpdown"),
    "left": ("D-pad Left", "Left", "dpleft"), "right": ("D-pad Right", "Right", "dpright"),
    "select": ("Select", "Backspace", "back"), "r": ("R", "E", "rightshoulder"),
    "zr": ("ZR", "3", "righttrigger"), "x": ("X", "I", "y"), "y": ("Y · Run", "U", "x"),
    "a": ("A", "K", "b"), "b": ("B · Jump", "J", "a"), "start": ("Start · Pause", "Return", "start"),
    "circle_up": ("Circle Pad Up", "W", ""), "circle_down": ("Circle Pad Down", "S", ""),
    "circle_left": ("Circle Pad Left", "A", ""), "circle_right": ("Circle Pad Right", "D", ""),
}
PAD_NAMES = {
    "a": "South (Xbox A)", "b": "East (Xbox B)", "x": "West (Xbox X)", "y": "North (Xbox Y)",
    "leftshoulder": "Left bumper", "rightshoulder": "Right bumper", "lefttrigger": "Left trigger",
    "righttrigger": "Right trigger", "start": "Menu / Start", "back": "View / Back", "leftstick": "L3",
    "dpup": "D-pad Up", "dpdown": "D-pad Down", "dpleft": "D-pad Left", "dpright": "D-pad Right",
    "misc1": "Share / Capture", "touchpad": "Touchpad click", "paddle1": "Right paddle 1",
    "paddle2": "Left paddle 1", "paddle3": "Right paddle 2", "paddle4": "Left paddle 2",
}
KEY_ROWS = ((10, "1234567890"), (24, "QWERTYUIOP"), (38, "ASDFGHJKL"), (52, "ZXCVBNM"))
KEY_FIXES = {"Shift_L": "Left Shift", "Shift_R": "Right Shift", "Control_L": "Left Ctrl",
             "Control_R": "Right Ctrl", "Alt_L": "Left Alt", "Alt_R": "Right Alt",
             "space": "Space", "BackSpace": "Backspace", "Prior": "PageUp", "Next": "PageDown",
             "minus": "-", "equal": "=", "bracketleft": "[", "bracketright": "]", "backslash": "\\",
             "semicolon": ";", "apostrophe": "'", "grave": "`", "comma": ",", "period": ".", "slash": "/"}


def keyboard_name(event):
    key = event.keysym
    if key in {"Escape", "Tab", "ISO_Left_Tab"} or key in {f"F{i}" for i in range(5, 13)}:
        return None
    # Tk on Linux uses X11/XWayland keycodes. Standard keyboard rows retain their physical
    # positions across layouts, matching SDL_GetScancodeFromName in the game.
    if sys.platform.startswith("linux"):
        for first, row in KEY_ROWS:
            if first <= event.keycode < first + len(row):
                return row[event.keycode - first]
    if len(key) == 1 and key.isascii() and key.isalnum():
        return key.upper()
    if key in {"Return", "Up", "Down", "Left", "Right", "Home", "End", "Insert", "Delete", "F1", "F2", "F3", "F4"}:
        return key
    return KEY_FIXES.get(key)


class SdlGamepads:
    """Optional shared SDL3; manual controller assignment does not need this."""
    def __init__(self):
        self.lib = c.CDLL(find_library("SDL3") or "libSDL3.so.0")
        self.devices = {}
        self.initialized = False
        self._set("SDL_InitSubSystem", c.c_bool, c.c_uint32)
        self._set("SDL_QuitSubSystem", None, c.c_uint32)
        self._set("SDL_SetHint", c.c_bool, c.c_char_p, c.c_char_p)
        self._set("SDL_SetGamepadEventsEnabled", None, c.c_bool)
        self._set("SDL_UpdateGamepads", None)
        self._set("SDL_GetGamepads", c.POINTER(c.c_uint32), c.POINTER(c.c_int))
        self._set("SDL_free", None, c.c_void_p)
        self._set("SDL_OpenGamepad", c.c_void_p, c.c_uint32)
        self._set("SDL_CloseGamepad", None, c.c_void_p)
        self._set("SDL_GetGamepadButton", c.c_bool, c.c_void_p, c.c_int)
        self._set("SDL_GetGamepadAxis", c.c_int16, c.c_void_p, c.c_int)
        self._set("SDL_GetGamepadStringForButton", c.c_char_p, c.c_int)
        self.lib.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
        if not self.lib.SDL_InitSubSystem(0x2000):
            raise RuntimeError("SDL3 gamepads unavailable")
        self.initialized = True
        self.lib.SDL_SetGamepadEventsEnabled(False)

    def _set(self, name, result, *arguments):
        function = getattr(self.lib, name)
        function.restype, function.argtypes = result, arguments

    def sample(self):
        sdl = self.lib
        sdl.SDL_UpdateGamepads()
        count = c.c_int()
        items = sdl.SDL_GetGamepads(c.byref(count))
        try:
            ids = set(items[:count.value]) if items else set()
        finally:
            if items:
                sdl.SDL_free(items)
        for device in self.devices.keys() - ids:
            sdl.SDL_CloseGamepad(self.devices.pop(device))
        for device in ids - self.devices.keys():
            handle = sdl.SDL_OpenGamepad(device)
            if handle:
                self.devices[device] = handle
        buttons = set()
        for handle in self.devices.values():
            for idx in range(26):
                if sdl.SDL_GetGamepadButton(handle, idx) and (name := sdl.SDL_GetGamepadStringForButton(idx)):
                    buttons.add(name.decode("ascii"))
            if sdl.SDL_GetGamepadAxis(handle, 4) > 16000:
                buttons.add("lefttrigger")
            if sdl.SDL_GetGamepadAxis(handle, 5) > 16000:
                buttons.add("righttrigger")
        return len(self.devices), buttons

    def close(self):
        if self.initialized:
            for handle in self.devices.values():
                self.lib.SDL_CloseGamepad(handle)
            self.devices.clear()
            self.lib.SDL_QuitSubSystem(0x2000)
            self.initialized = False


def draw_handheld(canvas, select):
    def body(x1, y1, x2, y2, radius, fill, outline):
        points = (x1+radius,y1,x2-radius,y1,x2,y1,x2,y1+radius,x2,y2-radius,x2,y2,x2-radius,y2,
                  x1+radius,y2,x1,y2,x1,y2-radius,x1,y1+radius,x1,y1)
        canvas.create_polygon(points, smooth=True, splinesteps=12, fill=fill, outline=outline, width=2)
    def hot(id, x, y, text, width=26, height=21, round_=False):
        coords = (x-width/2, y-height/2, x+width/2, y+height/2)
        draw = canvas.create_oval if round_ else canvas.create_rectangle
        draw(*coords, fill="#182231", outline="#8196B6", tags=(id, "hot"))
        canvas.create_text(x, y, text=text, fill="#EFF5FF", font=("TkDefaultFont", 8, "bold"), tags=(id, "hot"))
        canvas.tag_bind(id, "<Button-1>", lambda _event: select(id))
    body(46, 10, 288, 130, 13, "#2B3B53", "#7187A4")
    body(82, 24, 252, 119, 5, "#142237", "#94A8CA")
    canvas.create_polygon(87, 29, 192, 29, 144, 114, 87, 114, fill="#233B5A", outline="")
    canvas.create_text(167, 50, text="TOP SCREEN", fill="#A7BCD9", font=("TkDefaultFont", 8))
    canvas.create_text(167, 77, text="3D LAND", fill="#DCE9FF", font=("TkDefaultFont", 20, "bold"))
    canvas.create_oval(165, 16, 169, 20, fill="#152135", outline="")
    body(46, 128, 288, 145, 6, "#162130", "#7589A6")
    body(46, 146, 288, 256, 14, "#30435E", "#7187A4")
    body(103, 154, 232, 230, 5, "#17273C", "#8297B4")
    canvas.create_rectangle(117, 169, 218, 214, dash=(2, 3), outline="#5B759B")
    canvas.create_text(167, 192, text="TOUCH SCREEN", fill="#A9BCDB", font=("TkDefaultFont", 8))
    canvas.create_oval(61, 156, 91, 186, fill="#93A2B8", outline="#C5D3E4", width=2)
    for id, x, y, label in (("up", 76, 196, "↑"), ("down", 76, 226, "↓"),
                            ("left", 61, 211, "←"), ("right", 91, 211, "→")):
        hot(id, x, y, label, 14, 14, True)
    for id, x, y in (("x", 257, 162), ("y", 242, 180), ("a", 272, 180), ("b", 257, 199)):
        hot(id, x, y, id.upper(), 19, 19, True)
    for id, x, y in (("l", 64, 138), ("r", 270, 138), ("zl", 64, 113), ("zr", 270, 113)):
        hot(id, x, y, id.upper(), 25, 15)
    hot("select", 123, 241, "SEL", 32, 15)
    hot("start", 212, 241, "START", 38, 15)
    canvas.tag_bind("hot", "<Enter>", lambda _event: canvas.configure(cursor="hand2"))
    canvas.tag_bind("hot", "<Leave>", lambda _event: canvas.configure(cursor=""))
