#!/usr/bin/env python3
"""The work behind the installer, with no windows: reach the headset, set it up, and set up this PC.

The headset password goes to Windows' own ssh once, to add this PC's key, through a small helper mode of this program
(SSH_ASKPASS). It is never written to a file or a log.
"""
import ctypes
import ctypes.wintypes as wt
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time

import cockpit_portal as cp
import portal_keys as pk

VERSION = "0.1.1"
APP_NAME = "Cockpit Portal"
USER = "steamos"
DEFAULT_NAME = "frame.local"
KEY_NAME = "id_ed25519_cockpit_portal"
REMOTE_DIR = "~/cockpit-portal"
ASKPASS_ENV = "COCKPIT_PORTAL_SECRET"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CockpitPortal"
NO_WINDOW = subprocess.CREATE_NO_WINDOW
SETUP_LOG = os.path.join(pk.DATA_DIR, "setup.log")
SSH_TIMEOUT_S = 8
COMMAND_TIMEOUT_S = 60
INSTALL_TIMEOUT_S = 900       # building the layer takes a few minutes at most
RESTART_WAIT_S = 90
QUIT_WAIT_S = 8


NOT_A_FRAME = "That address answered, but it does not look like a Steam Frame, so nothing was installed on it."


class SetupError(Exception):
    """Carries a message written for the person running the installer."""


def log(msg):
    os.makedirs(pk.DATA_DIR, exist_ok=True)
    with open(SETUP_LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def clean_address(text):
    """The address as a host name or IP, or None. It goes on an ssh command line, so nothing else may get through."""
    text = text.strip()
    if text.lower().startswith(USER + "@"):
        text = text[len(USER) + 1:]
    return text if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:\-]*", text) else None


def find_headset(name=DEFAULT_NAME):
    """The headset's IP from the name it announces on the network, or None."""
    try:
        return socket.getaddrinfo(name, 22, socket.AF_INET)[0][4][0]
    except OSError:
        return None


def explain_ssh_failure(stderr):
    """What an ssh error means, in words for the installer."""
    if "Permission denied" in stderr:
        return "The headset refused that password. Check it, or set it again under Developer > Set User Password on the headset."
    if "Host key verification failed" in stderr or "IDENTIFICATION HAS CHANGED" in stderr:
        return ("This PC remembers a different headset. If you changed or reset your headset, run this in PowerShell and "
                f"try again: ssh-keygen -R {cp.HOST_KEY_ALIAS}")
    if "Connection refused" in stderr:
        return "The headset answered but is not accepting logins. Is Developer Mode turned on?"
    if "Could not resolve" in stderr:
        return "That address was not found. Check it and try again."
    if "timed out" in stderr or "No route" in stderr or "unreachable" in stderr:
        return "Could not reach that address. Check that the headset is on and on the same network as this PC."
    return "Could not connect: " + (stderr.strip().splitlines() or ["no details"])[-1]


