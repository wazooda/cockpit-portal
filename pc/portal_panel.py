#!/usr/bin/env python3
"""The Cockpit Portal page in the SteamVR dashboard, clickable with the laser.

Positions: open, close and rename the portals. Adjust: move, resize, fix a double image, save. Hotkeys: change any key.
Help: what to do, in words a first-time user can follow.

Runs inside cockpit_portal.py, on its own thread, and sends the same actions as the hotkeys. It never starts SteamVR: it
attaches only while vrmonitor.exe runs with a headset present. Run this file directly to draw each page to PNGs.

usage: portal_panel.py preview OUT_DIR
"""
import ctypes
import os
import subprocess
import sys
import tempfile
import time

import portal_keys as pk

W, H = 1280, 820
BG, CARD, LINE = (14, 17, 22), (24, 29, 37), (58, 66, 77)
WHITE, DIM, FAINT = (235, 240, 245), (150, 160, 172), (112, 120, 132)
ACCENT, GREEN, AMBER, RED = (64, 156, 255), (63, 185, 80), (222, 165, 50), (248, 81, 73)
FONT_DIR = r"C:\Windows\Fonts"
NO_WINDOW = 0x08000000
PAGES = (("positions", "Positions"), ("adjust", "Adjust"), ("hotkeys", "Hotkeys"), ("help", "Help"))
OVERLAY_METRES = 2.2
FRAME_S = 0.1
CAPTURE_FRAME_S = 0.02
CAPTURE_SECONDS = 15
NAME_MAX = 20
HOTKEY_ROWS = 8

HELP = (
    ("What this does", "A portal is a window in your VR view that shows the real room, so you can see your hands and "
                       "controls. It stays at one spot in your view and moves with your head."),
    ("Use one", "On Positions, tap a name to open that portal. Tap it again to close it, or tap another to jump there."),
    ("Move or resize it", "Open a position, then go to Adjust. Use the arrows to move it, and Bigger or Smaller to change its size."),
    ("If it looks double", "Look at the edge of the portal. If you see two overlapping circles, tap the arrows under "
                           "\"Looks double?\" until they become one."),
    ("Keep your changes", "Tap Save. Changes you do not save last until the connection to the headset drops. "
                          "Undo returns to the last save."),
    ("Names and keys", "Tap Rename on a position to change its name. On Hotkeys, tap Change and press the new key."),
)


def title(name):
    return name.replace("_", " ").replace("-", " ").title()


def clean_name(text):
    """What can go down the link to the headset: plain characters, one line."""
    kept = "".join(ch for ch in " ".join(text.split()) if " " <= ch <= "~")
    return " ".join(kept.split())[:NAME_MAX].strip()


def fonts():
    from PIL import ImageFont

    def font(size, bold=False):
        for name in ("segoeuib.ttf" if bold else "segoeui.ttf", "arial.ttf"):
            try:
                return ImageFont.truetype(os.path.join(FONT_DIR, name), size)
            except OSError:
                continue
        return ImageFont.load_default()
    return {"title": font(42, True), "h": font(30, True), "t": font(27), "s": font(23), "x": font(20), "big": font(38, True)}


