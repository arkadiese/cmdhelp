"""CLI behaviour and shell integration (syntax + opt-in gating), run as real subprocesses."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import tests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "packaging")


def run(args, env=None, **kw):
    e = dict(os.environ, PYTHONPATH=ROOT, NO_COLOR="1")
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "cmdhelp"] + args, cwd=ROOT, env=e,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, **kw)


class CLITest(unittest.TestCase):
    def test_version(self):
        from cmdhelp import __version__
        r = run(["-V"])
        self.assertEqual(r.returncode, 0)
        self.assertIn(__version__, r.stdout + r.stderr)

    def test_explain(self):
        r = run(["-e", "tar -xzvf a.tgz"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("-x", r.stdout)
        self.assertNotIn("\x1b[", r.stdout)

    def test_no_color_after_line(self):
        r = run(["-e", "ls -la", "--no-color"], env={"NO_COLOR": ""})
        self.assertNotIn("--no-color", r.stdout)

    def test_explain_from_stdin(self):
        r = run(["-e"], input="grep -rn foo .")
        self.assertIn("-r", r.stdout)

    def test_sheet_modes(self):
        for m in ("min", "normal", "verbose", "v", "1"):
            r = run(["-s", "awk", "-m", m])
            self.assertEqual(r.returncode, 0, (m, r.stderr))
            self.assertIn("awk", r.stdout)

    def test_broken_pipe_is_quiet(self):
        p = subprocess.Popen("%s -m cmdhelp -s tar -m verbose | head -1" % sys.executable, shell=True, cwd=ROOT,
                             env=dict(os.environ, PYTHONPATH=ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, err = p.communicate()
        self.assertNotIn(b"Traceback", err)

    def test_enable_disable_marker(self):
        cfg = tempfile.mkdtemp()
        try:
            marker = os.path.join(cfg, "cmdhelp", "enabled")
            self.assertEqual(run(["--enable"], env={"XDG_CONFIG_HOME": cfg}).returncode, 0)
            self.assertTrue(os.path.exists(marker))
            self.assertEqual(run(["--disable"], env={"XDG_CONFIG_HOME": cfg}).returncode, 0)
            self.assertFalse(os.path.exists(marker))
        finally:
            shutil.rmtree(cfg)

    def test_init_output(self):
        for sh in ("bash", "zsh"):
            r = run(["--init", sh])
            self.assertIn("_cmdhelp_widget", r.stdout)
            self.assertIn("_cmdhelp_run()", r.stdout)


@unittest.skipUnless(shutil.which("bash"), "bash missing")
class ShellSnippetTest(unittest.TestCase):
    def test_syntax(self):
        subprocess.check_call(["bash", "-n", os.path.join(PKG, "cmdhelp.bash")])
        subprocess.check_call(["sh", "-n", os.path.join(PKG, "cmdhelp.sh")])
        if shutil.which("zsh"):
            subprocess.check_call(["zsh", "-n", os.path.join(PKG, "cmdhelp.zsh")])
        init = run(["--init", "bash"]).stdout
        subprocess.run(["bash", "-n"], input=init, universal_newlines=True, check=True)

    def test_bindings_include_fallback_key(self):
        with open(os.path.join(PKG, "cmdhelp.bash")) as fh:
            self.assertIn('\\C-xh', fh.read())
        with open(os.path.join(PKG, "cmdhelp.zsh")) as fh:
            self.assertIn("^Xh", fh.read())


@unittest.skipUnless(shutil.which("bash"), "bash missing")
class ProfileGatingTest(unittest.TestCase):
    """profile.d hook must do nothing unless the user (or admin) opted in."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # relocate /usr/share/cmdhelp and /etc/cmdhelp paths into a temp tree
        share = os.path.join(self.tmp, "share")
        os.makedirs(share)
        shutil.copy(os.path.join(PKG, "cmdhelp.bash"), share)
        with open(os.path.join(PKG, "cmdhelp.sh")) as fh:
            hook = fh.read().replace("/usr/share/cmdhelp", share).replace("/etc/cmdhelp", os.path.join(self.tmp, "etc"))
        self.hook = os.path.join(self.tmp, "hook.sh")
        with open(self.hook, "w") as fh:
            fh.write(hook)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def loaded(self, extra_env=None):
        """Source the hook in an interactive bash attached to a pty (the hook requires a tty)."""
        import pty
        master, slave = pty.openpty()
        env = {"HOME": self.home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TERM": "dumb"}
        env.update(extra_env or {})
        script = '. "%s"; if type _cmdhelp_widget >/dev/null 2>&1; then echo LOADED >&3; else echo NOT >&3; fi' % self.hook
        r, w = os.pipe()
        p = subprocess.Popen(["bash", "--norc", "--noprofile", "-i", "-c", "exec 3>&%d; %s" % (w, script)],
                             stdin=slave, stdout=slave, stderr=slave, env=env, pass_fds=(w,))
        os.close(slave)
        os.close(w)
        out = os.read(r, 100).decode()
        p.wait(10)
        os.close(r)
        os.close(master)
        return out.strip() == "LOADED"

    def test_default_off(self):
        self.assertFalse(self.loaded())

    def test_user_marker(self):
        os.makedirs(os.path.join(self.home, ".config", "cmdhelp"))
        open(os.path.join(self.home, ".config", "cmdhelp", "enabled"), "w").close()
        self.assertTrue(self.loaded())

    def test_env_enable(self):
        self.assertTrue(self.loaded({"CMDHELP_ENABLE": "1"}))

    def test_admin_enable_all(self):
        os.makedirs(os.path.join(self.tmp, "etc"))
        open(os.path.join(self.tmp, "etc", "enable-all"), "w").close()
        self.assertTrue(self.loaded())

    def test_disable_wins(self):
        self.assertFalse(self.loaded({"CMDHELP_ENABLE": "1", "CMDHELP_DISABLE": "1"}))


if __name__ == "__main__":
    unittest.main()


def _pty_shell(argv, script, env, timeout=15):
    """Run `script` in an interactive shell that owns a real controlling terminal (like a user's
    session, so </dev/tty works). Returns the shell's exit status."""
    import pty
    import select
    pid, master = pty.fork()
    if pid == 0:                                   # child: becomes session leader with the pty as ctty
        try:
            os.execvpe(argv[0], argv + [script], env)
        finally:
            os._exit(127)
    deadline = time.time() + timeout
    status = None
    try:
        while time.time() < deadline:              # drain output so the shell never blocks
            r, _, _ = select.select([master], [], [], 0.2)
            if r:
                try:
                    os.read(master, 4096)
                except OSError:                    # EIO: the shell closed the terminal (exited)
                    pass
            done, st = os.waitpid(pid, os.WNOHANG)
            if done:
                status = st
                break
        if status is None:                         # hung: kill and report
            os.kill(pid, 9)
            os.waitpid(pid, 0)
            return -1
        return os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
    finally:
        os.close(master)


class WidgetContextTest(unittest.TestCase):
    """The real widget must hand last command, exit status and current line to the helper via the
    ENVIRONMENT, never on the command line (argv is visible to every user in `ps`)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "seen")
        self.env = {"HOME": self.tmp, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TERM": "dumb",
                    "HISTFILE": os.path.join(self.tmp, "hist"), "OUT": self.out}
        # stub replaces the real helper: records what it received
        self.stub = ('_cmdhelp_run() { { printf "ARGV:%s\\n" "$*"; env | grep "^CMDHELP_"; } > "$OUT"; '
                     'printf "picked line" > "${2}"; }; ')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def seen(self):
        with open(self.out) as fh:
            return fh.read()

    def check(self, text):
        self.assertIn("CMDHELP_LAST_STATUS=2", text)
        self.assertIn("CMDHELP_LAST_CMD=tar -xzf secret-pass.tgz", text)
        self.assertIn("CMDHELP_LINE=half typed", text)
        argv = [l for l in text.splitlines() if l.startswith("ARGV:")][0]
        self.assertNotIn("secret-pass", argv)        # last command NOT on argv
        self.assertNotIn("half typed", argv)

    def test_bash(self):
        snippet = os.path.join(PKG, "cmdhelp.bash")
        script = ('set -o history; . "%s" 2>/dev/null; %s history -s "tar -xzf secret-pass.tgz"; '
                  'READLINE_LINE="half typed"; (exit 2); _cmdhelp_widget; '
                  '[ "$READLINE_LINE" = "picked line" ] && exit 0 || exit 9' % (snippet, self.stub))
        rc = _pty_shell(["bash", "--norc", "--noprofile", "-i", "-c"], script, self.env)
        self.check(self.seen())
        self.assertEqual(rc, 0, "picked line was not put back into READLINE_LINE")

    @unittest.skipUnless(shutil.which("zsh"), "zsh missing")
    def test_zsh(self):
        snippet = os.path.join(PKG, "cmdhelp.zsh")
        # zle widgets can't be invoked outside the line editor, so call the function body directly
        script = ('. "%s" 2>/dev/null; %s print -s "tar -xzf secret-pass.tgz"; zle() { :; }; '
                  'BUFFER="half typed"; (exit 2); _cmdhelp_widget; '
                  '[[ "$BUFFER" == "picked line" ]] && exit 0 || exit 9' % (snippet, self.stub))
        rc = _pty_shell(["zsh", "-f", "-i", "-c"], script, self.env)
        self.check(self.seen())
        self.assertEqual(rc, 0)


class PackagedSnippetSyncTest(unittest.TestCase):
    def test_packaging_files_match_generator(self):
        for sh in ("bash", "zsh"):
            gen = run(["--init-static", sh]).stdout
            with open(os.path.join(PKG, "cmdhelp." + sh)) as fh:
                self.assertEqual(fh.read(), gen, "packaging/cmdhelp.%s is stale: python3 -m cmdhelp --init-static %s > packaging/cmdhelp.%s" % (sh, sh, sh))


class ContextCLITest(unittest.TestCase):
    def test_explain_with_context(self):
        r = run(["-e", "--context"], env={"CMDHELP_LAST_CMD": "systemctl restart nginx", "CMDHELP_LAST_STATUS": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("systemctl", r.stdout)
        self.assertIn("exit 1", r.stdout)
        self.assertIn("journalctl -xeu nginx", r.stdout)

    def test_context_alone(self):
        r = run(["--context"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Here:", r.stdout)