class Headset:
    """Runs commands on the headset through Windows' ssh."""

    def __init__(self, address, identity):
        self.address, self.identity = address, identity

    def ssh(self, password_login=False):
        command = ["ssh", "-T", "-o", f"ConnectTimeout={SSH_TIMEOUT_S}", "-o", f"HostKeyAlias={cp.HOST_KEY_ALIAS}",
                   "-o", "StrictHostKeyChecking=accept-new"]
        if password_login:
            command += ["-o", "PubkeyAuthentication=no", "-o", "PreferredAuthentications=password,keyboard-interactive",
                        "-o", "NumberOfPasswordPrompts=1"]
        else:
            command += ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-i", os.path.expanduser(self.identity)]
        return command + [f"{USER}@{self.address}"]

    def run(self, remote, data=None, timeout=COMMAND_TIMEOUT_S):
        """Returns (exit code, stdout, stderr)."""
        try:
            done = subprocess.run(self.ssh() + [remote], input=data, capture_output=True, timeout=timeout,
                                  creationflags=NO_WINDOW, check=False)
        except subprocess.TimeoutExpired:
            return 255, "", "ssh timed out"
        return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")

    def key_works(self):
        return self.run("true")[0] == 0

    def add_key(self, public_key, password):
        """Log in once with the password to add this PC's key. The password goes only to ssh, through askpass_env."""
        # Checked here first, so this PC's key is never left on some other machine.
        remote = ('test -x /opt/steamvr/bin/linuxarm64/vrcmd || exit 42; umask 077; mkdir -p ~/.ssh; read -r key; touch ~/.ssh/authorized_keys; '
                  'grep -qxF "$key" ~/.ssh/authorized_keys || echo "$key" >> ~/.ssh/authorized_keys')
        try:
            done = subprocess.run(self.ssh(password_login=True) + [remote], input=(public_key.strip() + "\n").encode("ascii"),
                                  capture_output=True, timeout=COMMAND_TIMEOUT_S, env=askpass_env(password),
                                  creationflags=NO_WINDOW, check=False)
        except subprocess.TimeoutExpired:
            raise SetupError("The headset did not answer in time. Try again.") from None
        if done.returncode == 42:
            raise SetupError(NOT_A_FRAME)
        if done.returncode != 0:
            stderr = done.stderr.decode("utf-8", "replace")
            log(f"adding the key failed: {stderr.strip()}")
            raise SetupError(explain_ssh_failure(stderr))
        if not self.key_works():
            raise SetupError("The key was added, but logging in with it did not work.")

    def is_steam_frame(self):
        code, out, _ = self.run("uname -m; test -x /opt/steamvr/bin/linuxarm64/vrcmd && echo steamvr")
        return code == 0 and "aarch64" in out and "steamvr" in out

    def upload(self, folder):
        """Copy the headset scripts over. Saved positions are in other files, so they stay."""
        code, _, err = self.run(f"mkdir -p {REMOTE_DIR} && tar -xzf - -C {REMOTE_DIR}", data=scripts_tar(folder))
        if code != 0:
            log(f"upload failed: {err.strip()}")
            raise SetupError("Could not copy Cockpit Portal to the headset. The details are in the setup log.")

    def run_setup(self, on_event):
        """Run setup.sh install. on_event gets each @@ line as a list of words after it."""
        command = self.ssh() + [f"bash {REMOTE_DIR}/setup.sh install"]
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=NO_WINDOW)
        failed = None
        started = time.monotonic()
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            log(line)
            if line.startswith("@@ "):
                words = line[3:].split(" ", 2)
                if words[0] == "FAIL":
                    failed = words[2] if len(words) > 2 else "Setup failed on the headset."
                on_event(words)
            if time.monotonic() - started > INSTALL_TIMEOUT_S:
                proc.kill()
                raise SetupError("Setup on the headset took too long. The details are in the setup log.")
        if proc.wait() != 0:
            raise SetupError(failed or "The connection to the headset dropped during setup. Try again: it is safe to repeat.")

    def addresses(self):
        """(ip -4 output, hostname), for the addresses the app should try."""
        code, out, _ = self.run("hostname; ip -4 -o addr")
        if code != 0 or not out.strip():
            return "", ""
        name, _, rest = out.partition("\n")
        return rest, name.strip()

    def restart_steamvr(self):
        """Restart it, then wait for the compositor to come back with the layer loaded. False if it did not in time."""
        self.run("nohup sh -c 'sleep 1; systemctl --user restart steamvr' >/dev/null 2>&1 &")
        time.sleep(5)
        deadline = time.monotonic() + RESTART_WAIT_S
        while time.monotonic() < deadline:
            code, out, _ = self.run('pid=$(pgrep -o vrcompositor) && test -f "/tmp/mrchroma-$pid.log" && echo loaded', timeout=15)
            if code == 0 and "loaded" in out:
                return True
            time.sleep(3)
        return False

    def uninstall(self):
        return self.run(f"bash {REMOTE_DIR}/setup.sh uninstall", timeout=COMMAND_TIMEOUT_S)