def fit(draw, text, font, width):
    """The text, shortened with ... if it is wider than width."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "...", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "..."


def wrap(draw, text, font, width):
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and draw.textlength(trial, font=font) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    return lines + [current] if current else []


class Panel:
    """Draws from the listener's state. send(action) queues the same action a hotkey would."""

    def __init__(self, send, get_state, keys):
        self.send, self.get_state, self.keys = send, get_state, keys
        self.page = "positions"
        self.f = fonts()
        self.hits = []
        self.capturing = None       # the action waiting for a key press
        self.capture_until = 0.0
        self.held = None            # a refused key that has not been let go yet
        self.note = ""              # the result of the last key change, in words
        self.ask_name = None        # (slot, current name), when the VR keyboard should open
        self.naming = None          # the slot the VR keyboard is open for
        self.typed = ""             # what has been typed on it so far
        self.keyboard_open = False

    def key_text(self, action_id):
        return pk.key_name(*self.keys.bindings[action_id])

    def label(self, state, slot):
        return state.get("labels", {}).get(slot) or title(slot)

    def go(self, page):
        self.cancel_capture()
        self.page = page

    # ---------- drawing helpers ----------
    def button(self, d, box, label, action, on=False, enabled=True, font="t", colour=None):
        x0, y0, x1, y1 = box
        fill = (colour or ACCENT) if on else CARD
        edge = fill if on else (LINE if enabled else (38, 44, 52))
        d.rounded_rectangle(box, 14, fill=fill, outline=edge, width=3)
        d.text(((x0 + x1) / 2, (y0 + y1) / 2), label, font=self.f[font], fill=WHITE if enabled else FAINT, anchor="mm")
        if enabled:
            self.hits.append((box, action))

    def arrow_button(self, d, box, way, action, enabled):
        x0, y0, x1, y1 = box
        d.rounded_rectangle(box, 14, fill=CARD, outline=LINE if enabled else (38, 44, 52), width=3)
        cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, 17
        points = {"up": [(cx, cy - r), (cx - r, cy + r), (cx + r, cy + r)],
                  "down": [(cx, cy + r), (cx - r, cy - r), (cx + r, cy - r)],
                  "left": [(cx - r, cy), (cx + r, cy - r), (cx + r, cy + r)],
                  "right": [(cx + r, cy), (cx - r, cy - r), (cx - r, cy + r)]}[way]
        d.polygon(points, fill=WHITE if enabled else FAINT)
        if enabled:
            self.hits.append((box, action))

    def pad(self, d, x, y, size, heading, note, kind, enabled):
        """Four arrows in a cross, with their keys under it. kind is "move" or "align"."""
        d.text((x + size * 3 / 2 + 6, y), heading, font=self.f["h"], fill=WHITE, anchor="mt")
        d.text((x + size * 3 / 2 + 6, y + 40), note, font=self.f["s"], fill=DIM, anchor="mt")
        top, gap = y + 82, 6
        for way, col, row in (("up", 1, 0), ("left", 0, 1), ("right", 2, 1), ("down", 1, 2)):
            bx, by = x + col * (size + gap), top + row * (size + gap)
            action = pk.ACTION_OF[f"{kind} {way}"]
            self.arrow_button(d, (bx, by, bx + size, by + size), way, lambda a=action: self.send(a), enabled)
        names = [self.key_text(f"{kind} {way}") for way in ("up", "down", "left", "right")]
        below = top + 3 * (size + gap) + 2
        d.text((x + size * 3 / 2 + 6, below), "Keyboard", font=self.f["x"], fill=FAINT, anchor="mt")
        d.text((x + size * 3 / 2 + 6, below + 24), pk.hint(names), font=self.f["x"], fill=FAINT, anchor="mt")

    # ---------- pages ----------
    def header(self, d, state):
        d.text((40, 26), "Cockpit Portal", font=self.f["title"], fill=WHITE)
        connected, on = state.get("connected"), state.get("on")
        status = ("Headset not connected", RED) if not connected else \
                 (f"{self.label(state, state.get('active', ''))} is open", GREEN) if on else ("Portal closed", DIM)
        width = d.textlength(status[0], font=self.f["t"])
        d.ellipse((W - 40 - width - 36, 42, W - 40 - width - 14, 64), fill=status[1])
        d.text((W - 40, 53), status[0], font=self.f["t"], fill=WHITE, anchor="rm")
        for i, (page, label) in enumerate(PAGES):
            x = 40 + i * 230
            self.button(d, (x, 100, x + 210, 164), label, lambda p=page: self.go(p), on=self.page == page)
        d.line((40, 184, W - 40, 184), fill=LINE, width=2)

    def draw_positions(self, d, state):
        on, active = state.get("on"), state.get("active")
        if not state.get("connected"):
            self.offline(d)
            return
        if self.naming and self.keyboard_open:
            d.text((40, 200), f"New name for {self.label(state, self.naming)}: {self.typed}_   then tap Enter",
                   font=self.f["h"], fill=AMBER)
        else:
            d.text((40, 204), f"Tap a position to open it. Tap it again to close it. On or off by keyboard: {self.key_text('toggle')}",
                   font=self.f["s"], fill=DIM)
        card_w, card_h = 590, 170
        for i, slot in enumerate(state.get("slots", [])[:4]):
            x, y = 40 + (i % 2) * (card_w + 20), 256 + (i // 2) * (card_h + 20)
            box = (x, y, x + card_w, y + card_h)
            is_open = on and slot == active
            name = self.label(state, slot)
            d.rounded_rectangle(box, 18, fill=ACCENT if is_open else CARD, outline=ACCENT if is_open else LINE, width=3)
            d.text((x + 32, y + 26), fit(d, name, self.f["big"], card_w - 210), font=self.f["big"], fill=WHITE)
            d.text((x + 32, y + 84), "Open now. Tap to close." if is_open else "Tap to open",
                   font=self.f["t"], fill=WHITE if is_open else DIM)
            action_id = f"open {slot}"
            if action_id in self.keys.bindings:
                d.text((x + 32, y + 124), f"Keyboard: {self.key_text(action_id)}", font=self.f["s"], fill=WHITE if is_open else FAINT)
            # The button's hit comes before the card's, so a tap on Rename does not also open the portal.
            self.button(d, (x + card_w - 160, y + 20, x + card_w - 20, y + 76), "Rename",
                        lambda s=slot, n=name: setattr(self, "ask_name", (s, n)), font="s")
            self.hits.append((box, lambda s=slot: self.send(f"open {s}")))
        y = 256 + 2 * (card_h + 20) + 2
        self.button(d, (40, y, 630, y + 96), "Adjust this portal" if on else "Open a position to adjust it",
                    lambda: self.go("adjust"), enabled=bool(on), font="h")

    def draw_adjust(self, d, state):
        on, active = state.get("on"), state.get("active", "")
        if not state.get("connected"):
            self.offline(d)
            return
        d.text((40, 200), f"Adjusting {self.label(state, active)}" if on else "Open a position first, on the Positions page.",
               font=self.f["h"], fill=WHITE if on else AMBER)
        unsaved = active in state.get("unsaved", [])
        if unsaved:
            d.text((W - 40, 218), "Not saved yet", font=self.f["t"], fill=AMBER, anchor="rm")
        size, top = 82, 252
        self.pad(d, 50, top, size, "Move", "Where it sits in your view", "move", on)
        self.pad(d, 880, top, size, "Looks double?", "Tap until it is one circle", "align", on)
        x = 500
        d.text((x + 140, top), "Size", font=self.f["h"], fill=WHITE, anchor="mt")
        d.text((x + 140, top + 40), f"{pk.SIZE_PERCENT}% each tap", font=self.f["s"], fill=DIM, anchor="mt")
        self.button(d, (x, top + 82, x + 280, top + 172), "Bigger", lambda: self.send(pk.ACTION_OF["bigger"]),
                    enabled=bool(on), font="h")
        self.button(d, (x, top + 184, x + 280, top + 274), "Smaller", lambda: self.send(pk.ACTION_OF["smaller"]),
                    enabled=bool(on), font="h")
        d.text((x + 140, top + 284), "Keyboard", font=self.f["x"], fill=FAINT, anchor="mt")
        d.text((x + 140, top + 308), pk.hint([self.key_text("bigger"), self.key_text("smaller")]),
               font=self.f["x"], fill=FAINT, anchor="mt")
        y = 700
        save_label = f"Save  ({self.key_text('save')})" if unsaved else "Saved"
        self.button(d, (40, y, 620, y + 88), save_label, lambda: self.send("save"), on=unsaved, enabled=unsaved, font="h", colour=GREEN)
        self.button(d, (660, y, 1240, y + 88), "Undo changes", lambda: self.send("revert"), enabled=unsaved, font="h")

    def draw_hotkeys(self, d, state):
        note = self.keys.note or self.note
        if self.capturing:
            what = pk.label_of(self.capturing) or self.label(state, self.capturing.replace("open ", ""))
            if self.note:
                d.text((40, 204), fit(d, self.note, self.f["s"], W - 230), font=self.f["s"], fill=RED)
            else:
                d.text((40, 200), f"Press the new key for {what}.", font=self.f["h"], fill=AMBER)
            d.text((W - 40, 216), "Esc cancels", font=self.f["t"], fill=DIM, anchor="rm")
        else:
            d.text((40, 204), note or "Tap Change, then press the new key. Letters and numbers need Ctrl or Alt held too.",
                   font=self.f["s"], fill=AMBER if note else DIM)
        for i, action_id in enumerate(pk.ACTION_OF):
            col, row = i // HOTKEY_ROWS, i % HOTKEY_ROWS
            x, y = 40 + col * 610, 248 + row * 60
            name = pk.label_of(action_id) or self.label(state, action_id.replace("open ", ""))
            waiting = self.capturing == action_id
            d.text((x, y + 26), fit(d, name, self.f["s"], 205), font=self.f["s"], fill=WHITE, anchor="lm")
            d.text((x + 215, y + 26), "..." if waiting else self.key_text(action_id), font=self.f["s"],
                   fill=AMBER if waiting else DIM, anchor="lm")
            self.button(d, (x + 460, y, x + 590, y + 52), "Change", lambda a=action_id: self.start_capture(a),
                        on=waiting, enabled=not self.capturing or waiting, font="s")
        fixed = " ".join(name for _, name, _ in pk.FIXED)
        d.text((40, H - 54), f"Also always on, for voice tools and button boxes: {fixed}", font=self.f["x"], fill=FAINT)
        self.button(d, (W - 270, H - 72, W - 40, H - 20), "Reset all keys", self.reset_keys, enabled=not self.capturing, font="s")

    def draw_help(self, d, _state):
        y = 198
        for heading, text in HELP:
            d.text((40, y), heading, font=self.f["h"], fill=WHITE)
            y += 40
            for line in wrap(d, text, self.f["s"], W - 80):
                d.text((40, y), line, font=self.f["s"], fill=DIM)
                y += 30
            y += 8

    def offline(self, d):
        d.text((40, 220), "The headset is not connected.", font=self.f["h"], fill=AMBER)
        for i, line in enumerate(("Check that the headset is on and streaming from this PC.",
                                  "This page will update by itself when it connects.")):
            d.text((40, 276 + i * 40), line, font=self.f["t"], fill=DIM)

    def render(self):
        """Returns the page as an image, and sets self.hits for click()."""
        from PIL import Image, ImageDraw
        state = self.get_state()
        self.hits = []
        img = Image.new("RGBA", (W, H), BG + (255,))
        d = ImageDraw.Draw(img)
        self.header(d, state)
        getattr(self, "draw_" + self.page)(d, state)
        return img

    def click(self, x, y):
        """Returns True if something was hit. y counts from the top."""
        for (x0, y0, x1, y1), action in self.hits:
            if x0 <= x <= x1 and y0 <= y <= y1:
                action()
                return True
        return False

    def thumbnail(self):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (256, 256), BG + (255,))
        d = ImageDraw.Draw(img)
        d.ellipse((48, 48, 208, 208), outline=ACCENT, width=18)
        return img

    # ---------- changing a key ----------
    def start_capture(self, action_id):
        if self.capturing == action_id:
            self.note = "Key not changed."
            self.cancel_capture()
            return
        self.note = self.keys.note = ""
        self.held = None
        self.capturing = action_id
        self.capture_until = time.monotonic() + CAPTURE_SECONDS
        self.keys.pause()
        for vk in pk.CAPTURABLE + [pk.ESCAPE]:   # forget anything pressed before now
            ctypes.windll.user32.GetAsyncKeyState(vk)

    def cancel_capture(self):
        if self.capturing:
            self.capturing = None
            self.keys.resume()

    def reset_keys(self):
        self.note = "All keys are back to their defaults."
        self.keys.note = ""
        self.keys.reset()

    def poll_capture(self):
        """Called often while waiting for a key. Returns True if something changed on the page."""
        if not self.capturing:
            return False
        user32 = ctypes.windll.user32
        if time.monotonic() > self.capture_until or user32.GetAsyncKeyState(pk.ESCAPE) & 1:
            self.note = "Key not changed."
            self.cancel_capture()
            return True
        if self.held:   # a refused key still down must not be refused again and again
            if user32.GetAsyncKeyState(self.held) & 0x8000:
                return False
            self.held = None
        for vk in pk.CAPTURABLE:
            if user32.GetAsyncKeyState(vk) & 0x8001:
                mods = 0
                for mod, held in ((pk.MOD_CONTROL, (0x11,)), (pk.MOD_ALT, (0x12,)), (pk.MOD_SHIFT, (0x10,)), (pk.MOD_WIN, (0x5B, 0x5C))):
                    if any(user32.GetAsyncKeyState(k) & 0x8000 for k in held):
                        mods |= mod
                self.finish_capture(mods, vk)
                return True
        return False

    def finish_capture(self, mods, vk):
        action_id = self.capturing
        problem = pk.problem_with(self.keys.bindings, action_id, mods, vk)
        if problem:
            # Keep waiting, so the next press can succeed without tapping Change again.
            self.note = problem
            self.held = vk
            self.capture_until = time.monotonic() + CAPTURE_SECONDS
            return
        self.capturing = None
        if self.keys.bindings[action_id] == (mods, vk):
            self.note = f"{pk.key_name(mods, vk)} is already its key."
            self.keys.resume()
            return
        self.note = f"Set to {pk.key_name(mods, vk)}."
        self.keys.change(action_id, mods, vk)

    def key_input(self, data):
        """One key from the VR keyboard. Returns True for Enter."""
        for code in data.split(b"\0")[0]:
            if code in (0x0A, 0x0D):
                return True
            if code in (0x08, 0x7F):
                self.typed = self.typed[:-1]
            elif 0x20 <= code <= 0x7E and len(self.typed) < NAME_MAX:
                self.typed += chr(code)
        return False

    def finish_rename(self, text):
        self.keyboard_open = False
        slot, self.naming = self.naming, None
        name = clean_name(text)
        if slot and name:
            self.send(f"rename {slot} {name}")


