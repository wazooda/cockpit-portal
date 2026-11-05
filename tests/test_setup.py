"""Tests of the installer's logic that need no headset."""
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pc"))

import setup_core as core  # noqa: E402

IP_OUTPUT = """1: lo    inet 127.0.0.1/8 scope host lo
2: wlan0    inet 192.168.1.50/24 brd 192.168.1.255 scope global wlan0
3: usb0    inet 10.9.9.9/29 scope global usb0
4: wlanap    inet 10.42.0.1/24 scope global wlanap
"""


class Addresses(unittest.TestCase):
    def test_accepted(self):
        self.assertEqual(core.clean_address(" 192.168.1.50 "), "192.168.1.50")
        self.assertEqual(core.clean_address("steamos@frame.local"), "frame.local")

    def test_refused(self):
        for bad in ("", "-oProxyCommand=calc", "a b", "x;calc", "root@frame", "$(calc)"):
            self.assertIsNone(core.clean_address(bad), bad)

    def test_link_comes_first_then_wifi_then_name(self):
        self.assertEqual(core.hosts_from(IP_OUTPUT, "frame", "192.168.1.50"),
                         ["steamos@10.42.0.1", "steamos@192.168.1.50", "steamos@frame.local"])

    def test_address_that_worked_is_kept(self):
        self.assertEqual(core.hosts_from(IP_OUTPUT, "frame", "10.9.9.9")[-1], "steamos@10.9.9.9")

    def test_no_link_network(self):
        text = IP_OUTPUT.replace("wlanap", "other")
        self.assertEqual(core.hosts_from(text, "frame", "frame.local"), ["steamos@192.168.1.50", "steamos@frame.local"])


class Errors(unittest.TestCase):
    def test_messages(self):
        for stderr, word in (("steamos@x: Permission denied (publickey,password).", "password"),
                             ("Host key verification failed.", "ssh-keygen -R"),
                             ("connect to host x port 22: Connection refused", "Developer Mode"),
                             ("ssh: Could not resolve hostname x", "not found"),
                             ("connect to host x port 22: Connection timed out", "Could not reach"),
                             ("something odd\n", "something odd"), ("", "no details")):
            self.assertIn(word, core.explain_ssh_failure(stderr))


class Upload(unittest.TestCase):
    def test_only_scripts_go_and_are_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("a.sh", "b.py", "notes.txt", "portal.spv"):
                with open(os.path.join(folder, name), "wb") as fh:
                    fh.write(b"x\n")
            with tarfile.open(fileobj=io.BytesIO(core.scripts_tar(folder))) as tar:
                self.assertEqual(sorted(tar.getnames()), ["a.sh", "b.py"])
                self.assertTrue(all(member.mode == 0o755 for member in tar.getmembers()))

    def test_the_real_scripts_keep_unix_line_ends(self):
        with tarfile.open(fileobj=io.BytesIO(core.scripts_tar(core.bundled("headset")))) as tar:
            self.assertIn("setup.sh", tar.getnames())
            for member in tar.getmembers():
                self.assertNotIn(b"\r", tar.extractfile(member).read(), member.name)


class Config(unittest.TestCase):
    def test_keeps_other_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = core.Paths(local=folder, roaming=folder, home=folder)
            os.makedirs(paths.data)
            with open(paths.config, "w", encoding="utf-8") as fh:
                json.dump({"hosts": ["old"], "other": 1}, fh)
            core.write_config(paths, ["steamos@new"], "key")
            saved = core.read_config(paths)
            self.assertEqual((saved["hosts"], saved["identity"], saved["other"]), (["steamos@new"], "key", 1))

    def test_password_is_only_in_the_environment_of_ssh(self):
        env = core.askpass_env("secret")
        self.assertEqual(env[core.ASKPASS_ENV], "secret")
        self.assertEqual(env["SSH_ASKPASS_REQUIRE"], "force")
        self.assertNotIn(core.ASKPASS_ENV, os.environ)


if __name__ == "__main__":
    unittest.main()
