import os
import unittest
from collections import Counter

from tests.helpers import kb
from cmdhelp.kb import KB, merge_man_flags


class KBTest(unittest.TestCase):
    def test_loads_and_sizes(self):
        k = kb()
        self.assertGreater(len(k.names), 5000)
        self.assertGreater(len(k.rank), 500)
        for name in ("tar", "gzip", "awk", "grep", "tcpdump", "iptables", "dnf"):
            e = k.get(name, man="none")
            self.assertEqual(e["source"].split("+")[0], "curated", name)

    def test_every_curated_entry_has_all_three_levels(self):
        k = kb()
        for name in k.names:
            e = k.get(name, man="none")
            if not e["source"].startswith("curated"):
                continue
            for lvl in ("min", "normal", "verbose"):
                self.assertTrue(e["summary"][lvl], (name, lvl))
            for f in e["flags"]:
                self.assertTrue(f["names"], name)
                for lvl in ("min", "normal", "verbose"):
                    self.assertIn(lvl, f, (name, f["names"]))
            for c in e["combos"]:
                self.assertTrue(c["cmd"].strip(), name)

    def test_tldr_entry_expansion(self):
        e = kb().get("zstd", man="none")
        self.assertEqual(e["source"], "tldr")
        self.assertTrue(e["combos"])
        self.assertTrue(all(c["cmd"] for c in e["combos"]))

    def test_tldr_arg_inference(self):
        f = [f for f in kb().get("git-commit", man="none")["flags"] if "-m" in f["names"]]
        self.assertTrue(f and f[0]["arg"])

    def test_unknown(self):
        self.assertIsNone(kb().get("nope-nope"))
        self.assertEqual(kb().summary("nope-nope", "normal"), "")

    def test_summary_modes(self):
        k = kb()
        self.assertLess(len(k.summary("tar", "min")), len(k.summary("tar", "normal")))

    def test_ranking_default_follows_top_list(self):
        k = KB()
        k.history = Counter()
        r = k.ranked_names("")
        self.assertLess(r.index("ls"), r.index("tcpdump"))

    def test_ranking_history_wins(self):
        k = KB()
        k.history = Counter({"tcpdump": 50})
        self.assertEqual(k.ranked_names("t")[0], "tcpdump")

    def test_history_parsing(self):
        home = os.environ["HOME"]
        with open(os.path.join(home, ".bash_history"), "w") as fh:
            fh.write("sudo tcpdump -nn\nLANG=C sort f | uniq -c\nls; ls && ls\n")
        with open(os.path.join(home, ".zsh_history"), "w") as fh:
            fh.write(": 1700000000:0;rsync -a a b\n")
        try:
            k = KB()
            self.assertEqual(k.history["tcpdump"], 1)       # sudo skipped
            self.assertEqual(k.history["sort"], 1)          # VAR=x skipped
            self.assertEqual(k.history["uniq"], 1)          # after a pipe
            self.assertEqual(k.history["ls"], 3)
            self.assertEqual(k.history["rsync"], 1)         # zsh extended format
        finally:
            os.unlink(os.path.join(home, ".bash_history"))
            os.unlink(os.path.join(home, ".zsh_history"))


class MergeTest(unittest.TestCase):
    BASE = {"source": "tldr", "flags": [{"names": ["-x"], "arg": None, "min": "x", "normal": "Used for: x.", "verbose": "v"}]}
    MAN = [{"names": ["-x", "--extract"], "arg": "FILE", "min": "ex", "normal": "Extract things.", "verbose": "Long."},
           {"names": ["-q"], "arg": None, "min": "q", "normal": "Quiet.", "verbose": "Quiet."}]

    def test_merge_adds_and_upgrades_without_mutating_base(self):
        m = merge_man_flags(self.BASE, self.MAN)
        names = [f["names"][0] for f in m["flags"]]
        self.assertEqual(names, ["-x", "-q"])
        self.assertEqual(m["flags"][0]["normal"], "Extract things.")
        self.assertEqual(m["flags"][0]["arg"], "FILE")
        self.assertEqual(self.BASE["flags"][0]["normal"], "Used for: x.")   # untouched

    def test_curated_text_is_never_overwritten(self):
        base = dict(self.BASE, source="curated")
        m = merge_man_flags(base, self.MAN)
        self.assertEqual(m["flags"][0]["normal"], "Used for: x.")


if __name__ == "__main__":
    unittest.main()
