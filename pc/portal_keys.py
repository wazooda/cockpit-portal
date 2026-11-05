#!/usr/bin/env python3
"""The portal's hotkeys: which key does what, and the rules for changing one.

Each action has one key the user can change, saved in keys.json in the app's data folder. F13-F19 and F22 also
always work: they have no modifiers, which suits voice tools and button boxes, because a sim reading keys through Raw
Input sees a modifier even when this program takes the hotkey.
"""
import json
import os

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
CTRL_ALT = MOD_CONTROL | MOD_ALT
MOVE_PX = 16      # about 0.9 degrees
ALIGN_PX = 8      # about 0.45 degrees
SIZE_PERCENT = 10
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "CockpitPortal")
SAVED = os.path.join(DATA_DIR, "keys.json")


def adjust(mx=0, my=0, ax=0, ay=0, percent=0):
    """(move x, move y, align x, align y, radius %). A larger x moves a window left in view, and a larger y moves it up."""
    return (mx, my, ax, ay, percent)


# id, label, action, default modifiers, default key. Shift is not used: alone, it is the MSFS VR recenter key.
# A label of None means the name of the position, which the user can change.
ACTIONS = [
    ("toggle", "On / off", "toggle", CTRL_ALT, 0x30),
    ("open avionics", None, "open avionics", CTRL_ALT, 0x31),
    ("open center", None, "open center", CTRL_ALT, 0x32),
    ("open up", None, "open up", CTRL_ALT, 0x33),
    ("open down", None, "open down", CTRL_ALT, 0x34),
    ("save", "Save", "save", CTRL_ALT, 0x53),
    ("bigger", "Bigger", adjust(percent=SIZE_PERCENT), CTRL_ALT, 0x21),
    ("smaller", "Smaller", adjust(percent=-SIZE_PERCENT), CTRL_ALT, 0x22),
    ("move up", "Move up", adjust(my=MOVE_PX), CTRL_ALT, 0x26),
    ("move down", "Move down", adjust(my=-MOVE_PX), CTRL_ALT, 0x28),
    ("move left", "Move left", adjust(mx=MOVE_PX), CTRL_ALT, 0x25),
    ("move right", "Move right", adjust(mx=-MOVE_PX), CTRL_ALT, 0x27),
    ("align up", "Fix double: up", adjust(ay=ALIGN_PX), CTRL_ALT, 0x49),
    ("align down", "Fix double: down", adjust(ay=-ALIGN_PX), CTRL_ALT, 0x4B),
    ("align left", "Fix double: left", adjust(ax=ALIGN_PX), CTRL_ALT, 0x4A),
    ("align right", "Fix double: right", adjust(ax=-ALIGN_PX), CTRL_ALT, 0x4C),
]
ACTION_OF = {action_id: action for action_id, _, action, _, _ in ACTIONS}

# Key, name, action. Always on, and not changeable.
FIXED = [
    (0x85, "F22", "toggle"),
    (0x7C, "F13", "open avionics"),
    (0x7D, "F14", "open center"),
    (0x7E, "F15", "open up"),
    (0x7F, "F16", "open down"),
    (0x80, "F17", adjust(percent=SIZE_PERCENT)),
    (0x81, "F18", adjust(percent=-SIZE_PERCENT)),
    (0x82, "F19", "save"),
]

NAMES = {0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x20: "Space", 0x21: "Page Up", 0x22: "Page Down",
         0x23: "End", 0x24: "Home", 0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down", 0x2D: "Insert", 0x2E: "Delete",
         0x6A: "Num *", 0x6B: "Num +", 0x6D: "Num -", 0x6E: "Num .", 0x6F: "Num /", 0xBA: ";", 0xBB: "=", 0xBC: ",",
         0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'"}
NAMES.update({vk: chr(vk) for vk in range(0x30, 0x3A)})
NAMES.update({vk: chr(vk) for vk in range(0x41, 0x5B)})
NAMES.update({0x60 + n: f"Num {n}" for n in range(10)})
NAMES.update({0x70 + n: f"F{n + 1}" for n in range(24)})
ESCAPE = 0x1B
CAPTURABLE = list(NAMES)    # modifiers and Esc are not in NAMES, so pressing one alone never counts as choosing a key
# Keys nobody needs for typing can be used with no Ctrl or Alt: F keys, the numpad, Pause and the navigation block.
WORKS_ALONE = set(range(0x70, 0x88)) | set(range(0x60, 0x6A)) | {0x6A, 0x6B, 0x6D, 0x6E, 0x6F} | {0x13, 0x21, 0x22, 0x23, 0x24, 0x2D, 0x2E}


def key_name(mods, vk):
    parts = [name for bit, name in ((MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift"), (MOD_WIN, "Win")) if mods & bit]
    return "+".join(parts + [NAMES.get(vk, f"Key {vk:#x}")])


def defaults():
    return {action_id: (mods, vk) for action_id, _, _, mods, vk in ACTIONS}


def load(path=SAVED):
    bindings = defaults()
    try:
        with open(path, encoding="utf-8") as fh:
            saved = json.load(fh)
    except (OSError, ValueError):
        return bindings
    for action_id, pair in saved.items():
        if action_id in bindings and isinstance(pair, list) and len(pair) == 2 and all(isinstance(v, int) for v in pair):
            bindings[action_id] = (pair[0], pair[1])
    return bindings


def save(bindings, path=SAVED):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".new", "w", encoding="utf-8") as fh:
        json.dump({action_id: list(pair) for action_id, pair in bindings.items()}, fh, indent=1)
    os.replace(path + ".new", path)


def label_of(action_id):
    return next(label for candidate, label, _, _, _ in ACTIONS if candidate == action_id)


def problem_with(bindings, action_id, mods, vk):
    """Why this key cannot be used, in words for the panel, or None if it can."""
    name = key_name(mods, vk)
    if mods & MOD_SHIFT:
        return f"{name} uses Shift, which re-centres VR in MSFS. Choose another."
    if mods & MOD_WIN:
        return f"{name} uses the Windows key, which Windows keeps for itself. Choose another."
    if not mods & CTRL_ALT and vk not in WORKS_ALONE:
        return f"{name} alone would stop typing it anywhere. Hold Ctrl or Alt with it, or use an F or numpad key."
    for fixed_vk, fixed_name, _ in FIXED:
        if not mods and vk == fixed_vk:
            return f"{fixed_name} is kept for voice tools. Choose another."
    for other, pair in bindings.items():
        if other != action_id and pair == (mods, vk):
            return f"{name} is already used by {label_of(other) or other.replace('open ', '').title()}."
    return None


def hint(names):
    """["Ctrl+Alt+Up", "Ctrl+Alt+Down"] -> "Ctrl+Alt + Up / Down". Without a shared start, the names as they are."""
    heads = {name.rsplit("+", 1)[0] for name in names if "+" in name}
    if len(heads) == 1 and all("+" in name for name in names):
        return f"{heads.pop()} + " + " / ".join(name.rsplit("+", 1)[1] for name in names)
    return " / ".join(names)
