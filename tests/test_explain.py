import unittest

from tests.helpers import kb, rows, kinds, text_for
from cmdhelp.explain import render_text, render_command, explain


class ExplainTest(unittest.TestCase):
    def test_tar_bundle_with_f_argument(self):
        k = kinds("tar -czvf backup.tgz dir/")
        self.assertEqual(k[0], ("tar", "cmd"))
        self.assertIn(("-c", "flag"), k)
        self.assertIn(("-z", "flag"), k)
        self.assertIn(("-v", "flag"), k)
        self.assertIn(("-f", "flag"), k)
        self.assertIn(("backup.tgz", "arg"), k)          # f consumes the next token
        self.assertEqual(text_for("tar -czvf backup.tgz dir/", "backup.tgz"), "value for -f")

    def test_tar_oldstyle_no_dash(self):
        k = kinds("tar xzf a.tgz")
        for letter in ("x", "z", "f"):
            self.assertIn((letter, "flag"), k)

    def test_ps_bsd_style_letters(self):
        # 'u' must be the BSD letter (user format), not -u USER which takes an argument
        self.assertIn("user", text_for("ps aux", "u").lower())
        self.assertNotIn(("aux", "arg"), kinds("ps aux"))

    def test_long_option_with_equals_and_separate_value(self):
        self.assertIn(("--exclude=*.log", "flag"), kinds("tar -czf x.tgz --exclude=*.log d"))
        k = kinds("iptables -A INPUT -p tcp --dport 22 -j ACCEPT")
        self.assertIn(("22", "arg"), k)
        self.assertIn(("ACCEPT", "arg"), k)

    def test_find_exec_consumes_command(self):
        r = rows("find /var/log -name '*.gz' -mtime +30 -exec rm {} \\;")
        toks = [t for t, _, _ in r]
        self.assertIn("rm {}", toks)
        self.assertEqual(toks[-1], "\\;")

    def test_whole_token_single_dash_options(self):
        self.assertIn(("-print0", "flag"), kinds("find . -name x -print0"))
        self.assertIn(("-nn", "flag"), kinds("tcpdump -nn -i any"))

    def test_tldr_bundle_split_into_letters(self):
        k = kinds("ls -ltr /etc")
        self.assertIn(("-l", "flag"), k)
        self.assertIn(("-t", "flag"), k)
        self.assertIn(("-r", "flag"), k)

    def test_sudo_prefix_and_user(self):
        k = kinds("sudo -u oracle sqlplus / as sysdba")
        self.assertEqual(k[0], ("sudo", "prefix"))
        self.assertIn(("oracle", "arg"), k)
        self.assertIn(("sqlplus", "cmd"), k)

    def test_env_assignment_prefix(self):
        self.assertEqual(kinds("LANG=C sort f")[0], ("LANG=C", "env"))

    def test_pipeline_explains_every_command(self):
        k = kinds("ps aux | grep '[n]ginx' && echo ok")
        self.assertIn(("|", "sep"), k)
        self.assertIn(("&&", "sep"), k)
        self.assertIn(("grep", "cmd"), k)
        self.assertIn(("echo", "cmd"), k)

    def test_redirections(self):
        k = kinds("cmd 2>&1 > out.log")
        self.assertIn(("2>&1", "redir"), k)
        self.assertIn((">", "redir"), k)
        self.assertIn(("out.log", "arg"), k)

    def test_subcommand_page_and_parent_fallback(self):
        k = kinds("git commit -am msg")
        self.assertIn(("commit", "sub"), k)
        self.assertIn(("-a", "flag"), k)
        # dnf install has its own page; -y lives on dnf itself
        self.assertIn(("-y", "flag"), kinds("dnf install -y nginx"))

    def test_tcpdump_bpf_keywords(self):
        self.assertIn("BPF", text_for("tcpdump -i eth0 host 10.0.0.1 and port 443", "and"))

    def test_unknown_command_does_not_crash(self):
        k = kinds("definitely-not-a-cmd --foo bar")
        self.assertEqual(k[0], ("definitely-not-a-cmd", "cmd"))

    def test_unknown_flag_is_marked(self):
        self.assertIn(("--no-such-flag", "flag?"), kinds("tar --no-such-flag"))

    def test_empty_and_whitespace(self):
        self.assertEqual(rows(""), [])
        self.assertEqual(rows("   "), [])

    def test_unsupported_syntax_degrades_gracefully(self):
        # process substitution / heredoc / subshell: no exception, something sensible comes back
        for line in ("diff <(sort a) <(sort b)", "cat <<EOF", "(cd /tmp && ls)", "echo $(date)", "a | | b"):
            explain(kb(), line, "normal", man="none")

    def test_three_modes_differ(self):
        line = "tar -czvf x.tgz d"
        mn = render_text(kb(), line, "min", color=False, man="none")
        no = render_text(kb(), line, "normal", color=False, man="none")
        vb = render_text(kb(), line, "verbose", color=False, man="none")
        self.assertEqual(len(mn.splitlines()), 1)            # minimal = one line
        self.assertGreater(len(no.splitlines()), 4)
        self.assertIn("Watch out", vb)                       # verbose adds pitfalls
        self.assertGreater(len(vb), len(no))

    def test_cheat_sheet(self):
        out = render_command(kb(), "tcpdump", "normal", color=False, man="none")
        self.assertIn("Use cases:", out)
        self.assertIn("Options:", out)
        self.assertIn("No entry", render_command(kb(), "nope-nope", "normal", color=False, man="none"))

    def test_related_combos_in_verbose(self):
        res = explain(kb(), "tar -xzvf a.tgz", "verbose", man="none")
        self.assertTrue(res["related"])
        self.assertTrue(res["pitfalls"])


if __name__ == "__main__":
    unittest.main()
