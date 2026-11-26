"""Context-aware suggestions from things the shell already knows.

Inputs (all local, nothing is recorded or written to disk):
  * the last command line          (CMDHELP_LAST_CMD, from `fc -ln -1`)
  * its exit status                (CMDHELP_LAST_STATUS, from `$?`)
  * the current directory          (os.getcwd(): names, types, sizes, mtimes only;
                                    file CONTENTS and command OUTPUT are never read)

Outputs: a short ranked list of {"cmd", "why", "kind"} suggestions, plus a way to fill the
placeholders of ready-made combos with real file names from the current directory.
"""
import difflib
import os
import re
import shutil

from .explain import tokenize, split_segments
from .kb import PREFIX_CMDS

ARCHIVE_RE = re.compile(r"\.(tar\.gz|tgz|tar\.xz|txz|tar\.bz2|tbz2?|tar\.zst|tar)$", re.I)
EXT_FAMILIES = [
    ("archive", ARCHIVE_RE),
    ("zip", re.compile(r"\.zip$", re.I)),
    ("gz", re.compile(r"(?<!\.tar)\.gz$", re.I)),
    ("xz", re.compile(r"(?<!\.tar)\.xz$", re.I)),
    ("rpm", re.compile(r"\.rpm$", re.I)),
    ("log", re.compile(r"(\.log(\.\d+)?|^messages|^secure|^syslog|^alert_.*\.log)$", re.I)),
    ("pcap", re.compile(r"\.(pcap|pcapng|cap)$", re.I)),
    ("csv", re.compile(r"\.csv$", re.I)),
    ("json", re.compile(r"\.json$", re.I)),
    ("sh", re.compile(r"\.sh$", re.I)),
    ("trc", re.compile(r"\.trc$", re.I)),
    ("sql", re.compile(r"\.sql$", re.I)),
    ("conf", re.compile(r"\.(conf|cnf|cfg|ini|ya?ml|ora)$", re.I)),
]
MAX_ENTRIES = 400          # never stat more than this many directory entries

# commands that commonly fail only because they need root
NEEDS_ROOT = {"systemctl", "dnf", "yum", "rpm", "apt", "apt-get", "iptables", "ip6tables", "nft", "firewall-cmd",
              "tcpdump", "mount", "umount", "useradd", "usermod", "userdel", "groupadd", "passwd", "chown",
              "journalctl", "dmesg", "lsof", "ss", "netstat", "fdisk", "parted", "mkfs", "fsck", "modprobe",
              "sysctl", "crontab", "service", "reboot", "shutdown", "ethtool", "nmap", "setenforce", "semanage",
              "restorecon", "visudo", "lvextend", "lvcreate", "pvcreate", "vgextend", "resize2fs", "xfs_growfs"}

SIGNALS = {1: "SIGHUP (terminal closed)", 2: "SIGINT (Ctrl+C)", 3: "SIGQUIT", 6: "SIGABRT (aborted, often an assert)",
           9: "SIGKILL (killed hard, often by the OOM killer)", 11: "SIGSEGV (segmentation fault)",
           13: "SIGPIPE (reader of its output went away)", 15: "SIGTERM (asked to stop)"}

# per-command exit codes that are NOT the generic meaning
CMD_CODES = {
    "grep": {1: "no lines matched (not an error)", 2: "error: bad regex or unreadable file"},
    "egrep": {1: "no lines matched (not an error)"}, "zgrep": {1: "no lines matched (not an error)"},
    "diff": {1: "the files differ (not an error)", 2: "trouble: missing file or binary"},
    "cmp": {1: "the files differ"},
    "test": {1: "condition is false"}, "[": {1: "condition is false"},
    "curl": {3: "malformed URL", 6: "could not resolve host (DNS)", 7: "failed to connect (port closed, firewall, service down)",
             22: "HTTP error >= 400 (with -f)", 28: "timed out", 35: "TLS handshake failed", 47: "too many redirects",
             51: "server certificate name mismatch", 52: "server sent nothing", 56: "connection reset while receiving",
             60: "certificate not trusted (unknown CA / expired / self-signed)"},
    "wget": {1: "generic error", 3: "file I/O error", 4: "network failure", 5: "TLS verification failure",
             6: "authentication failure", 8: "server returned an error (404/403/500...)"},
    "ssh": {255: "ssh itself failed: connection, host key or authentication problem"},
    "scp": {1: "copy failed (path, permission or connection)"},
    "rsync": {1: "syntax/usage error", 5: "error starting client-server protocol", 11: "file I/O error",
              12: "protocol data stream error (often remote rsync missing)", 23: "partial transfer: some files failed",
              24: "partial transfer: source files vanished", 30: "timeout", 255: "ssh connection failed"},
    "ping": {1: "no replies received", 2: "error (unknown host, network unreachable)"},
    "systemctl": {3: "unit is not running (inactive/dead)", 4: "no such unit", 5: "unit not loaded / not found"},
    "tar": {1: "some files differ or changed while being archived", 2: "fatal error"},
    "umount": {32: "target is busy"}, "mount": {32: "mount failure"},
    "unzip": {9: "not a zip file / zip not found", 11: "no matching files"},
    "gzip": {1: "error", 2: "warning"}, "gunzip": {1: "error", 2: "warning"},
    "dnf": {1: "error (package not found, conflict, or no permission)"},
    "make": {2: "a build rule failed"},
}