def askpass_env(password):
    env = dict(os.environ)
    env.update({"SSH_ASKPASS": sys.executable, "SSH_ASKPASS_REQUIRE": "force", ASKPASS_ENV: password})
    return env


def answer_askpass():
    """ssh runs this program to get the password. Windowed builds have no sys.stdout, so write to the handle directly."""
    if "assword" not in " ".join(sys.argv[1:]):
        return 1
    data = (os.environ[ASKPASS_ENV] + "\n").encode("utf-8")
    kernel32 = ctypes.windll.kernel32
    kernel32.GetStdHandle.restype = wt.HANDLE
    kernel32.WriteFile.argtypes = [wt.HANDLE, ctypes.c_char_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    written = wt.DWORD()
    return 0 if kernel32.WriteFile(kernel32.GetStdHandle(-11), data, len(data), ctypes.byref(written), None) else 1


def scripts_tar(folder):
    """The headset scripts as a .tar.gz. Executable, and unchanged byte for byte."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and name.endswith((".sh", ".py")):
                info = tar.gettarinfo(path, arcname=name)
                info.mode, info.uid, info.gid, info.uname, info.gname = 0o755, 0, 0, "", ""
                with open(path, "rb") as fh:
                    tar.addfile(info, fh)
    return buffer.getvalue()


def hosts_from(ip_output, hostname, used_address):
    """The addresses to try, best first: streaming link, home Wi-Fi, the announced name, and whatever reached it today."""
    found = dict(re.findall(r"^\d*:?\s*(\S+)\s+(?:inet\s+)?(\d+\.\d+\.\d+\.\d+)", ip_output, flags=re.M))
    addresses = [found[nic] for nic in ("wlanap", "wlan0") if nic in found]
    if hostname:
        addresses.append(f"{hostname}.local")
    if used_address not in addresses:
        addresses.append(used_address)
    return [f"{USER}@{address}" for address in addresses]


def bundled(*parts):
    """A file that travels with the program, whether built into the exe or run from the source folder."""
    root = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    return os.path.join(root, *parts)


class Paths:
    """Where things go on the PC. Per-user folders only, so no administrator rights are needed."""

    def __init__(self, local=None, roaming=None, home=None):
        local = local or os.environ["LOCALAPPDATA"]
        roaming = roaming or os.environ["APPDATA"]
        home = home or os.path.expanduser("~")
        self.data = os.path.join(local, "CockpitPortal")
        self.config = os.path.join(self.data, "config.json")
        self.folder = os.path.join(local, "Programs", "CockpitPortal")
        self.exe = os.path.join(self.folder, "CockpitPortal.exe")
        programs = os.path.join(roaming, "Microsoft", "Windows", "Start Menu", "Programs")
        self.start_menu = os.path.join(programs, f"{APP_NAME}.lnk")
        self.startup = os.path.join(programs, "Startup", f"{APP_NAME}.lnk")
        self.key = os.path.join(home, ".ssh", KEY_NAME)


def ensure_key(paths):
    """This PC's key for the headset, made if needed. Returns the public half."""
    public = paths.key + ".pub"
    if not os.path.exists(paths.key):
        os.makedirs(os.path.dirname(paths.key), exist_ok=True)
        try:
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "cockpit-portal", "-f", paths.key],
                           stdin=subprocess.DEVNULL, capture_output=True, creationflags=NO_WINDOW, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SetupError("Could not make a key with ssh-keygen. Is Windows' OpenSSH Client installed? "
                             "It is under Settings > System > Optional features.") from exc
    with open(public, encoding="ascii") as fh:
        return fh.read().strip()


