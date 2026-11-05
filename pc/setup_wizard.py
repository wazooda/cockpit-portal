#!/usr/bin/env python3
"""The Windows setup wizard and uninstaller. The work itself is in setup_core.py."""
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import setup_core as core

PAD = 20
WIDTH = 640
STEPS = (("connect", "Connect to the headset"),
         ("check", "Check this SteamVR version is supported"),
         ("layer", "Build and install the compositor layer"),
         ("setting", "Turn on the passthrough setting"),
         ("restart", "Restart SteamVR on the headset, if needed"),
         ("pc", "Install on this PC and start with Windows"))
MARK = {"wait": "○", "busy": "…", "ok": "✓", "fail": "✗", "skip": "–"}
COLOUR = {"wait": "#888888", "busy": "#1f6feb", "ok": "#1a7f37", "fail": "#cf222e", "skip": "#888888"}

WELCOME = """Cockpit Portal opens a window in your VR view that shows the real room, so you can see your hands and controls while flying or driving.

This installer adds your PC's key to the headset, builds an open-source compositor layer (mr-chroma-frame) on the headset, turns on a hidden SteamVR setting, and sets Cockpit Portal to start with Windows.

This is an unofficial tool, not supported by Valve. A SteamVR update can stop it working. It comes with no warranty."""

BEFORE = """Do these on your Steam Frame now. The installer cannot do them for you, and it cannot continue without them.

    1.  Open Steam Settings > System and turn on Developer Mode.

    2.  In the new Developer section, choose Set User Password, and pick a password. If you set one before and do not remember it, set a new one.

    3.  Leave the headset on, on the same network as this PC."""

DONE = """Cockpit Portal is running and will start with Windows.

Try it:

    1.  Start streaming to your headset, and open a game.
    2.  Press Ctrl+Alt+1. A window onto the real room should open.
    3.  If it looks double, open the SteamVR dashboard and choose Cockpit Portal > Adjust. Tap the arrows under "Looks double?" until you see one circle, then tap Save. Eyes and fit differ, so most people need to do this once for each position.

Everything else, including renaming positions and changing keys, is on that same dashboard page. To remove it, use Installed apps in Windows Settings."""


class Wizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{core.APP_NAME} Setup")
        self.geometry(f"{WIDTH}x540")
        self.resizable(False, False)
        self.paths = core.Paths()
        self.events = queue.Queue()
        self.headset = None
        self.hosts = []
        self.finished = False
        self.body = ttk.Frame(self, padding=PAD)
        self.body.pack(fill="both", expand=True)
        self.buttons = ttk.Frame(self, padding=(PAD, 0, PAD, PAD))
        self.buttons.pack(fill="x", side="bottom")
        self.back = ttk.Button(self.buttons, text="Cancel", command=self.destroy)
        self.back.pack(side="left")
        self.next = ttk.Button(self.buttons, text="Next")
        self.next.pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.page_welcome()
        self.after(100, self.pump)

    # ---------- running work off the window's thread ----------
    def pump(self):
        while True:
            try:
                action = self.events.get_nowait()
            except queue.Empty:
                break
            action()
        self.after(100, self.pump)

    def later(self, function, *args):
        """Run on the window's thread, from a worker thread."""
        self.events.put(lambda: function(*args))

    def on_close(self):
        if self.next["state"] == "disabled" and self.back["state"] == "disabled":
            return    # setup is running on the headset, and stopping half way would help nobody
        self.destroy()

    def clear(self, title):
        for child in self.body.winfo_children():
            child.destroy()
        ttk.Label(self.body, text=title, font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 12))

    def text(self, words, **pack):
        label = ttk.Label(self.body, text=words, wraplength=WIDTH - 2 * PAD, justify="left", font=("Segoe UI", 10))
        label.pack(anchor="w", **pack)
        return label

    # ---------- welcome ----------
    def page_welcome(self):
        self.clear(f"Install {core.APP_NAME}")
        self.text(WELCOME)
        self.next.configure(text="Next", command=self.page_before)

    # ---------- what only the person can do ----------
    def page_before(self):
        self.clear("Before you start")
        self.text(BEFORE, pady=(0, 18))
        self.gates = [tk.BooleanVar(self), tk.BooleanVar(self)]
        for gate, words in zip(self.gates, ("Developer Mode is turned on", "I have set a user password, and I know what it is")):
            ttk.Checkbutton(self.body, text=words, variable=gate, command=self.check_gates).pack(anchor="w", pady=3)
        self.next.configure(text="Next", command=self.page_connect, state="disabled")

    def check_gates(self):
        self.next.configure(state="normal" if all(gate.get() for gate in self.gates) else "disabled")

    # ---------- find the headset, and the password if one is needed ----------
    def page_connect(self):
        self.clear("Connect to your headset")
        self.text("Looking for it on your network. If it is not found, type the IP address from the headset's Wi-Fi settings.")
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=12)
        ttk.Label(row, text="Headset address").pack(side="left")
        self.address = tk.StringVar()
        self.address_box = ttk.Entry(row, textvariable=self.address, width=30)
        self.address_box.pack(side="left", padx=8)
        self.password = tk.StringVar()
        self.password_row = ttk.Frame(self.body)
        ttk.Label(self.password_row, text="Headset password").pack(side="left")
        self.password_box = ttk.Entry(self.password_row, textvariable=self.password, show="•", width=30)
        self.password_box.pack(side="left", padx=8)
        self.password_note = ttk.Label(self.body, wraplength=WIDTH - 2 * PAD, justify="left", font=("Segoe UI", 9),
                                       text="The password you set on the headset. It is used once, to add this PC's key to the "
                                            "headset, and is never saved. Forgotten it? Set a new one under Set User "
                                            "Password on the headset, then type it here.")
        self.status = self.text("", pady=8)
        self.next.configure(text="Next", command=self.connect)
        self.next.configure(state="disabled")
        self.status.configure(text="Searching...")
        threading.Thread(target=self.search, daemon=True).start()

    def search(self):
        self.later(self.search_done, core.find_headset())

    def search_done(self, found):
        if not self.address_box.winfo_exists():
            return
        if found and not self.address.get():
            self.address.set(found)
            self.status.configure(text=f"Found a headset at {found}.")
        elif not found:
            self.status.configure(text="Not found automatically. Type the address above.")
        self.next.configure(state="normal")

    def connect(self):
        address = core.clean_address(self.address.get())
        if not address:
            self.status.configure(text="That does not look like an address, such as 192.168.1.50.")
            return
        self.next.configure(state="disabled")
        self.status.configure(text="Connecting...")
        threading.Thread(target=self.try_connect, args=(address, self.password.get()), daemon=True).start()

    def try_connect(self, address, password):
        try:
            public = core.ensure_key(self.paths)
            identity = core.identity_in_use(self.paths, address)
            if not identity and not password:
                self.later(self.ask_password)
                return
            headset = core.Headset(address, identity or self.paths.key)
            if not identity:
                headset.add_key(public, password)
            if not headset.is_steam_frame():
                raise core.SetupError(core.NOT_A_FRAME)
        except core.SetupError as exc:
            self.later(self.connect_failed, str(exc))
            return
        self.later(self.page_install, headset)

    def ask_password(self):
        self.password_row.pack(fill="x", pady=(0, 4), before=self.status)
        self.password_note.pack(anchor="w", before=self.status)
        self.password_box.focus_set()
        self.status.configure(text="")
        self.next.configure(state="normal")

    def connect_failed(self, message):
        self.status.configure(text=message)
        self.password.set("")
        self.next.configure(state="normal")

    # ---------- the checklist ----------
    def page_install(self, headset):
        self.headset = headset
        self.password.set("")
        self.clear("Setting up")
        self.marks = {}
        for step, words in STEPS:
            row = ttk.Frame(self.body)
            row.pack(fill="x", pady=3)
            mark = tk.Label(row, width=2, font=("Segoe UI", 11, "bold"))
            mark.pack(side="left")
            ttk.Label(row, text=words, font=("Segoe UI", 10)).pack(side="left")
            self.marks[step] = mark
            self.set_mark(step, "wait")
        self.set_mark("connect", "ok")
        self.status = self.text("", pady=14)
        self.next.configure(state="disabled", text="Next")
        self.back.configure(state="disabled")
        threading.Thread(target=self.install_headset, daemon=True).start()

    def set_mark(self, step, state):
        self.marks[step].configure(text=MARK[state], fg=COLOUR[state])

    def install_headset(self):
        self.need_restart = False

        def on_event(words):
            kind, step = words[0], words[1] if len(words) > 1 else ""
            if kind == "RESTART":
                self.need_restart = True
            elif step in self.marks:
                self.later(self.set_mark, step, {"STEP": "busy", "OK": "ok", "FAIL": "fail"}.get(kind, "wait"))

        try:
            # Close any running copy first, so nothing is using the scripts while they are replaced.
            core.stop_running_app()
            self.headset.upload(core.bundled("headset"))
            self.headset.run_setup(on_event)
        except core.SetupError as exc:
            self.later(self.install_failed, str(exc))
            return
        self.later(self.after_headset)

    def after_headset(self):
        if self.need_restart:
            self.set_mark("restart", "busy")
            self.status.configure(text="SteamVR on the headset has to restart once to load the layer. If you are streaming, "
                                       "the stream will drop for about 15 seconds. Click Restart when you are ready.")
            self.next.configure(text="Restart", state="normal", command=self.restart)
        else:
            self.set_mark("restart", "skip")
            threading.Thread(target=self.install_pc, daemon=True).start()

    def restart(self):
        self.next.configure(state="disabled")
        self.status.configure(text="Restarting SteamVR on the headset...")

        def work():
            loaded = self.headset.restart_steamvr()
            self.later(self.restart_done, loaded)
        threading.Thread(target=work, daemon=True).start()

    def restart_done(self, loaded):
        self.set_mark("restart", "ok" if loaded else "skip")
        self.restart_note = "" if loaded else ("SteamVR did not confirm the restart. If the portal does not open, "
                                               "restart the headset once.")
        threading.Thread(target=self.install_pc, daemon=True).start()

    def install_pc(self):
        self.later(self.set_mark, "pc", "busy")
        self.later(self.status.configure, {"text": ""})
        try:
            ip_output, name = self.headset.addresses()
            hosts = core.hosts_from(ip_output, name, self.headset.address)
            core.write_config(self.paths, hosts, self.headset.identity)
            core.log(f"hosts: {hosts}")
            core.install_program(self.paths, sys.executable)
            core.make_shortcut(self.paths.startup, self.paths.exe)
            core.make_shortcut(self.paths.start_menu, self.paths.exe)
            core.register_uninstaller(self.paths)
            core.start_app(self.paths)
        except Exception as exc:  # noqa: BLE001 - any failure here should reach the person, in the window
            core.log(f"PC setup failed: {exc!r}")
            self.later(self.install_failed, f"Could not finish on this PC: {exc}")
            return
        self.later(self.set_mark, "pc", "ok")
        self.later(self.page_done)

    def install_failed(self, message):
        for step, mark in self.marks.items():
            if mark["text"] == MARK["busy"]:
                self.set_mark(step, "fail")
        self.status.configure(text=f"{message}\n\nIt is safe to run this installer again. Log: {core.SETUP_LOG}")
        # A repeat install that failed should not leave the hotkeys off.
        if os.path.exists(self.paths.exe):
            core.start_app(self.paths)
        self.next.configure(text="Close", state="normal", command=self.destroy)

    # ---------- done ----------
    def page_done(self):
        self.clear("You're set")
        self.text(DONE)
        note = getattr(self, "restart_note", "")
        if note:
            self.text(note, pady=10)
        self.back.pack_forget()
        self.next.configure(text="Finish", state="normal", command=self.destroy)