GENERIC_CODES = {1: "general error", 2: "misuse: bad option or argument", 126: "found but not executable (permission)",
                 127: "command not found"}


def _strip_prefixes(toks):
    """['sudo','-u','x','env','A=1','tar','-x'] -> (['tar','-x'], had_sudo)."""
    i, sudo = 0, False
    while i < len(toks):
        t = toks[i]
        if t in ("sudo", "doas"):
            sudo = True
            i += 1
            while i < len(toks) and toks[i].startswith("-"):
                i += 2 if toks[i] in ("-u", "-g") else 1
            continue
        if t in PREFIX_CMDS or re.match(r"^[A-Za-z_]\w*=", t):
            i += 1
            if t == "timeout" and i < len(toks) and re.match(r"^[\d.]+[smhd]?$", toks[i]):
                i += 1
            continue
        break
    return toks[i:], sudo


def _q(s):
    """Quote for re-insertion into a shell line only when needed."""
    return s if re.match(r"^[\w@%+=:,./~-]+$", s) else "'" + s.replace("'", "'\\''") + "'"


class Context(object):
    def __init__(self, last_cmd=None, status=None, cwd=None):
        self.last_cmd = (last_cmd or "").strip() or None
        self.status = status
        self.cwd = cwd or _safe_cwd()
        self._files = None
        toks = tokenize(self.last_cmd or "")
        segs = [s for s, sep in split_segments(toks) if s]
        # bash reports the status of the LAST element of a pipeline
        self.segment, self.sudo = _strip_prefixes(segs[-1]) if segs else ([], False)
        self.last_line_segment = " ".join(_q(t) for t in (segs[-1] if segs else []))
        self.cmd = os.path.basename(self.segment[0]) if self.segment else None
        self.args = self.segment[1:]

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        st = env.get("CMDHELP_LAST_STATUS", "")
        return cls(env.get("CMDHELP_LAST_CMD"), int(st) if st.strip().lstrip("-").isdigit() else None)

    # ---------- directory metadata (names/types/sizes/mtimes only) ----------
    @property
    def files(self):
        if self._files is None:
            out = []
            try:
                it = os.scandir(self.cwd)
            except OSError:
                it = []
            try:
                for n, e in enumerate(it):
                    if n >= MAX_ENTRIES:
                        break
                    if e.name.startswith("."):
                        continue
                    try:
                        st = e.stat(follow_symlinks=False)
                        out.append((e.name, e.is_dir(follow_symlinks=False), st.st_mtime, st.st_size))
                    except OSError:
                        continue
            finally:
                if hasattr(it, "close"):
                    it.close()
            out.sort(key=lambda f: -f[2])        # newest first
            self._files = out
        return self._files

    def has(self, name):
        return os.path.exists(os.path.join(self.cwd, name))

    def newest(self, family=None, dirs=False):
        for name, is_dir, _, _ in self.files:
            if dirs:
                if is_dir:
                    return name
                continue
            if is_dir:
                continue
            if family is None or family_of(name) == family:
                return name
        return None

    @property
    def failed(self):
        return self.status not in (None, 0)

    # ---------- explanations ----------
    def status_text(self):
        if self.status is None:
            return None
        s, c = self.status, self.cmd
        if s == 0:
            return "exit 0: success"
        meaning = CMD_CODES.get(c, {}).get(s) or GENERIC_CODES.get(s)
        if not meaning and 128 < s < 128 + 65:
            meaning = "killed by signal %d: %s" % (s - 128, SIGNALS.get(s - 128, "see: kill -l %d" % (s - 128)))
        return "exit %d: %s" % (s, meaning or "failed (check the command's man page, EXIT STATUS section)")


def _safe_cwd():
    try:
        return os.getcwd()
    except OSError:
        return os.path.expanduser("~")


def family_of(name):
    for fam, rx in EXT_FAMILIES:
        if rx.search(name):
            return fam
    return None


# ---------------------------------------------------------------- rules
def _positional(args):
    return [a for a in args if not a.startswith("-")]


