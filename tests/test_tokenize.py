import unittest

from tests.helpers import kb  # noqa: F401
from cmdhelp.explain import tokenize, split_segments


class TokenizeTest(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(tokenize("tar -xzvf a.tgz"), ["tar", "-xzvf", "a.tgz"])

    def test_quotes_are_kept_together(self):
        self.assertEqual(tokenize("grep 'a b' \"c d\" f"), ["grep", "a b", "c d", "f"])

    def test_unterminated_quote_does_not_raise(self):
        # happens on every keystroke while typing
        self.assertEqual(tokenize("grep 'abc"), ["grep", "'abc"])

    def test_pipes_and_lists_are_separate_tokens(self):
        self.assertEqual(tokenize("a|b&&c;d||e"), ["a", "|", "b", "&&", "c", ";", "d", "||", "e"])

    def test_stderr_redirect_glued(self):
        self.assertEqual(tokenize("cmd 2>&1 | grep x"), ["cmd", "2>&1", "|", "grep", "x"])
        self.assertEqual(tokenize("cmd 2>/dev/null"), ["cmd", "2>", "/dev/null"])
        self.assertEqual(tokenize("cmd >> out"), ["cmd", ">>", "out"])

    def test_find_exec_escaped_semicolon_is_not_a_separator(self):
        toks = tokenize("find . -name x -exec rm {} \\;")
        self.assertEqual(toks[-1], "\\;")
        self.assertEqual(len(split_segments(toks)), 1)

    def test_split_segments(self):
        segs = split_segments(tokenize("ps aux | grep x && echo ok"))
        cmds = [s[0][0] for s in segs if s[0]]
        seps = [s[1] for s in segs if s[1]]
        self.assertEqual(cmds, ["ps", "grep", "echo"])
        self.assertEqual(seps, ["|", "&&"])

    def test_empty(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("   "), [])


if __name__ == "__main__":
    unittest.main()
