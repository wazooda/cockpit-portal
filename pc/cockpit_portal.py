#!/usr/bin/env python3
"""Cockpit Portal for Windows: the hotkeys and the SteamVR dashboard page.

Keys are listed in portal_keys.py and can be changed on the page's Hotkeys tab. It keeps one SSH connection open to
`slots.py serve` on the headset, so a press does not wait for a new connection. Presses run in order, one at a time, and
adjustments that pile up are applied together. The tone says what happened:
    high = on, low = off, two high = saved, three short = failed or unconfirmed.
Adjustments make no tone unless they fail.

Settings: %LOCALAPPDATA%\\CockpitPortal\\config.json (see config.example.json). The log is cockpit_portal.log beside it.

usage: cockpit_portal.py              run. Only one copy runs at a time
       cockpit_portal.py quit         close the running copy cleanly
       cockpit_portal.py once ACTION  run one command once and exit, such as status or "open center"
"""
import ctypes
import ctypes.wintypes as wt
import datetime
import json
import os
import queue
import subprocess
import sys
import threading
import time
import winsound

import portal_keys as pk

CONFIG = os.path.join(pk.DATA_DIR, "config.json")
LOG = os.path.join(pk.DATA_DIR, "cockpit_portal.log")
HOST_KEY_ALIAS = "cockpit-portal-headset"
SSH_CONNECT_S = 4         # each address in the config gets this long
CONNECT_TIMEOUT_S = 10
PING_TIMEOUT_S = 1.5      # a dead link is found here, before anything can change state
REQUEST_TIMEOUT_S = 35    # longer than portal.sh can take: lock 15 + reload 10 + confirm 6
RECONNECT_WAIT_S = 5
QUIT_WAIT_S = 3
WM_QUIT = 0x0012
WM_HOTKEY = 0x0312
WM_APP = 0x8000
WM_KEYS_PAUSE, WM_KEYS_RESUME, WM_KEYS_APPLY = WM_APP + 1, WM_APP + 2, WM_APP + 3
ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Local\\CockpitPortalRunning"
QUIT_EVENT_NAME = "Local\\CockpitPortalQuit"
INFINITE = 0xFFFFFFFF


def windows_tool(name):
    """Windows' own OpenSSH tool. Not whichever comes first on PATH: Git's copies, for example, make keys with
    permissions that Windows' ssh refuses."""
    path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH", name + ".exe")
    return path if os.path.exists(path) else name