def _archive_arg(args):
    for i, a in enumerate(args):
        if re.match(r"^-[a-zA-Z]*f$", a) and i + 1 < len(args):
            return args[i + 1]
        if a.startswith("--file="):
            return a.split("=", 1)[1]
    for a in args:
        if family_of(a) in ("archive", "zip", "gz", "xz"):
            return a
    return None


def _url(args):
    for a in args:
        m = re.match(r"^(?:(https?|ftp)://)?([^/:@\s]+@)?([A-Za-z0-9.-]+\.[A-Za-z]{2,}|\d+\.\d+\.\d+\.\d+|localhost)(?::(\d+))?(/\S*)?$", a)
        if m and (m.group(1) or "." in a):
            port = m.group(4) or ("443" if (m.group(1) or "").lower() == "https" else "80")
            return a, m.group(3), port
    return None, None, None


def _ssh_target(args):
    skip_next = {"-p", "-i", "-l", "-o", "-L", "-R", "-D", "-J", "-F", "-c", "-m", "-b", "-E", "-W", "-P"}
    port, i = "22", 0
    while i < len(args):
        a = args[i]
        if a in ("-p", "-P") and i + 1 < len(args):
            port = args[i + 1]
        if a in skip_next:
            i += 2
            continue
        if not a.startswith("-"):
            host = a.split(":")[0]
            return host, host.split("@")[-1], port
        i += 1
    return None, None, port


def _unit(args):
    pos = _positional(args)
    if pos and pos[0] in ("start", "restart", "reload", "stop", "status", "enable", "disable", "try-restart", "reload-or-restart") and len(pos) > 1:
        return pos[0], pos[1]
    return (pos[0] if pos else None), None


CONFIG_CHECKS = [
    (re.compile(r"nginx.*\.conf$|/nginx/"), "nginx -t", "check nginx config syntax before reload"),
    (re.compile(r"httpd.*\.conf$|/httpd/|apache2"), "apachectl configtest", "check Apache config syntax"),
    (re.compile(r"sshd_config"), "sshd -t", "check sshd config BEFORE restarting (don't lock yourself out)"),
    (re.compile(r"\.service$|\.timer$|\.socket$"), "systemctl daemon-reload", "reload unit files after editing"),
    (re.compile(r"/etc/fstab$|^fstab$"), "findmnt --verify", "verify fstab before the next reboot"),
    (re.compile(r"sudoers"), "visudo -c", "check sudoers syntax"),
    (re.compile(r"named\.conf"), "named-checkconf", "check BIND config"),
    (re.compile(r"\.zone$|/named/"), "named-checkzone ZONE FILE", "check a zone file"),
    (re.compile(r"\.bashrc$|\.bash_profile$"), "source ~/.bashrc", "load the changes into this shell"),
    (re.compile(r"\.zshrc$"), "source ~/.zshrc", "load the changes into this shell"),
    (re.compile(r"resolv\.conf$"), "dig +short example.com", "test DNS resolution"),
    (re.compile(r"tnsnames\.ora$"), "tnsping SERVICE", "test the new TNS alias"),
    (re.compile(r"listener\.ora$"), "lsnrctl reload", "make the listener re-read its config"),
    (re.compile(r"crontab|cron\.d/"), "crontab -l", "check the installed crontab"),
    (re.compile(r"\.ya?ml$"), "python3 -c 'import sys,yaml; yaml.safe_load(open(sys.argv[1]))' FILE", "check YAML syntax"),
    (re.compile(r"\.json$"), "jq . FILE >/dev/null && echo valid", "check JSON syntax"),
    (re.compile(r"\.sh$"), "bash -n FILE", "syntax-check the script without running it"),
    (re.compile(r"/etc/sysctl"), "sysctl --system", "apply sysctl settings"),
    (re.compile(r"\.repo$"), "dnf repolist", "check the repo is picked up"),
    (re.compile(r"my\.cnf"), "systemctl restart mysqld && systemctl status mysqld --no-pager", "restart MySQL to apply"),
]


