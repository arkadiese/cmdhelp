import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from tests.helpers import kb  # noqa: F401
import cmdhelp.kb as kbmod
from cmdhelp.kb import KB, parse_man_text

GNU = """\
NAME
       demo - a demo tool

OPTIONS
       -x, --extract
              Extract files from an archive. More text here.

       -f, --file=ARCHIVE
              Use archive file ARCHIVE.

       -h --help
              Print help and exit.

       --debug N
              Set debug level.

       -v     Verbose mode; print more.
"""

BSD = """\
     -a      Include directory entries whose names begin with a dot.
     -l      List in long format.
"""


class ParseManTextTest(unittest.TestCase):
    def by(self, flags):
        return {f["names"][0]: f for f in flags}

    def test_gnu_layout(self):
        f = self.by(parse_man_text(GNU))
        self.assertEqual(f["-x"]["names"], ["-x", "--extract"])
        self.assertEqual(f["-x"]["normal"], "Extract files from an archive.")
        self.assertEqual(f["-f"]["arg"], "ARCHIVE")
        self.assertEqual(f["-h"]["names"], ["-h", "--help"])     # space-separated aliases
        self.assertEqual(f["--debug"]["arg"], "N")
        self.assertIn("Verbose", f["-v"]["normal"])               # description on the same line

    def test_bsd_layout(self):
        f = self.by(parse_man_text(BSD))
        self.assertIn("-a", f)
        self.assertIn("long format", f["-l"]["normal"])

    def test_malformed_input_never_raises(self):
        for junk in (None, "", "   \n\n", "-", "--\n--\n", "\x00\x01\x02", "-" * 10000, GNU[:37], "\t-x\t\n" * 500):
            self.assertIsInstance(parse_man_text(junk), list)

    def test_caps_output(self):
        big = "".join("       --opt%d\n              Thing %d.\n\n" % (i, i) for i in range(1000))
        self.assertLessEqual(len(parse_man_text(big)), 300)


class ManCacheTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.page = os.path.join(self.dir, "demo.1")
        with open(self.page, "w") as fh:
            fh.write("x")
        self.cache = os.path.join(self.dir, "cache")
        self.p_dir = mock.patch.object(kbmod, "CACHE_DIR", self.cache)
        self.p_dir.start()
        self.reads = 0

        def fake_read(name):
            self.reads += 1
            return GNU
        self.p_read = mock.patch.object(kbmod, "read_man", side_effect=fake_read)
        self.p_path = mock.patch.object(kbmod, "man_path", return_value=self.page)
        self.p_read.start()
        self.p_path.start()

    def tearDown(self):
        mock.patch.stopall()
        shutil.rmtree(self.dir, ignore_errors=True)

    def cache_json(self):
        with open(os.path.join(self.cache, kbmod.MAN_CACHE_FILE)) as fh:
            return json.load(fh)

    def test_parse_once_then_cached_across_processes(self):
        KB().man_flags("tar")
        KB().man_flags("tar")                      # fresh KB = new process
        self.assertEqual(self.reads, 1)
        self.assertEqual(self.cache_json()["v"], kbmod.PARSER_VERSION)

    def test_invalidated_when_man_page_changes(self):
        KB().man_flags("tar")
        t = time.time() + 100
        os.utime(self.page, (t, t))
        KB().man_flags("tar")
        self.assertEqual(self.reads, 2)

    def test_invalidated_when_parser_version_changes(self):
        KB().man_flags("tar")
        with mock.patch.object(kbmod, "PARSER_VERSION", kbmod.PARSER_VERSION + 1):
            KB().man_flags("tar")
        self.assertEqual(self.reads, 2)

    def test_corrupt_cache_is_ignored(self):
        os.makedirs(self.cache)
        with open(os.path.join(self.cache, kbmod.MAN_CACHE_FILE), "w") as fh:
            fh.write("{not json")
        self.assertTrue(KB().man_flags("tar"))
        self.assertIn("tar", self.cache_json()["cmds"])     # rewritten cleanly

    def test_atomic_write_leaves_no_temp_files(self):
        k = KB()
        for n in ("tar", "grep", "awk"):
            k.man_flags(n)
        left = [f for f in os.listdir(self.cache) if f.startswith(".man_flags.")]
        self.assertEqual(left, [])

    def test_cached_mode_never_parses(self):
        k = KB()
        e = k.get("tar", man="cached")
        self.assertEqual(self.reads, 0)
        self.assertNotIn("man_flags", e)

    def test_enrich_async_is_non_blocking_and_calls_back(self):
        gate = []

        def slow_read(name):
            time.sleep(0.3)
            gate.append(name)
            return GNU
        self.p_read.stop()
        with mock.patch.object(kbmod, "read_man", side_effect=slow_read):
            k = KB()
            called = []
            t0 = time.time()
            th = k.enrich_async("tar", lambda: called.append(1))
            self.assertLess(time.time() - t0, 0.1)            # returned immediately
            th.join(5)
            self.assertEqual(called, [1])
            self.assertIn("--extract", [n for f in k.get("tar", man="cached")["flags"] for n in f["names"]])
            self.assertIsNone(k.enrich_async("tar"))         # already validated: no second thread

    def test_no_man_page_installed(self):
        self.p_path.stop()
        with mock.patch.object(kbmod, "man_path", return_value=None):
            self.assertEqual(KB().man_flags("tar"), [])
            self.assertEqual(self.reads, 0)


if __name__ == "__main__":
    unittest.main()