def setup():
    Wizard().mainloop()
    return 0


def uninstall():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)    # Windows Settings starts this, and the messages must not open behind it
    if not messagebox.askyesno(f"Remove {core.APP_NAME}", "Remove Cockpit Portal from this PC and from your headset?\n\n"
                                                          "Turn the headset on first, so it can be removed from there too. "
                                                          "Your saved positions and hotkeys will be deleted."):
        return 0
    paths = core.Paths()
    core.stop_running_app()
    config = core.read_config(paths)
    identity = config.get("identity") or paths.key
    message = "Cockpit Portal has been removed from this PC and your headset."
    for host in config.get("hosts", []):
        headset = core.Headset(host.split("@")[-1], identity)
        if headset.key_works():
            code, out, err = headset.uninstall()
            core.log(f"headset uninstall: {code} {out} {err}")
            if code != 0:
                message = "Removed from this PC. The headset reported a problem. Its files are in ~/cockpit-portal."
            core.remove_our_key_from_headset(headset, paths)
            break
    else:
        message = ("Removed from this PC. The headset could not be reached, so its files are still there. "
                   "The README explains how to remove them by hand.")
    core.remove_from_pc(paths)
    messagebox.showinfo(f"Remove {core.APP_NAME}", message)
    root.destroy()
    # Last, because the program cannot delete itself while it is waiting on that message.
    core.remove_program_after_exit(paths)
    return 0


if __name__ == "__main__":
    sys.exit(uninstall() if sys.argv[1:] == ["uninstall"] else setup())