def _fail_rules(c, kb):
    cmd, a, out = c.cmd, c.args, []
    add = lambda s, why: out.append((s, why))   # noqa: E731
    pos = _positional(a)

    if c.status == 127:
        known = bool(kb and cmd in kb.rank_pos)   # a common tool that just isn't installed: no typo guessing
        pool = [] if known else [n for n in (kb.rank if kb else []) if n != cmd]
        swapped = [m for m in pool if len(m) == len(cmd) and sorted(m) == sorted(cmd)
                   and sum(1 for x, y in zip(m, cmd) if x != y) == 2]          # sl -> ls, gerp -> grep
        close = []
        for m in swapped + difflib.get_close_matches(cmd, pool, n=6, cutoff=0.6):
            if m not in close and shutil.which(m):
                close.append(m)
        close = close[:2]
        for m in close:
            add(c.last_line_segment.replace(cmd, m, 1), "did you mean '%s'?" % m)
        if shutil.which("dnf") or shutil.which("yum"):
            add("dnf provides '*/bin/%s'" % cmd, ("'%s' is a known tool that isn't installed: which package has it" if known
                                                   else "which package installs '%s'") % cmd)
        elif shutil.which("apt-get"):
            add("apt-cache search %s" % _q(cmd), "find a package for '%s'" % cmd)
        add("type -a %s" % _q(cmd), "is it an alias/function, or not in $PATH?")
        return out
    if c.status == 126:
        add("ls -l %s" % _q(c.segment[0]), "check the execute bit and owner")
        add("chmod +x %s" % _q(c.segment[0]), "make it executable")
        return out
    if c.status in (128 + 9, 9):
        add("dmesg -T | grep -iE 'killed process|out of memory' | tail", "was it the OOM killer?")
        add("free -h", "current memory")
    if c.status in (128 + 11,):
        add("dmesg -T | tail -20", "kernel log for the segfault")
        add("coredumpctl list --since today", "core dumps (systemd)")

    if cmd in ("tar",):
        f = _archive_arg(a)
        if f:
            add("file %s" % _q(f), "is it really the archive type you think? (gzip vs xz vs plain tar vs HTML)")
            add("tar -tvf %s | head" % _q(f), "list it before extracting")
            add("ls -l %s" % _q(f), "exists? size 0? truncated download?")
    elif cmd in ("gzip", "gunzip", "zcat", "xz", "unxz", "bzip2", "bunzip2", "zstd"):
        for f in pos[:1]:
            add("file %s" % _q(f), "check the real file type")
            add("ls -l %s" % _q(f), "exists? empty? already decompressed?")
    elif cmd == "unzip":
        for f in pos[:1]:
            add("unzip -l %s" % _q(f), "list the archive")
            add("file %s" % _q(f), "is it really a zip?")
    elif cmd in ("systemctl", "service"):
        verb, unit = _unit(a) if cmd == "systemctl" else ((pos[1] if len(pos) > 1 else None), (pos[0] if pos else None))
        if unit:
            add("systemctl status %s -l --no-pager" % _q(unit), "state + last log lines")
            add("journalctl -xeu %s --no-pager | tail -50" % _q(unit), "why it failed")
            add("systemctl cat %s" % _q(unit), "the unit file actually in use")
        else:
            add("systemctl --failed", "what is failing")
    elif cmd == "ssh" or cmd == "scp" or cmd == "sftp":
        target, host, port = _ssh_target(a)
        if host:
            add("ssh -vvv -p %s %s" % (port, _q(target)), "verbose: shows where it fails (DNS, TCP, host key, auth)")
            add("nc -zv -w3 %s %s" % (_q(host), port), "is the SSH port reachable at all?")
            add("ssh-keygen -R %s" % _q(host), "only if it said REMOTE HOST IDENTIFICATION HAS CHANGED")
    elif cmd == "rsync":
        add("rsync --version && ssh <host> rsync --version", "rsync must exist on both ends")
    elif cmd in ("curl", "wget"):
        url, host, port = _url(a)
        if host:
            s = c.status
            if (cmd == "curl" and s == 6) or (cmd == "wget" and s == 4):
                add("dig +short %s" % _q(host), "does the name resolve?")
            if (cmd == "curl" and s in (7, 28, 56)) or (cmd == "wget" and s == 4):
                add("nc -zv -w3 %s %s" % (_q(host), port), "is the port open?")
                add("ip route get $(dig +short %s | tail -1)" % _q(host), "which route/interface is used")
            if (cmd == "curl" and s in (35, 51, 60)) or (cmd == "wget" and s == 5):
                add("openssl s_client -connect %s:%s -servername %s </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates"
                    % (host, port, host), "inspect the certificate (expiry, issuer, name)")
            add("curl -sSv -o /dev/null %s" % _q(url), "verbose: DNS, connect, TLS and HTTP status step by step")
    elif cmd == "ping":
        h = pos[-1] if pos else None
        if h:
            if c.status == 2:
                add("dig +short %s" % _q(h), "does the name resolve?")
            add("ip route get %s" % _q(h), "which interface/gateway would be used")
            add("tracepath -n %s" % _q(h), "where the path stops (no root needed)")
    elif cmd in ("dig", "nslookup", "host"):
        n = [p for p in pos if not p.startswith("@")]
        add("cat /etc/resolv.conf", "which DNS servers this box uses")
        if n:
            add("dig @1.1.1.1 +short %s" % _q(n[-1]), "compare with a public resolver")
    elif cmd == "umount":
        for t in pos[:1]:
            add("lsof +D %s 2>/dev/null | head" % _q(t), "who is using it (target is busy)")
            add("fuser -vm %s" % _q(t), "processes holding the mount")
    elif cmd == "mount":
        add("dmesg -T | tail", "kernel reason for the mount failure")
        add("findmnt --verify", "check fstab")
    elif cmd == "cd":
        p = pos[0] if pos else None
        if p:
            add("ls -ld %s" % _q(os.path.dirname(p.rstrip("/")) or "."), "does the parent exist / can you enter it?")
    elif cmd in ("cp", "mv", "rm", "rmdir", "mkdir", "touch", "ln"):
        if cmd == "mkdir" and "-p" not in a and pos:
            add("mkdir -p %s" % " ".join(_q(p) for p in pos), "create missing parent directories too")
        for p in pos[-1:]:
            add("ls -ld %s" % _q(p), "exists? permissions?")
        if cmd in ("cp", "mv") and pos:
            add("df -h %s" % _q(os.path.dirname(pos[-1].rstrip("/")) or "."), "space left on the destination")
    elif cmd in ("chmod", "chown", "chgrp"):
        for p in pos[1:2]:
            add("ls -l %s" % _q(p), "current owner and mode")
    elif cmd in ("dnf", "yum"):
        if pos and pos[0] in ("install", "update", "upgrade") and len(pos) > 1:
            pkg = pos[1]
            if family_of(pkg) == "rpm":
                add("rpm -qpR %s" % _q(pkg), "what the RPM needs")
            else:
                add("dnf search %s" % _q(pkg), "find the right package name")
                add("dnf provides '*/%s'" % pkg, "which package ships a file by that name")
                add("dnf repolist", "are the needed repos enabled? (EPEL? CRB?)")
        add("dnf clean metadata", "stale metadata / mirror errors")
    elif cmd == "rpm":
        for p in pos:
            if family_of(p) == "rpm":
                add("dnf install ./%s" % p.lstrip("./"), "let dnf resolve the dependencies")
    elif cmd in ("grep", "egrep", "zgrep") and c.status == 1:
        line = c.last_line_segment
        if " -i" not in line:
            add(re.sub(r"^(\S*grep)", r"\1 -i", line, count=1), "try case-insensitive")
        if any(os.path.isdir(os.path.join(c.cwd, p)) for p in pos[1:]) and " -r" not in line:
            add(re.sub(r"^(\S*grep)", r"\1 -rn", line, count=1), "search directories recursively")
        if pos and re.search(r"[.*\[\]()+?{}|\\^$]", pos[0]) and " -F" not in line:
            add(re.sub(r"^(\S*grep)", r"\1 -F", line, count=1), "pattern has regex characters: match them literally")
    elif cmd in ("iptables", "ip6tables"):
        add("iptables -V", "nft or legacy backend? (rules set with one are invisible to the other)")
        add("iptables -S | head -40", "current rules as commands")
    elif cmd == "tcpdump":
        add("tcpdump -D", "valid interface names")
        add("ip -br link", "interfaces and state")
    elif cmd in ("docker", "podman"):
        if cmd == "docker":
            add("systemctl status docker --no-pager", "is the daemon running?")
        add("%s ps -a" % cmd, "containers, including exited ones")
    elif cmd == "make":
        add("make -n", "dry run: show what it would do")
    elif cmd in ("sqlplus", "tnsping", "lsnrctl", "rman", "expdp", "impdp"):
        add('echo "ORACLE_HOME=$ORACLE_HOME ORACLE_SID=$ORACLE_SID"', "Oracle environment set in this shell?")
        add("lsnrctl status", "is the listener up, which services does it know")
        add("ps -ef | grep [p]mon_", "which instances are running")
    elif cmd in ("firewall-cmd",):
        add("systemctl status firewalld --no-pager", "is firewalld running?")
    elif cmd == "crontab":
        add("crontab -l", "current crontab")
    elif cmd == "kill":
        for p in pos:
            if p.isdigit():
                add("ps -p %s -o pid,user,stat,etime,cmd" % p, "does the process exist, who owns it")

    if (cmd in NEEDS_ROOT or c.status == 126) and not c.sudo and _euid() != 0 and c.last_line_segment:
        add("sudo " + c.last_line_segment, "if it said 'Permission denied' / 'Operation not permitted'")
    if not out and cmd:
        add("man %s" % _q(cmd), "see the EXIT STATUS / DIAGNOSTICS section")
    return out


