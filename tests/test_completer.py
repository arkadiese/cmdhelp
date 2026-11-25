import unittest
from unittest import mock

from tests.helpers import kb
from cmdhelp.__main__ import _import_pt

HAVE_PT = _import_pt()
if HAVE_PT:
    from prompt_toolkit.document import Document
    from prompt_toolkit.completion import CompleteEvent
    from cmdhelp.tui import HelperCompleter, State
import cmdhelp.kb as kbmod


@unittest.skipUnless(HAVE_PT, "prompt_toolkit not importable")
class CompleterTest(unittest.TestCase):
    def setUp(self):
        # typing must never touch man(1)
        self.p = [mock.patch.object(kbmod, "read_man", side_effect=AssertionError("man rendered on typing path")),
                  mock.patch.object(kbmod.KB, "enrich_async", return_value=None)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def comps(self, text, mode="normal"):
        c = HelperCompleter(kb(), State(mode))
        return list(c.get_completions(Document(text, len(text)), CompleteEvent()))

    def apply(self, text, comp):
        cut = len(text) + comp.start_position
        return text[:cut] + comp.text

    def test_command_names(self):
        texts = [c.text for c in self.comps("tcp")]
        self.assertIn("tcpdump", texts)

    def test_intent_search(self):
        texts = [c.text for c in self.comps("compress")]
        self.assertTrue({"gzip", "xz", "zstd", "bzip2"} & set(texts), texts[:20])

    def test_flags_with_meta(self):
        cs = self.comps("tar -")
        texts = [c.text.strip() for c in cs]
        self.assertIn("-x", texts)
        self.assertTrue(all(c.display_meta for c in cs))

    def test_bundle_learns_next_letter(self):
        cs = self.comps("tar -xz")
        bundles = [c.text for c in cs if c.text.startswith("-xz") and len(c.text) == 4]
        self.assertTrue(bundles[0] in ("-xzv", "-xzf"), bundles[:5])

    def test_combo_keyword_filter_replaces_whole_line(self):
        text = "tar exclude"
        cs = [c for c in self.comps(text) if "combo" in (c.style or "")]
        self.assertTrue(cs)
        self.assertIn("--exclude", self.apply(text, cs[0]))
        self.assertTrue(self.apply(text, cs[0]).startswith("tar "))

    def test_combo_in_pipeline_keeps_left_side(self):
        text = "cat access.log | grep top"
        cs = [c for c in self.comps(text) if "combo" in (c.style or "")]
        self.assertTrue(cs)
        out = self.apply(text, cs[0])
        self.assertTrue(out.startswith("cat access.log | grep"), out)

    def test_subcommands(self):
        texts = [c.text for c in self.comps("systemctl ")]
        self.assertIn("restart", texts)

    def test_modes_change_meta_length(self):
        mn = self.comps("tar -", "min")[0].display_meta
        nm = self.comps("tar -", "normal")[0].display_meta
        self.assertLessEqual(len(str(mn)), len(str(nm)))

    def test_sudo_prefix(self):
        texts = [c.text.strip() for c in self.comps("sudo tcpdump -")]
        self.assertIn("-i", texts)

    def test_unknown_command_falls_back_to_paths(self):
        self.comps("nope-nope ./")   # must not raise


if __name__ == "__main__":
    unittest.main()
