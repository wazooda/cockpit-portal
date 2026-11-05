#!/usr/bin/env python3
"""Named portal positions. portal.sh still does the building, applying and confirming.

Run as `slots.py serve` over one ssh connection. Each input line is one command, and the reply
ends with `RC <code>`:
    ping | status
    toggle                     close the open window, or open the last one used
    open NAME                  open a slot. If it is already open, close it
    close
    adjust MX MY AX AY PCT     change the open window: MX,MY move both eyes and AX,AY move the right
                               eye only (the alignment), in pixels. PCT changes the radius, in percent
    save                       keep the open slot's current values across restarts
    revert                     go back to the open slot's saved values
    rename SLOT NAME           change the name shown for a slot. Its keys keep working
    state                      one line of JSON for the dashboard panel

A larger x moves a window left in view, and a larger y moves it up. Adjustments last until the
connection closes unless saved.
"""
import copy
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.path.join(HERE, "portal.sh")
SAVED = os.path.join(HERE, "slots.json")
LAST = os.path.join(HERE, "slots.last")
PARAMS = os.path.join(HERE, "portal.spv.params")
EYE_WIDTH = 2160
HEIGHT = 2160
MIN_RADIUS = 60
MAX_RADIUS = 600

# Starting points measured on one headset. Eyes and fit differ, so expect to adjust and save your own.
DEFAULTS = {
    "avionics": {"lx": 728.2, "ly": 504.1, "rx": 3588.4, "ry": 519.6, "radius": 228.9, "soft": 30},
    "center": {"lx": 754.6, "ly": 752.5, "rx": 3563.3, "ry": 775.7, "radius": 228.9, "soft": 30},
    "up": {"lx": 763.8, "ly": 942.8, "rx": 3371.4, "ry": 921.5, "radius": 228.9, "soft": 30},
    "down": {"lx": 739.8, "ly": 628.5, "rx": 3573.5, "ry": 643.9, "radius": 228.9, "soft": 30},
}


def clamp(value, low, high):
    return max(low, min(high, value))


def portal(*args):
    done = subprocess.run([PORTAL, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, universal_newlines=True, check=False)
    lines = done.stdout.strip().splitlines()
    return done.returncode, lines[-1] if lines else ""


def read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def write_atomic(path, text):
    with open(path + ".new", "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(path + ".new", path)


class Slots:
    def __init__(self):
        self.saved = copy.deepcopy(DEFAULTS)
        if os.path.exists(SAVED):
            with open(SAVED, encoding="utf-8") as fh:
                self.saved.update(json.load(fh))
        self.working = copy.deepcopy(self.saved)
        last = read_text(LAST)
        self.last = last if last in self.working else "avionics"
        self.supported = portal("check")[0] == 0
        # An override is matched by file name, so an open portal must not carry over to a new SteamVR's shader.
        if not self.supported and self.is_on():
            portal("off")

    def is_on(self):
        return portal("status")[1] == "on"

    def show(self, name):
        s = self.working[name]
        args = ["--centers", f"{s['lx']:.1f},{s['ly']:.1f},{s['rx']:.1f},{s['ry']:.1f}",
                "--radius", f"{s['radius']:.1f}", "--soft", f"{s['soft']:g}"]
        if read_text(PARAMS) != " ".join(args):
            code, text = portal("build", *args)
            if code != 0:
                return 1, f"on {name} FAILED build: {text}"
        code, text = portal("on")
        self.last = name
        write_atomic(LAST, name)
        return code, text.replace("on", f"on {name}", 1)

    def toggle(self):
        return portal("off") if self.is_on() else self.show(self.last)

    def open(self, name):
        if name not in self.working:
            return 1, f"open FAILED unknown slot {name}"
        if name == self.last and self.is_on():
            return portal("off")
        return self.show(name)

    def adjust(self, mx, my, ax, ay, percent):
        if not self.is_on():
            return 1, "adjust FAILED no window open"
        s = self.working[self.last]
        s["lx"] = clamp(s["lx"] + mx, 0, EYE_WIDTH)
        s["ly"] = clamp(s["ly"] + my, 0, HEIGHT)
        s["rx"] = clamp(s["rx"] + mx + ax, EYE_WIDTH, 2 * EYE_WIDTH)
        s["ry"] = clamp(s["ry"] + my + ay, 0, HEIGHT)
        s["radius"] = clamp(s["radius"] * (1 + percent / 100), MIN_RADIUS, MAX_RADIUS)
        return self.show(self.last)

    def save(self):
        if not self.is_on():
            return 1, "save FAILED no window open"
        self.saved[self.last] = copy.deepcopy(self.working[self.last])
        write_atomic(SAVED, json.dumps(self.saved, indent=1))
        return 0, f"saved {self.last}"

    def revert(self):
        self.working[self.last] = copy.deepcopy(self.saved[self.last])
        return self.show(self.last) if self.is_on() else (0, f"reverted {self.last}")

    def rename(self, slot, label):
        if slot not in self.working:
            return 1, f"rename FAILED unknown slot {slot}"
        self.saved[slot]["label"] = label
        self.working[slot]["label"] = label
        write_atomic(SAVED, json.dumps(self.saved, indent=1))
        return 0, f"renamed {slot}"

    def state(self):
        unsaved = [name for name in self.working if self.working[name] != self.saved[name]]
        labels = {name: slot.get("label", name.title()) for name, slot in self.working.items()}
        return 0, json.dumps({"on": self.is_on(), "active": self.last, "slots": list(self.working), "labels": labels,
                              "unsaved": unsaved, "supported": self.supported})

    def status(self):
        return 0, f"{'on' if self.is_on() else 'off'} {self.last} {json.dumps(self.working[self.last])}"

    def run(self, line):
        parts = line.split()
        if not parts:
            return 2, "empty command"
        cmd, args = parts[0], parts[1:]
        if cmd == "ping":
            return 0, ""
        if cmd == "status":
            return self.status()
        if cmd == "toggle":
            return self.toggle()
        if cmd == "close":
            return portal("off")
        if cmd == "save":
            return self.save()
        if cmd == "revert":
            return self.revert()
        if cmd == "state":
            return self.state()
        if cmd == "rename" and len(args) >= 2:
            return self.rename(args[0], " ".join(args[1:]))
        if cmd == "open" and len(args) == 1:
            return self.open(args[0])
        if cmd == "adjust" and len(args) == 5:
            try:
                return self.adjust(*[float(a) for a in args])
            except ValueError:
                return 2, "adjust needs five numbers"
        return 2, f"unknown command: {line}"


def main():
    if sys.argv[1:] != ["serve"]:
        print(__doc__)
        return 2
    slots = Slots()
    for line in sys.stdin:
        code, text = slots.run(line.strip())
        print(text, flush=True)
        print(f"RC {code}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