def _euid():
    try:
        return os.geteuid()
    except AttributeError:
        return 1


def _ok_rules(c):
    cmd, a, out = c.cmd, c.args, []
    add = lambda s, why: out.append((s, why))   # noqa: E731
    pos = _positional(a)
    flags = "".join(x.lstrip("-") for x in a if x.startswith("-") and not x.startswith("--"))
    if cmd == "tar":
        f = _archive_arg(a)
        if f and "c" in flags:
            add("tar -tvf %s | head" % _q(f), "verify the archive you just made")
            add("ls -lh %s" % _q(f), "its size")
        elif f and "t" in flags:
            add("tar -xf %s" % _q(f), "extract it here")
            add("mkdir -p /tmp/x && tar -xf %s -C /tmp/x" % _q(f), "extract somewhere safe first")
        elif "x" in flags:
            add("ls -lt | head", "what was just extracted")
    elif cmd == "mkdir" and pos:
        add("cd %s" % _q(pos[-1]), "go into it")
    elif cmd == "git" and pos[:1] == ["clone"] and len(pos) > 1:
        d = pos[2] if len(pos) > 2 else re.sub(r"\.git$", "", pos[1].rstrip("/").split("/")[-1].split(":")[-1])
        add("cd %s" % _q(d), "go into the clone")
    elif cmd in ("wget", "curl"):
        saved = None
        for i, x in enumerate(a):
            if x in ("-o", "-O", "--output", "--output-document") and i + 1 < len(a) and not (cmd == "curl" and x == "-O"):
                saved = a[i + 1]
        if not saved and (cmd == "wget" or "-O" in a or "--remote-name" in a or "-LO" in a or "-OL" in a):
            url, _, _ = _url(a)
            if url:
                saved = url.split("?")[0].rstrip("/").split("/")[-1]
        if saved:
            fam = family_of(saved)
            if fam == "archive":
                add("tar -tvf %s | head" % _q(saved), "look inside before extracting")
                add("tar -xf %s" % _q(saved), "extract it")
            elif fam == "zip":
                add("unzip -l %s" % _q(saved), "look inside")
            elif fam == "rpm":
                add("rpm -qpi %s" % _q(saved), "what is this package")
                add("sudo dnf install ./%s" % saved, "install it with dependencies")
            add("sha256sum %s" % _q(saved), "checksum to compare with the publisher's")
            add("file %s" % _q(saved), "did you get the file, or an HTML error page?")
    elif cmd == "systemctl":
        verb, unit = _unit(a)
        if unit and verb in ("start", "restart", "reload", "try-restart", "reload-or-restart"):
            add("systemctl status %s --no-pager" % _q(unit), "did it come up?")
            add("journalctl -u %s -f" % _q(unit), "follow its log")
        elif unit and verb in ("enable", "disable"):
            add("systemctl is-enabled %s" % _q(unit), "confirm the boot setting")
            if "--now" not in a and verb == "enable":
                add("systemctl start %s" % _q(unit), "enable does not start it; this does")
    elif cmd in ("dnf", "yum") and pos[:1] == ["install"] and len(pos) > 1:
        pkg = pos[1]
        if family_of(pkg) != "rpm":
            add("rpm -ql %s | head -30" % _q(pkg), "what it installed")
            add("systemctl list-unit-files '%s*'" % pkg, "does it ship a service to enable?")
    elif cmd == "useradd" and pos:
        add("passwd %s" % _q(pos[-1]), "set a password")
        add("id %s" % _q(pos[-1]), "check uid/groups")
    elif cmd == "ssh-keygen" and "-R" not in a:
        add("ssh-copy-id user@host", "install the new public key on a server")
    elif cmd == "ssh-copy-id":
        add("ssh " + " ".join(_q(p) for p in a), "log in with the key now")
    elif cmd in ("iptables", "ip6tables") and any(x in a for x in ("-A", "-I", "-D", "-R", "-P", "-F")):
        add("%s -L -n -v --line-numbers" % cmd, "check the result and counters")
        add("%s-save > /etc/sysconfig/%s" % (cmd, cmd), "persist (RHEL path; Debian: /etc/iptables/rules.v4)")
    elif cmd == "firewall-cmd" and "--permanent" not in a and any(x.startswith(("--add", "--remove")) for x in a):
        add("firewall-cmd --runtime-to-permanent", "that change is runtime only; this keeps it after reboot")
        add("firewall-cmd --list-all", "current zone settings")
    elif cmd == "tcpdump":
        for i, x in enumerate(a):
            if x == "-w" and i + 1 < len(a):
                add("tcpdump -nn -r %s | head -50" % _q(a[i + 1]), "read the capture")
    elif cmd in ("docker", "podman") and pos[:1] == ["run"]:
        add("%s ps" % cmd, "is it running?")
        add("%s logs -f $(%s ps -lq)" % (cmd, cmd), "follow the newest container's log")
    elif cmd in ("vi", "vim", "nano", "emacs", "sudoedit", "vimdiff") and pos:
        f = pos[-1]
        for rx, check, why in CONFIG_CHECKS:
            if rx.search(f) or rx.search(os.path.join(c.cwd, f)):
                add(check.replace("FILE", _q(f)), why)
                break
    elif cmd in ("chmod", "chown", "chgrp") and len(pos) > 1:
        add("ls -l %s" % _q(pos[-1]), "check the result")
    elif cmd == "ln" and pos:
        add("ls -l %s" % _q(pos[-1]), "check where the link points")
    elif cmd in ("gzip", "xz", "zstd", "bzip2") and pos and "-d" not in a:
        add("ls -lh %s*" % _q(pos[-1]), "compressed size")
    elif cmd == "crontab" and "-e" in a:
        add("crontab -l", "check what is installed now")
    elif cmd == "rpm" and any(x.startswith("-i") or x.startswith("-U") for x in a):
        for p in pos:
            if family_of(p) == "rpm":
                add("rpm -qip %s" % _q(p), "package info")
    return out


