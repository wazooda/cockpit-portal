"""Tests that need no headset. Run from the project folder: python -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pc"))

import portal_keys as pk  # noqa: E402
import portal_panel as pp  # noqa: E402

CA = pk.CTRL_ALT


class FakeKeys:
    def __init__(self):
        self.version = 0
        self.note = ""
        self.bindings = pk.defaults()
        self.calls = []

    def pause(self):
        self.calls.append("pause")

    def resume(self):
        self.calls.append("resume")

    def change(self, *args):
        self.calls.append(args)


STATE = {"connected": True, "on": True, "active": "center", "slots": ["avionics", "center", "up", "down"],
         "labels": {"center": "Center"}, "unsaved": ["center"]}


def panel():
    sent = []
    return pp.Panel(sent.append, lambda: STATE, FakeKeys()), sent


class KeyRules(unittest.TestCase):
    def check(self, mods, vk):
        return pk.problem_with(pk.defaults(), "save", mods, vk)

    def test_refused(self):
        for mods, vk, word in ((0, 0x53, "alone"), (0, 0x20, "alone"), (0, 0x26, "alone"), (CA | pk.MOD_SHIFT, 0x41, "Shift"),
                               (pk.MOD_WIN, 0x41, "Windows"), (0, 0x85, "voice"), (CA, 0x31, "already used")):
            self.assertIn(word, self.check(mods, vk))

    def test_allowed(self):
        for mods, vk in ((CA, 0x41), (pk.MOD_ALT, 0x53), (0, 0x74), (0, 0x65), (0, 0x24), (CA, 0x53)):
            self.assertIsNone(self.check(mods, vk))

    def test_every_action_has_a_different_default(self):
        self.assertEqual(len(set(pk.defaults().values())), len(pk.ACTIONS))

    def test_fixed_keys_are_not_defaults(self):
        for mods, vk in pk.defaults().values():
            self.assertTrue(mods & CA)

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "new", "keys.json")
            bindings = dict(pk.defaults(), save=(CA, 0x41))
            pk.save(bindings, path)
            self.assertEqual(pk.load(path)["save"], (CA, 0x41))

    def test_damaged_file_gives_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "keys.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("not json")
            self.assertEqual(pk.load(path), pk.defaults())

    def test_hint(self):
        self.assertEqual(pk.hint(["Ctrl+Alt+Up", "Ctrl+Alt+Down"]), "Ctrl+Alt + Up / Down")
        self.assertEqual(pk.hint(["F5", "Ctrl+Alt+X"]), "F5 / Ctrl+Alt+X")


class Naming(unittest.TestCase):
    def test_clean_name(self):
        self.assertEqual(pp.clean_name("  GCU\t479\n"), "GCU 479")
        self.assertEqual(pp.clean_name("\n"), "")
        self.assertLessEqual(len(pp.clean_name("x" * 50)), pp.NAME_MAX)
        self.assertEqual(pp.clean_name("Gä CU"), "G CU")

    def test_typing_and_enter(self):
        p, sent = panel()
        p.naming = "avionics"
        for key in (b"G\0\0", b"C\0", b"X\0", b"\x08\0", b"U\0"):
            self.assertFalse(p.key_input(key))
        self.assertEqual(p.typed, "GCU")
        self.assertTrue(p.key_input(b"\n\0"))
        self.assertTrue(p.key_input(b"\r\0"))
        p.finish_rename(p.typed)
        self.assertEqual(sent, ["rename avionics GCU"])

    def test_second_finish_does_nothing(self):
        p, sent = panel()
        p.naming, p.typed = "avionics", "A"
        p.finish_rename(p.typed)
        p.finish_rename("late")
        self.assertEqual(sent, ["rename avionics A"])

    def test_empty_name_is_not_sent(self):
        p, sent = panel()
        p.naming = "avionics"
        p.finish_rename("\n")
        self.assertEqual(sent, [])


class Pages(unittest.TestCase):
    def test_every_page_draws_in_every_state(self):
        for state in (STATE, dict(STATE, on=False, unsaved=[]), {"connected": False}):
            p = pp.Panel(lambda a: None, lambda s=state: s, FakeKeys())
            for page, _ in pp.PAGES:
                p.page = page
                self.assertEqual(p.render().size, (pp.W, pp.H))

    def test_rename_does_not_open_the_portal(self):
        p, sent = panel()
        p.render()
        self.assertTrue(p.click(40 + 590 - 90, 256 + 40))
        self.assertEqual(p.ask_name[0], "avionics")
        self.assertEqual(sent, [])

    def test_card_opens_the_portal(self):
        p, sent = panel()
        p.render()
        p.click(100, 356)
        self.assertEqual(sent, ["open avionics"])

    def test_adjust_is_disabled_when_closed(self):
        state = dict(STATE, on=False)
        sent = []
        p = pp.Panel(sent.append, lambda: state, FakeKeys())
        p.page = "adjust"
        p.render()
        self.assertFalse(p.click(640, 380))
        self.assertEqual(sent, [])

    def test_refused_key_keeps_waiting(self):
        p, _ = panel()
        p.capturing = "save"
        p.finish_capture(0, 0x53)
        self.assertEqual(p.capturing, "save")
        self.assertIn("alone", p.note)
        p.held = None
        p.finish_capture(CA, 0x41)
        self.assertIsNone(p.capturing)
        self.assertEqual(p.keys.calls, [("save", CA, 0x41)])

    def test_same_key_says_so(self):
        p, _ = panel()
        p.capturing = "save"
        p.finish_capture(CA, 0x53)
        self.assertIn("already its key", p.note)
        self.assertEqual(p.keys.calls, ["resume"])


if __name__ == "__main__":
    unittest.main()