def steamvr_running():
    """vrmonitor.exe, not vrserver.exe: MSFS can start vrserver for a moment, and an overlay init would then bring up
    the whole SteamVR UI. isHmdPresent does not start the runtime."""
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq vrmonitor.exe", "/NH"], capture_output=True, text=True,
                         creationflags=NO_WINDOW, check=False).stdout
    if "vrmonitor.exe" not in out:
        return False
    import openvr
    return bool(openvr.isHmdPresent())


class Files:
    """Saves images in turn to two names, so SteamVR never reads one half written."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="cockpitportal_")
        self.flip = 0

    def save(self, img, name):
        self.flip ^= 1
        path = os.path.join(self.dir, f"{name}{self.flip}.png")
        img.save(path)
        return path


def keyboard_text(overlay):
    """The VR keyboard's text. pyopenvr 2.12's getKeyboardText passes its buffer as the length too, and raises."""
    buffer = ctypes.create_string_buffer(256)
    overlay.function_table.getKeyboardText(buffer, len(buffer))
    return buffer.value.decode("utf-8", "replace")


def set_icon(overlay, thumb, img, log):
    """Pixels straight to SteamVR. Every dashboard icon showed a question mark on the Frame with the file route."""
    data = img.tobytes()
    try:
        overlay.setOverlayRaw(thumb, (ctypes.c_char * len(data)).from_buffer_copy(data), img.width, img.height, 4)
        log("panel: icon set from pixels")
    except Exception as exc:  # noqa: BLE001
        log(f"panel: icon from pixels failed: {exc!r}")


def session(panel, get_version, log, stop):
    import openvr
    openvr.init(openvr.VRApplication_Overlay)
    log("panel: attached to SteamVR")
    files = Files()
    overlay = openvr.IVROverlay()
    dash, thumb = overlay.createDashboardOverlay("cockpitportal.panel", "Cockpit Portal")
    overlay.setOverlayWidthInMeters(dash, OVERLAY_METRES)
    overlay.setOverlayInputMethod(dash, openvr.VROverlayInputMethod_Mouse)
    scale = openvr.HmdVector2_t()
    scale.v[0], scale.v[1] = W, H
    overlay.setOverlayMouseScale(dash, scale)
    set_icon(overlay, thumb, panel.thumbnail(), log)
    drawn = None
    loops = 0
    try:
        while True:
            loops += 1
            if stop.is_set() or (loops % 50 == 0 and not steamvr_running()):
                return
            event = openvr.VREvent_t()
            while overlay.pollNextOverlayEvent(dash, event)[0]:
                if event.eventType == openvr.VREvent_Quit:
                    return
                if event.eventType == openvr.VREvent_MouseButtonDown:
                    # OpenVR overlay mouse coordinates count up from the bottom.
                    panel.click(event.data.mouse.x, H - event.data.mouse.y)
                    drawn = None
                elif event.eventType == openvr.VREvent_KeyboardDone:
                    panel.finish_rename(panel.typed or keyboard_text(overlay))
                elif event.eventType == openvr.VREvent_KeyboardClosed:
                    panel.keyboard_open = False
                elif event.eventType == openvr.VREvent_KeyboardCharInput and panel.naming:
                    if panel.key_input(bytes(event.data.keyboard.cNewInput)):
                        # On this keyboard getKeyboardText returns only the last key, here a line break.
                        panel.finish_rename(panel.typed or keyboard_text(overlay))
                        overlay.hideKeyboard()
            if panel.ask_name:
                slot, name = panel.ask_name
                panel.ask_name = None
                try:
                    overlay.showKeyboardForOverlay(dash, openvr.k_EGamepadTextInputModeNormal,
                                                   # Minimal sends each key as it is pressed, which is the only way to see
                                                   # Enter. It starts empty, because typed text is counted from nothing.
                                                   openvr.k_EGamepadTextInputLineModeSingleLine, openvr.KeyboardFlag_Minimal,
                                                   "Name this portal, then tap Enter", NAME_MAX, "", 0)
                    panel.naming, panel.typed, panel.keyboard_open = slot, "", True
                except Exception as exc:  # noqa: BLE001
                    log(f"panel: VR keyboard failed: {exc!r}")
            if overlay.isOverlayVisible(dash):
                if panel.poll_capture():
                    drawn = None
                key = (panel.page, get_version(), panel.keys.version, panel.keys.note, panel.note, panel.capturing,
                       panel.naming, panel.typed, panel.keyboard_open)
                if key != drawn:
                    overlay.setOverlayFromFile(dash, files.save(panel.render(), "panel"))
                    drawn = key
            else:
                panel.cancel_capture()
            time.sleep(CAPTURE_FRAME_S if panel.capturing else FRAME_S)
    finally:
        panel.cancel_capture()
        openvr.shutdown()
        log("panel: detached from SteamVR")


def run(send, get_state, get_version, keys, log, stop):
    """Never lets a panel problem reach the hotkeys."""
    try:
        import openvr  # noqa: F401
        panel = Panel(send, get_state, keys)
    except Exception as exc:  # noqa: BLE001 - hotkeys still work without the panel
        log(f"panel: not available: {exc!r}")
        return
    last_error = None
    while not stop.is_set():
        try:
            if steamvr_running():
                session(panel, get_version, log, stop)
            last_error = None
        except Exception as exc:  # noqa: BLE001 - try again next time SteamVR is up
            # Waiting for a headset repeats this every few seconds, so say it once.
            if repr(exc) != last_error:
                log(f"panel: {exc!r}")
                last_error = repr(exc)
        stop.wait(5)


class PreviewKeys:
    version = 0
    note = ""
    bindings = pk.defaults()

    def pause(self):
        pass

    def resume(self):
        pass


def preview(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    slots = ["avionics", "center", "up", "down"]
    labels = {"avionics": "Avionics", "center": "Center", "up": "Radio and autopilot", "down": "Down"}
    states = {"closed": {"connected": True, "on": False, "active": "avionics", "slots": slots, "labels": labels, "unsaved": []},
              "open": {"connected": True, "on": True, "active": "center", "slots": slots, "labels": labels, "unsaved": ["center"]},
              "offline": {"connected": False}}
    for state_name, state in states.items():
        panel = Panel(lambda action: None, lambda s=state: s, PreviewKeys())
        for page, _ in PAGES:
            panel.page = page
            panel.render().convert("RGB").save(os.path.join(out_dir, f"{state_name}-{page}.png"))
    panel = Panel(lambda action: None, lambda s=states["open"]: s, PreviewKeys())
    panel.page, panel.capturing = "hotkeys", "open center"
    panel.render().convert("RGB").save(os.path.join(out_dir, "capturing-hotkeys.png"))
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "preview":
        sys.exit(preview(sys.argv[2]))
    print(__doc__)
    sys.exit(2)