FOLDER_HINTS = [
    (re.compile(r"^/var/log(/|$)"), [("ls -lt | head", "most recently written logs"),
                                     ("tail -F messages", "follow the system log (RHEL); Debian: syslog")]),
    (re.compile(r"/(diag|trace)(/|$)"), [("ls -lt *.trc | head", "newest Oracle trace files"),
                                         ("tail -200 alert_*.log", "end of the Oracle alert log")]),
    (re.compile(r"^/etc/systemd/system"), [("systemctl daemon-reload", "after editing unit files"),
                                           ("systemctl list-unit-files --state=enabled", "what starts at boot")]),
    (re.compile(r"^/etc/yum\.repos\.d"), [("dnf repolist", "enabled repos")]),
    (re.compile(r"^/etc/nginx"), [("nginx -t", "check config syntax")]),
    (re.compile(r"^/etc/httpd|^/etc/apache2"), [("apachectl configtest", "check config syntax")]),
    (re.compile(r"^/etc/ssh"), [("sshd -t", "check sshd config syntax")]),
    (re.compile(r"^/etc(/|$)"), [("ls -lt | head", "most recently changed configs")]),
]


def _folder_rules(c):
    out = []
    add = lambda s, why: out.append((s, why))   # noqa: E731
    for rx, hints in FOLDER_HINTS:
        if rx.search(c.cwd):
            out.extend(hints)
            break
    f = c.newest("archive")
    if f:
        add("tar -tvf %s | head" % _q(f), "newest archive here: look inside")
    f = c.newest("zip")
    if f:
        add("unzip -l %s" % _q(f), "newest zip here: look inside")
    f = c.newest("rpm")
    if f:
        add("sudo dnf install ./%s" % f, "install the RPM in this folder")
    f = c.newest("log")
    if f:
        add("tail -F %s" % _q(f), "follow the newest log here")
    f = c.newest("pcap")
    if f:
        add("tcpdump -nn -r %s | head -50" % _q(f), "read the newest capture here")
    f = c.newest("csv")
    if f:
        add("column -s, -t < %s | less -S" % _q(f), "view the CSV as a table")
    names = set(n for n, _, _, _ in c.files)
    if "Makefile" in names:
        add("make -n", "dry-run the Makefile")
    if names & {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
        add("docker compose ps", "compose services here")
    if "Dockerfile" in names:
        add("docker build -t %s ." % _q(os.path.basename(c.cwd).lower() or "image"), "build the image here")
    if c.has(".git"):
        add("git status -sb", "git repo: what changed")
    f = c.newest("sh")
    if f and not os.access(os.path.join(c.cwd, f), os.X_OK):
        add("bash -n %s" % _q(f), "syntax-check the script (it isn't executable yet)")
    if len(c.files) >= 15:
        add("du -sh * 2>/dev/null | sort -h | tail", "biggest items in this folder")
    return out


def suggestions(ctx, kb=None, limit=12):
    """Ranked, de-duplicated [{"cmd","why","kind"}]. kind: fix | next | here."""
    out, seen = [], set()

    def push(items, kind):
        for cmd, why in items:
            if cmd and cmd not in seen:
                seen.add(cmd)
                out.append({"cmd": cmd, "why": why, "kind": kind})

    if ctx.cmd:
        if ctx.failed and ctx.status not in (130,):          # Ctrl+C is not a failure worth fixing
            push(_fail_rules(ctx, kb), "fix")
        elif ctx.status == 0:
            push(_ok_rules(ctx), "next")
    push(_folder_rules(ctx), "here")
    return out[:limit]


# ---------------------------------------------------------------- placeholder filling
TLDR_PH = re.compile(r"<([^<>]+)>")
CURATED_PH = {"archive.tar.gz": "archive", "archive.tar.xz": "archive", "archive.tar.zst": "archive", "x.tgz": "archive",
              "a.tgz": "archive", "app.tar.gz": "archive", "archive.zip": "zip", "file.log": "log", "app.log": "log",
              "access.log": "log", "cap.pcap": "pcap", "data.csv": "csv", "file.gz": "gz", "file.log.gz": "gz",
              "access.log.gz": "gz", "script.sh": "sh", "dir/": "@dir", "project/": "@dir"}


def fill(cmd, ctx):
    """Replace placeholders with real names from the current directory. Returns (cmd, changed)."""
    changed = [False]

    def pick(hint):
        h = hint.lower()
        if h == "@dir" or "directory" in h or h.endswith("/") or h in ("dir", "path/to/dir"):
            name = ctx.newest(dirs=True)
            return (name + "/") if name and h.endswith("/") else name
        fam = hint if hint in dict(EXT_FAMILIES) else family_of(h)
        if fam:
            return ctx.newest(fam)
        if h in ("path/to/file", "file", "filename", "path/to/file_or_directory"):
            return ctx.newest()
        return None

    def tldr_sub(m):
        name = pick(m.group(1))
        if name:
            changed[0] = True
            return _q(name)
        return m.group(0)

    toks = cmd.split(" ")
    protected = _output_positions(toks)
    for i, t in enumerate(toks):
        if i in protected:
            continue
        if TLDR_PH.search(t):
            toks[i] = TLDR_PH.sub(tldr_sub, t)
            continue
        fam = CURATED_PH.get(t)
        if fam:
            name = pick(fam)
            if name:
                toks[i] = _q(name) + ("/" if t.endswith("/") and not name.endswith("/") else "")
                changed[0] = True
    return " ".join(toks), changed[0]


OUTPUT_FLAGS = {"-o", "-O", "-w", "--output", "--output-document", "-of", ">", ">>", "of="}
CREATE_CMDS = {"zip": 1, "7z": 2, "7za": 2, "rar": 2, "mksquashfs": 2}


def _output_positions(toks):
    """Indices of tokens that name something the command WRITES. Never fill those with an existing
    file name: tar -czf archive.tar.gz would overwrite a real archive."""
    out = set()
    cmd = toks[0] if toks else ""
    for i, t in enumerate(toks):
        if t in OUTPUT_FLAGS and i + 1 < len(toks):
            out.add(i + 1)
        if cmd == "tar" and re.match(r"^-?[a-zA-Z]*[cru][a-zA-Z]*f$", t) and i + 1 < len(toks):
            out.add(i + 1)                       # tar -czf OUT / tar czf OUT / tar -rf OUT
        if t in ("-c", "--create") and cmd == "tar":
            for j in range(i + 1, len(toks) - 1):
                if toks[j] in ("-f", "--file"):
                    out.add(j + 1)
    if cmd in CREATE_CMDS:
        pos = [i for i, t in enumerate(toks[1:], 1) if not t.startswith("-")]
        k = CREATE_CMDS[cmd] - 1
        if len(pos) > k:
            out.add(pos[k])                      # zip OUT.zip files / 7z a OUT.7z files
    return out


def render_context(ctx, kb=None, color=True, limit=8):
    """Plain/ANSI text block for `??` and the TUI pane."""
    C = {"b": "\033[1m", "dim": "\033[2m", "ok": "\033[1;32m", "bad": "\033[1;31m", "cmd": "\033[1;33m", "r": "\033[0m"} \
        if color else {k: "" for k in ("b", "dim", "ok", "bad", "cmd", "r")}
    lines = []
    st = ctx.status_text()
    if ctx.last_cmd and st:
        tone = C["ok"] if not ctx.failed else C["bad"]
        lines.append("%sLast:%s %s  %s%s%s" % (C["b"], C["r"], ctx.last_cmd, tone, st, C["r"]))
    lines.append("%sHere:%s %s" % (C["dim"], C["r"], ctx.cwd))
    sug = suggestions(ctx, kb, limit)
    if sug:
        label = {"fix": "to investigate", "next": "next steps", "here": "in this folder"}
        cur = None
        for s in sug:
            if s["kind"] != cur:
                cur = s["kind"]
                lines.append("")
                lines.append("%s%s:%s" % (C["b"], label[cur].capitalize(), C["r"]))
            lines.append("  %s%s%s  %s# %s%s" % (C["cmd"], s["cmd"], C["r"], C["dim"], s["why"], C["r"]))
    return "\n".join(lines)
