import builtins
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from tests.helpers import kb
import cmdhelp.context as cx
from cmdhelp.context import Context, suggestions, fill, render_context


def cmds(line, status, cwd="/nonexistent-dir-for-tests", limit=20):
    return [s["cmd"] for s in suggestions(Context(line, status, cwd), kb(), limit)]


class StatusTextTest(unittest.TestCase):
    def st(self, line, status):
        return Context(line, status, "/").status_text()

    def test_command_specific_meanings(self):
        self.assertIn("no lines matched", self.st("grep x f", 1))
        self.assertIn("failed to connect", self.st("curl https://a.b", 7))
        self.assertIn("certificate", self.st("curl https://a.b", 60))
        self.assertIn("target is busy", self.st("umount /mnt", 32))
        self.assertIn("ssh itself failed", self.st("ssh host", 255))

    def test_generic_and_signals(self):
        self.assertIn("command not found", self.st("foo", 127))
        self.assertIn("not executable", self.st("./x.sh", 126))
        self.assertIn("SIGINT", self.st("sleep 9", 130))
        self.assertIn("OOM", self.st("make", 137))
        self.assertEqual(self.st("ls", 0), "exit 0: success")
        self.assertIsNone(self.st("ls", None))

    def test_prefixes_and_pipelines(self):
        c = Context("sudo -u oracle env A=1 timeout 5 grep -i x f", 1, "/")
        self.assertEqual(c.cmd, "grep")
        self.assertTrue(c.sudo)
        # bash reports the status of the LAST command of a pipeline
        self.assertEqual(Context("cat f | grep x", 1, "/").cmd, "grep")

    def test_from_env(self):
        c = Context.from_env({"CMDHELP_LAST_CMD": " ls -la ", "CMDHELP_LAST_STATUS": "2"})
        self.assertEqual((c.last_cmd, c.status), ("ls -la", 2))
        self.assertIsNone(Context.from_env({"CMDHELP_LAST_STATUS": "garbage"}).status)
        self.assertIsNone(Context.from_env({}).last_cmd)


class FailRulesTest(unittest.TestCase):
    def test_tar(self):
        self.assertIn("file backup.tgz", cmds("tar -xzf backup.tgz", 2))

    def test_systemctl(self):
        c = cmds("systemctl restart nginx", 1)
        self.assertIn("systemctl status nginx -l --no-pager", c)
        self.assertTrue(any(x.startswith("journalctl -xeu nginx") for x in c))

    def test_curl_by_exit_code(self):
        self.assertIn("dig +short api.example.com", cmds("curl https://api.example.com/x", 6))
        self.assertIn("nc -zv -w3 api.example.com 443", cmds("curl -sS https://api.example.com/x", 7))
        self.assertTrue(any(x.startswith("openssl s_client -connect api.example.com:443") for x in cmds("curl https://api.example.com", 60)))
        self.assertIn("nc -zv -w3 db.local 8080", cmds("curl http://db.local:8080/health", 7))

    def test_ssh_uses_the_custom_port(self):
        c = cmds("ssh -p 2222 root@10.0.0.5", 255)
        self.assertIn("ssh -vvv -p 2222 root@10.0.0.5", c)
        self.assertIn("nc -zv -w3 10.0.0.5 2222", c)

    def test_grep_no_match_variants(self):
        d = tempfile.mkdtemp()
        try:
            os.mkdir(os.path.join(d, "conf"))
            c = cmds("grep a.b conf", 1, d)
            self.assertIn("grep -i a.b conf", c)
            self.assertIn("grep -rn a.b conf", c)
            self.assertIn("grep -F a.b conf", c)
        finally:
            shutil.rmtree(d)

    def test_dnf(self):
        c = cmds("dnf install htop", 1)
        self.assertIn("dnf search htop", c)
        self.assertIn("dnf repolist", c)

    def test_typo_and_missing_tool(self):
        self.assertEqual(cmds("sl -la", 127)[0], "ls -la")                # swapped letters, ls installed
        self.assertEqual(cmds("gerp foo f", 127)[0], "grep foo f")
        self.assertFalse(any(x.startswith("sh ") for x in cmds("ssh root@h", 127)))  # known tool: no 'did you mean sh'

    def test_permission_and_signals(self):
        self.assertIn("chmod +x ./deploy.sh", cmds("./deploy.sh", 126))
        self.assertTrue(any("OOM" in s["why"] for s in suggestions(Context("make", 137, "/x"), kb())))
        self.assertEqual(cmds("sleep 100", 130), [])                        # Ctrl+C: nothing to fix

    def test_sudo_suggested_only_for_non_root(self):
        with mock.patch.object(cx, "_euid", return_value=1000):
            self.assertIn("sudo systemctl restart nginx", cmds("systemctl restart nginx", 1))
            self.assertNotIn("sudo sudo systemctl restart nginx", cmds("sudo systemctl restart nginx", 1))
            self.assertNotIn("sudo ls x", cmds("ls x", 2))                  # ls rarely needs root
        with mock.patch.object(cx, "_euid", return_value=0):
            self.assertNotIn("sudo systemctl restart nginx", cmds("systemctl restart nginx", 1))

    def test_oracle(self):
        self.assertIn("lsnrctl status", cmds("sqlplus / as sysdba", 1))