def read_config(paths):
    try:
        with open(paths.config, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def write_config(paths, hosts, identity):
    config = read_config(paths)
    config.update({"hosts": hosts, "identity": identity, "remote_dir": REMOTE_DIR})
    os.makedirs(paths.data, exist_ok=True)
    with open(paths.config + ".new", "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=1)
    os.replace(paths.config + ".new", paths.config)


def stop_running_app():
    """Ask a running copy to close, and wait until it has."""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenMutexW.restype = wt.HANDLE
    kernel32.SetEvent(cp.quit_event())
    deadline = time.monotonic() + QUIT_WAIT_S
    while time.monotonic() < deadline:
        mutex = kernel32.OpenMutexW(0x00100000, False, cp.MUTEX_NAME)   # SYNCHRONIZE
        if not mutex:
            return True
        kernel32.CloseHandle(wt.HANDLE(mutex))
        time.sleep(0.2)
    return False


def make_shortcut(link, target):
    os.makedirs(os.path.dirname(link), exist_ok=True)
    env = dict(os.environ, CP_LINK=link, CP_TARGET=target)
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:CP_LINK); $s.TargetPath = $env:CP_TARGET; "
              "$s.WorkingDirectory = Split-Path $env:CP_TARGET; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env, capture_output=True,
                   creationflags=NO_WINDOW, check=True)


def register_uninstaller(paths):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        for name, value in (("DisplayName", APP_NAME), ("DisplayVersion", VERSION), ("Publisher", "Cockpit Portal contributors"),
                            ("InstallLocation", paths.folder), ("DisplayIcon", paths.exe),
                            ("UninstallString", f'"{paths.exe}" uninstall')):
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        for name in ("NoModify", "NoRepair"):
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 1)


def install_program(paths, source_exe):
    """Copy this program into place, retrying while Windows lets go of a copy that has just closed."""
    os.makedirs(paths.folder, exist_ok=True)
    if os.path.abspath(source_exe).lower() == os.path.abspath(paths.exe).lower():
        return
    for attempt in range(20):
        try:
            shutil.copy2(source_exe, paths.exe)
            return
        except OSError:
            if attempt == 19:
                raise
            time.sleep(0.5)


def start_app(paths):
    """Start the installed copy on its own. The reset tells it not to share this running exe's unpacked files."""
    env = {k: v for k, v in os.environ.items() if k != ASKPASS_ENV}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen([paths.exe], cwd=paths.folder, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def identity_in_use(paths, address):
    """A key already set up for this headset, so a repeat install needs no password. Returns its path, or None."""
    saved = read_config(paths).get("identity")
    for identity in filter(None, (saved, paths.key)):
        if os.path.exists(os.path.expanduser(identity)) and Headset(address, identity).key_works():
            return identity
    return None


def remove_from_pc(paths):
    """Everything on the PC except the running exe. Only a key this project made is deleted."""
    import winreg
    identity = read_config(paths).get("identity")
    for link in (paths.startup, paths.start_menu):
        if os.path.exists(link):
            os.remove(link)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    if identity and os.path.abspath(os.path.expanduser(identity)) == os.path.abspath(paths.key):
        for path in (paths.key, paths.key + ".pub"):
            if os.path.exists(path):
                os.remove(path)
    subprocess.run(["ssh-keygen", "-R", cp.HOST_KEY_ALIAS], capture_output=True, creationflags=NO_WINDOW, check=False)
    shutil.rmtree(paths.data, ignore_errors=True)


def remove_program_after_exit(paths):
    """A running exe cannot delete itself, so a short-lived command does it once this one has closed."""
    subprocess.Popen(f'cmd /c ping -n 4 127.0.0.1 >nul & rmdir /s /q "{paths.folder}"', cwd=os.environ.get("TEMP", "C:\\"),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                     creationflags=NO_WINDOW)


def remove_our_key_from_headset(headset, paths):
    """Last step on the headset, because it ends this PC's access. Only a key this project made."""
    if os.path.abspath(os.path.expanduser(headset.identity)) != os.path.abspath(paths.key):
        return
    with open(paths.key + ".pub", encoding="ascii") as fh:
        public = fh.read().strip()
    headset.run('read -r key; f=~/.ssh/authorized_keys; grep -vxF "$key" "$f" > "$f.new"; chmod 600 "$f.new"; mv "$f.new" "$f"',
                data=(public + "\n").encode("ascii"))