def log(msg):
    now = datetime.datetime.now()
    line = f"{now:%Y-%m-%d %H:%M:%S}.{now.microsecond // 1000:03d} {msg}"
    if sys.stdout:
        print(line, flush=True)
    os.makedirs(pk.DATA_DIR, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_config():
    """{"hosts": [...], "identity": path or None, "remote_dir": path}. Hosts are tried in order: the streaming link
    first, then home Wi-Fi, so the page still works when one of them is down."""
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            saved = json.load(fh)
    except (OSError, ValueError):
        saved = {}
    return {"hosts": saved.get("hosts", []), "identity": saved.get("identity"),
            "remote_dir": saved.get("remote_dir", "~/cockpit-portal")}


class LinkError(Exception):
    pass


class Link:
    """One long-lived ssh process. Replies are text lines ending with `RC <code>`."""

    def __init__(self, config):
        self.config = config
        self.proc = None
        self.lines = None
        self.host = None

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def close(self):
        if self.proc is not None:
            try:
                self.proc.kill()
            except OSError:
                pass
        self.proc = None
        self.lines = None

    def connect(self):
        if not self.config["hosts"]:
            raise LinkError(f"no headset address in {CONFIG}")
        problems = []
        for host in self.config["hosts"]:
            try:
                self.connect_to(host)
                self.host = host
                return
            except (LinkError, OSError) as exc:
                problems.append(f"{host}: {exc}")
        raise LinkError("; ".join(problems))

    def connect_to(self, host):
        self.close()
        # One name for the headset's key, whichever address reaches it. Trusted the first time, and refused if it changes.
        command = [windows_tool("ssh"), "-T", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={SSH_CONNECT_S}",
                   "-o", f"HostKeyAlias={HOST_KEY_ALIAS}", "-o", "StrictHostKeyChecking=accept-new",
                   "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2"]
        if self.config["identity"]:
            command += ["-i", os.path.expanduser(self.config["identity"])]
        command += [host, f"python3 -I {self.config['remote_dir']}/slots.py serve"]
        self.proc = subprocess.Popen(
            command,
            # Bytes, not text: text mode on Windows would send CRLF to the headset.
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.lines = queue.Queue()
        threading.Thread(target=self._read, args=(self.proc, self.lines), daemon=True).start()
        self.ping(CONNECT_TIMEOUT_S)

    def ping(self, timeout):
        code, text = self.request("ping", timeout)
        if code != 0:
            self.close()
            raise LinkError(f"bad reply to ping: {text}")

    @staticmethod
    def _read(proc, lines):
        for line in proc.stdout:
            lines.put(line.decode("utf-8", "replace").strip())
        lines.put(None)

    def request(self, command, timeout):
        """Returns (exit code, last text line). Closes the link on any failure."""
        if not self.alive():
            raise LinkError("not connected")
        try:
            self.proc.stdin.write((command + "\n").encode("ascii"))
        except OSError as exc:
            self.close()
            raise LinkError(f"write failed: {exc}")
        deadline = time.monotonic() + timeout
        text = ""
        while True:
            try:
                line = self.lines.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                self.close()
                raise LinkError(f"no reply to {command} in {timeout} s")
            if line is None:
                self.close()
                raise LinkError(f"connection closed during {command}")
            if line.startswith("RC "):
                return int(line[3:]), text
            text = line


def ensure_link(link):
    """Prove the link works. Ping changes nothing, so reconnecting after it is safe."""
    try:
        link.ping(PING_TIMEOUT_S)
    except LinkError:
        link.connect()


def run_action(link, action):
    """Returns (exit code, text). A timed-out command is not retried: it may have applied."""
    try:
        ensure_link(link)
    except (LinkError, OSError) as exc:
        return 1, f"{action} FAILED no connection: {exc}"
    try:
        return link.request(action, REQUEST_TIMEOUT_S)
    except LinkError as exc:
        return 1, f"{action} FAILED {exc}"


def fail_tone():
    for _ in range(3):
        winsound.Beep(300, 90)


def tone(code, text):
    if code != 0:
        fail_tone()
    elif text.startswith(("saved", "renamed")):
        winsound.Beep(1200, 100)
        winsound.Beep(1200, 100)
    elif text.startswith("on"):
        winsound.Beep(1200, 150)
    elif text.startswith("off"):
        winsound.Beep(500, 150)
    elif text.startswith("reverted"):
        winsound.Beep(900, 100)
    else:
        fail_tone()


def take_adjustments(first, presses):
    """Adds up the adjustments waiting at the front of the queue into one command."""
    total = list(first)
    while True:
        try:
            _, action = presses.queue[0]
        except IndexError:
            break
        if not isinstance(action, tuple):
            break
        presses.get_nowait()
        total = [a + b for a, b in zip(total, action)]
    return "adjust " + " ".join(str(v) for v in total)


class Shared:
    """What the dashboard page draws from. Only the worker thread writes it."""

    def __init__(self):
        self.state = {"connected": False}
        self.version = 0

    def set(self, state):
        if state != self.state:
            self.state = state
            self.version += 1


def publish(link, shared):
    """Tell the page the current state. Changes nothing on the headset."""
    try:
        code, text = link.request("state", PING_TIMEOUT_S)
        shared.set(dict(json.loads(text), connected=True) if code == 0 else {"connected": False})
    except (LinkError, OSError, ValueError):
        shared.set({"connected": False})


def worker(presses, shared, config):
    link = Link(config)
    next_try = 0.0
    reported_down = False
    while True:
        try:
            pressed_at, action = presses.get(timeout=1)
        except queue.Empty:
            # Reconnect while idle, so the next press finds the link already open.
            if not link.alive():
                shared.set({"connected": False})
            if not link.alive() and time.monotonic() >= next_try:
                try:
                    link.connect()
                    log(f"connected to {link.host}")
                    reported_down = False
                    publish(link, shared)
                except (LinkError, OSError) as exc:
                    # While the headset is away this repeats for hours, so say it once.
                    if not reported_down:
                        log(f"connect failed, still trying: {exc}")
                        reported_down = True
                    next_try = time.monotonic() + RECONNECT_WAIT_S
            continue
        adjusting = isinstance(action, tuple)
        command = take_adjustments(action, presses) if adjusting else action
        code, text = run_action(link, command)
        log(f"{command}: {text} | press to result {(time.monotonic() - pressed_at) * 1000:.0f} ms")
        if adjusting:
            if code != 0:
                fail_tone()
        else:
            tone(code, text)
        if link.alive():
            publish(link, shared)
        else:
            shared.set({"connected": False})


class HotKeys:
    """Owns the registered keys. RegisterHotKey belongs to the thread that calls it, so the page's calls only post a
    message, and handle() does the work on the main thread."""

    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.thread = ctypes.windll.kernel32.GetCurrentThreadId()
        self.bindings = pk.load()
        self.actions = {}
        self.version = 0
        self.note = ""          # set when Windows refuses a key the page asked for
        self.pending = None

    def register_all(self):
        """Returns the names Windows refused."""
        self.unregister_all()
        refused = []
        hotkey_id = 0
        for vk, name, action in pk.FIXED:
            hotkey_id += 1
            if self.user32.RegisterHotKey(None, hotkey_id, pk.MOD_NOREPEAT, vk):
                self.actions[hotkey_id] = action
            else:
                refused.append(name)
        for action_id, (mods, vk) in self.bindings.items():
            hotkey_id += 1
            action = pk.ACTION_OF[action_id]
            # Adjustments repeat while held. Everything else fires once.
            flags = mods | (0 if isinstance(action, tuple) else pk.MOD_NOREPEAT)
            if self.user32.RegisterHotKey(None, hotkey_id, flags, vk):
                self.actions[hotkey_id] = action
            else:
                refused.append(pk.key_name(mods, vk))
        return refused

    def unregister_all(self):
        for hotkey_id in self.actions:
            self.user32.UnregisterHotKey(None, hotkey_id)
        self.actions = {}

    # ---------- called from the page's thread ----------
    def pause(self):
        self.user32.PostThreadMessageW(self.thread, WM_KEYS_PAUSE, 0, 0)

    def resume(self):
        self.user32.PostThreadMessageW(self.thread, WM_KEYS_RESUME, 0, 0)

    def change(self, action_id, mods, vk):
        self.pending = (action_id, mods, vk)
        self.user32.PostThreadMessageW(self.thread, WM_KEYS_APPLY, 0, 0)

    def reset(self):
        self.pending = "reset"
        self.user32.PostThreadMessageW(self.thread, WM_KEYS_APPLY, 0, 0)

    # ---------- on the main thread ----------
    def handle(self, message):
        if message == WM_KEYS_PAUSE:
            self.unregister_all()
        elif message == WM_KEYS_RESUME:
            self.register_all()
        elif message == WM_KEYS_APPLY:
            self.apply()
        self.version += 1

    def apply(self):
        pending, self.pending = self.pending, None
        before = dict(self.bindings)
        if pending == "reset":
            self.bindings = pk.defaults()
        elif pending:
            action_id, mods, vk = pending
            self.bindings = dict(self.bindings, **{action_id: (mods, vk)})
        refused = self.register_all()
        if pending and pending != "reset" and pk.key_name(pending[1], pending[2]) in refused:
            name = pk.key_name(pending[1], pending[2])
            log(f"could not register {name}: another program holds it")
            self.note = f"Another program holds {name}. Choose another."
            self.bindings = before
            self.register_all()
            return
        pk.save(self.bindings)
        what = "reset to defaults" if pending == "reset" else f"{pending[0]} set to {pk.key_name(pending[1], pending[2])}"
        log(f"keys saved: {what}. Refused: {refused or 'none'}")


def start_panel(presses, shared, keys, stop):
    """The SteamVR dashboard page. A problem with it must never reach the hotkeys."""
    try:
        import portal_panel
        portal_panel.run(lambda action: presses.put((time.monotonic(), action)), lambda: shared.state,
                         lambda: shared.version, keys, log, stop)
    except Exception as exc:  # noqa: BLE001
        log(f"panel: {exc!r}")


def quit_event():
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateEventW.restype = wt.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    kernel32.SetEvent.argtypes = [wt.HANDLE]
    kernel32.ResetEvent.argtypes = [wt.HANDLE]
    return kernel32.CreateEventW(None, True, False, QUIT_EVENT_NAME)


def listen():
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wt.HANDLE
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.GetLastError() == ERROR_ALREADY_EXISTS:
        log("already running")
        return 0
    keys = HotKeys()
    for name in keys.register_all():
        log(f"could not register {name}: another program holds it")
    log(f"listening for {len(keys.actions)} keys")

    presses = queue.Queue()
    shared = Shared()
    stop = threading.Event()
    event = quit_event()
    kernel32.ResetEvent(event)
    main_thread = kernel32.GetCurrentThreadId()

    def wait_for_quit():
        kernel32.WaitForSingleObject(event, INFINITE)
        stop.set()
        user32.PostThreadMessageW(main_thread, WM_QUIT, 0, 0)

    threading.Thread(target=wait_for_quit, daemon=True).start()
    threading.Thread(target=worker, args=(presses, shared, load_config()), daemon=True).start()
    panel = threading.Thread(target=start_panel, args=(presses, shared, keys, stop), daemon=True)
    panel.start()
    msg = wt.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in keys.actions:
                presses.put((time.monotonic(), keys.actions[msg.wParam]))
            elif WM_KEYS_PAUSE <= msg.message <= WM_KEYS_APPLY:
                keys.handle(msg.message)
    finally:
        # Let the page close properly, so the dashboard does not keep a dead button.
        stop.set()
        panel.join(QUIT_WAIT_S)
        keys.unregister_all()
        kernel32.CloseHandle(wt.HANDLE(mutex))
        log("stopped")
    return 0


def main():
    args = sys.argv[1:]
    if args == ["quit"]:
        ctypes.windll.kernel32.SetEvent(quit_event())
        return 0
    if len(args) == 2 and args[0] == "once":
        link = Link(load_config())
        code, text = run_action(link, args[1])
        link.close()
        log(text)
        return code
    if not args:
        return listen()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