class OkRulesTest(unittest.TestCase):
    def test_next_steps(self):
        self.assertIn("cd newdir", cmds("mkdir -p newdir", 0))
        self.assertIn("cd cmdhelp", cmds("git clone https://github.com/arkadiese/cmdhelp.git", 0))
        self.assertIn("tar -xf pkg-1.2.tar.gz", cmds("wget https://x.org/pkg-1.2.tar.gz", 0))
        self.assertIn("sudo dnf install ./x.rpm", cmds("curl -LO https://x.org/x.rpm", 0))
        self.assertIn("systemctl status httpd --no-pager", cmds("sudo systemctl restart httpd", 0))
        self.assertIn("systemctl start nginx", cmds("systemctl enable nginx", 0))
        self.assertIn("firewall-cmd --runtime-to-permanent", cmds("firewall-cmd --add-port=8080/tcp", 0))
        self.assertIn("iptables -L -n -v --line-numbers", cmds("iptables -I INPUT -p tcp --dport 22 -j ACCEPT", 0))
        self.assertIn("tcpdump -nn -r cap.pcap | head -50", cmds("tcpdump -i any -w cap.pcap", 0))

    def test_config_checks_after_editing(self):
        self.assertIn("sshd -t", cmds("vim /etc/ssh/sshd_config", 0))
        self.assertIn("nginx -t", cmds("sudo vi /etc/nginx/nginx.conf", 0))
        self.assertIn("visudo -c", cmds("vi /etc/sudoers.d/admins", 0))
        self.assertIn("tnsping SERVICE", cmds("vi $ORACLE_HOME/network/admin/tnsnames.ora", 0))
        self.assertIn("systemctl daemon-reload", cmds("vim /etc/systemd/system/app.service", 0))


class FolderTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        old = time.time() - 3600
        for name in ("old.tar.gz", "new.tgz", "app.log", "cap.pcap", "x.rpm", ".hidden.tar.gz"):
            open(os.path.join(self.d, name), "w").close()
        os.utime(os.path.join(self.d, "old.tar.gz"), (old, old))
        os.mkdir(os.path.join(self.d, "src"))
        self.ctx = Context(None, None, self.d)

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_folder_suggestions_use_newest(self):
        c = [s["cmd"] for s in suggestions(self.ctx, kb())]
        self.assertIn("tar -tvf new.tgz | head", c)
        self.assertIn("tail -F app.log", c)
        self.assertIn("sudo dnf install ./x.rpm", c)
        self.assertFalse(any(".hidden" in x for x in c))

    def test_fill_inputs(self):
        self.assertEqual(fill("tar -xzvf archive.tar.gz", self.ctx), ("tar -xzvf new.tgz", True))
        self.assertEqual(fill("tcpdump -nn -r cap.pcap 'port 53'", self.ctx)[1], True)
        self.assertEqual(fill("zstd -d <path/to/file.zst>", self.ctx), ("zstd -d <path/to/file.zst>", False))
        self.assertEqual(fill("tar -xf <path/to/file.tar.gz>", self.ctx), ("tar -xf new.tgz", True))

    def test_fill_never_touches_outputs(self):
        # filling these with an existing name would OVERWRITE a real file
        for line in ("tar -czvf archive.tar.gz dir/", "tar czf archive.tar.gz dir/", "tar -c -f archive.tar.gz dir/",
                     "zip -r archive.zip dir/", "tcpdump -i eth0 -w cap.pcap", "gzip -c file.log > file.log.gz"):
            out, _ = fill(line, self.ctx)
            self.assertNotIn("new.tgz", out, line)
            self.assertNotIn("old.tar.gz", out, line)
        self.assertEqual(fill("tar -czvf archive.tar.gz dir/", self.ctx)[0], "tar -czvf archive.tar.gz src/")
        self.assertEqual(fill("tcpdump -i eth0 -w cap.pcap", self.ctx)[0], "tcpdump -i eth0 -w cap.pcap")

    def test_never_reads_file_contents(self):
        real_open = builtins.open

        def guarded(path, *a, **kw):
            if str(path).startswith(self.d):
                raise AssertionError("context opened a file: %s" % path)
            return real_open(path, *a, **kw)
        with mock.patch.object(builtins, "open", guarded):
            c = Context("tar -xzf new.tgz", 2, self.d)
            suggestions(c, kb())
            fill("tar -xzvf archive.tar.gz", c)
            render_context(c, kb(), color=False)

    def test_entry_cap_and_bad_cwd(self):
        with mock.patch.object(cx, "MAX_ENTRIES", 2):
            self.assertLessEqual(len(Context(None, None, self.d).files), 2)
        self.assertEqual(Context(None, None, "/definitely/not/here").files, [])

    def test_render(self):
        out = render_context(Context("tar -xzf new.tgz", 2, self.d), kb(), color=False)
        self.assertIn("Last: tar -xzf new.tgz  exit 2: fatal error", out)
        self.assertIn("To investigate:", out)
        self.assertIn("In this folder:", out)


if __name__ == "__main__":
    unittest.main()
