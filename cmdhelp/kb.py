"""Knowledge base: loading, tldr expansion, history ranking, man-page flag parsing.

Python 3.6+ compatible, stdlib only.
"""
import gzip
import io
import json
import os
import pkgutil
import re
import subprocess
import tempfile
import threading
from collections import Counter

MODES = ("min", "normal", "verbose")
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "cmdhelp")
MAN_CACHE_FILE = "man_flags.v2.json"
PARSER_VERSION = 2          # bump when parse_man_text changes: invalidates every cached entry
MAN_TIMEOUT = 4
PREFIX_CMDS = {"sudo", "doas", "time", "nohup", "nice", "ionice", "watch", "env", "exec", "command", "builtin", "xargs", "timeout", "strace", "chroot"}


def _short(text, n=4):
    w = re.sub(r"[`.,:;()]", "", text).split()
    return " ".join(w[:n]).lower()


def _load_raw():
    data = pkgutil.get_data("cmdhelp", "data/kb.json.gz")
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as fh:
        return json.loads(fh.read().decode("utf-8"))


class KB(object):
    def __init__(self):
        raw = _load_raw()
        self.rank = raw["rank"]
        self.rank_pos = {n: i for i, n in enumerate(self.rank)}
        self.categories = raw["categories"]
        self._raw = raw["cmds"]
        self._expanded = {}          # name -> entry without man flags
        self._merged = {}            # name -> (flags list id, merged entry)
        self._man_lock = threading.RLock()
        self._man_disk = None        # lazily loaded disk cache {"v":..,"cmds":{name:{path,mtime,flags}}}
        self._man_valid = {}         # name -> flags, validated against the man page during this process
        self._man_pending = set()
        self.history = Counter()
        self._load_history()
        self.names = sorted(self._raw)

    # ---------- entries ----------
    def has(self, name):
        return name in self._raw

    def get(self, name, man="sync"):
        """Return the entry for a command.

        man="sync"   parse/validate the man page now if needed (CLI explain / cheat sheet)
        man="cached" use man flags only if already known; never blocks (TUI, while typing)
        man="none"   curated + tldr data only
        """
        if name not in self._raw:
            return None
        if name not in self._expanded:
            e = self._raw[name]
            if e.get("t"):
                e = self._expand_tldr(name, e)
            self._expanded[name] = e
        base = self._expanded[name]
        if man == "none" or not re.match(r"^[\w.+-]+$", name):
            return base
        flags = self.man_flags(name) if man == "sync" else self.cached_man_flags(name)
        if not flags:
            return base
        hit = self._merged.get(name)
        if hit and hit[0] is flags:
            return hit[1]
        merged = merge_man_flags(base, flags)
        self._merged[name] = (flags, merged)
        return merged

    def _expand_tldr(self, name, e):
        desc = e.get("d") or [name]
        d0 = desc[0]
        flags, combos = {}, []
        for ex_desc, ex_cmd, ex_flags in e.get("x", []):
            for alts in ex_flags:
                names = alts.split("|")
                if names[0] not in flags:
                    takes = any(re.search(re.escape(n) + r"""(\s+["']?<|=<)""", ex_cmd) for n in names)
                    flags[names[0]] = {"names": names, "arg": "VALUE" if takes else None, "min": _short(ex_desc, 3),
                                       "normal": "Used for: %s." % ex_desc,
                                       "verbose": "Used for: %s. Example: %s" % (ex_desc, ex_cmd)}
            combos.append({"cmd": ex_cmd, "min": _short(ex_desc), "normal": ex_desc + ".", "verbose": ex_desc + ".", "tags": []})
        verbose = " ".join(desc) + ((" More: " + e["u"]) if e.get("u") else "")
        return {"summary": {"min": _short(d0), "normal": d0, "verbose": verbose},
                "flags": list(flags.values()), "combos": combos, "pitfalls": [], "oldstyle": False,
                "subcommands": e.get("s", {}), "see": [], "source": "tldr", "url": e.get("u"),
                "category": e.get("category")}

    def summary(self, name, mode):
        e = self._raw.get(name)
        if e is None:
            return ""
        if e.get("t"):
            d = (e.get("d") or [name])[0]
            return _short(d) if mode == "min" else d
        return e["summary"]["min" if mode == "min" else "normal"]

    # ---------- ranking ----------
    def _load_history(self):
        files = [os.path.expanduser(p) for p in ("~/.bash_history", "~/.zsh_history", "~/.local/share/fish/fish_history")]
        hf = os.environ.get("HISTFILE")
        if hf:
            files.append(hf)
        for f in set(files):
            try:
                with open(f, "rb") as fh:
                    data = fh.read()[-2000000:].decode("utf-8", "replace")
            except (IOError, OSError):
                continue
            for line in data.splitlines():
                if line.startswith(": ") and ";" in line:      # zsh extended history
                    line = line.split(";", 1)[1]
                if line.startswith("- cmd: "):                  # fish
                    line = line[7:]
                for seg in re.split(r"\|\|?|&&|;", line):
                    toks = seg.split()
                    while toks and (toks[0] in PREFIX_CMDS or "=" in toks[0]):
                        toks = toks[1:]
                    if toks:
                        self.history[os.path.basename(toks[0])] += 1

    def score(self, name):
        """Lower is better."""
        h = self.history.get(name, 0)
        r = self.rank_pos.get(name, 5000)
        return (-min(h, 1000) * 3) + r

    def ranked_names(self, prefix=""):
        cand = [n for n in self.names if n.startswith(prefix)] if prefix else list(self.rank)
        return sorted(cand, key=self.score)

    # ---------- man page flags (never executes the target program) ----------
    def _load_disk(self):
        if self._man_disk is None:
            data = {}
            try:
                with open(os.path.join(CACHE_DIR, MAN_CACHE_FILE)) as fh:
                    data = json.load(fh)
            except (IOError, OSError, ValueError):
                data = {}
            if not isinstance(data, dict) or data.get("v") != PARSER_VERSION or not isinstance(data.get("cmds"), dict):
                data = {"v": PARSER_VERSION, "cmds": {}}
            self._man_disk = data
            try:  # v1 cache had no invalidation; drop it
                os.unlink(os.path.join(CACHE_DIR, "man_flags.json"))
            except OSError:
                pass
        return self._man_disk

    def _save_disk(self):
        """Atomic write: temp file in the same dir, then os.replace."""
        try:
            if not os.path.isdir(CACHE_DIR):
                os.makedirs(CACHE_DIR, 0o700)
            fd, tmp = tempfile.mkstemp(prefix=".man_flags.", dir=CACHE_DIR)
            try:
                with os.fdopen(fd, "w") as fh:
                    json.dump(self._man_disk, fh)
                os.replace(tmp, os.path.join(CACHE_DIR, MAN_CACHE_FILE))
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except (IOError, OSError):
            pass

    def cached_man_flags(self, name):
        """Non-blocking: flags validated in this process, else the (unvalidated) disk copy, else None."""
        with self._man_lock:
            if name in self._man_valid:
                return self._man_valid[name]
            rec = self._load_disk()["cmds"].get(name)
            return rec.get("flags") if rec else None

    def man_flags(self, name):
        """Blocking: validate the cache against the man page's path+mtime, re-parse if stale."""
        with self._man_lock:
            if name in self._man_valid:
                return self._man_valid[name]
        path = man_path(name)
        mtime = _mtime(path)
        with self._man_lock:
            rec = self._load_disk()["cmds"].get(name)
            if rec and rec.get("path") == path and rec.get("mtime") == mtime:
                self._man_valid[name] = rec.get("flags") or []
                return self._man_valid[name]
        flags = parse_man_text(read_man(name)) if path else []
        with self._man_lock:
            self._load_disk()["cmds"][name] = {"path": path, "mtime": mtime, "flags": flags}
            self._man_valid[name] = flags
            self._save_disk()
        return flags

    def enrich_async(self, name, callback=None):
        """Validate/parse man flags in a background thread; call callback() if they changed."""
        if not name or not re.match(r"^[\w.+-]+$", name) or name not in self._raw:
            return
        with self._man_lock:
            if name in self._man_valid or name in self._man_pending:
                return
            self._man_pending.add(name)
        before = self.cached_man_flags(name)

        def work():
            try:
                after = self.man_flags(name)
                if callback and after != before:
                    callback()
            except Exception:
                pass
            finally:
                with self._man_lock:
                    self._man_pending.discard(name)
        t = threading.Thread(target=work, name="cmdhelp-man-" + name)
        t.daemon = True
        t.start()
        return t


def merge_man_flags(base, man):
    """Return a NEW entry: base flags first (curated/tldr win), man flags added; tldr texts upgraded."""
    e = dict(base)
    flags = [dict(f) for f in base["flags"]]
    have = set(n for f in flags for n in f["names"])
    extra = []
    for f in man:
        fn = set(f["names"])
        if fn & have:
            if base.get("source") == "tldr":
                for g in flags:
                    if set(g["names"]) & fn:
                        g["normal"] = f["normal"]
                        g["verbose"] = f["verbose"]
                        if f.get("arg") and not g.get("arg"):
                            g["arg"] = f["arg"]
            continue
        extra.append(f)
    e["flags"] = flags + extra
    e["man_flags"] = len(man)
    return e


def _man_env():
    return dict(os.environ, MANWIDTH="160", MANPAGER="cat", PAGER="cat", LANG="C", LC_ALL="C",
                MAN_KEEP_FORMATTING="0", GROFF_NO_SGR="1")


def _mtime(path):
    try:
        return int(os.stat(path).st_mtime) if path else None
    except OSError:
        return None


def man_path(name):
    """Path of the man page source (man -w), or None. Cheap: no rendering."""
    try:
        p = subprocess.Popen(["man", "-w", name], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_man_env())
        out, _ = p.communicate(timeout=MAN_TIMEOUT)
        path = out.decode("utf-8", "replace").strip().splitlines()
        return path[0] if p.returncode == 0 and path else None
    except Exception:
        return None


def read_man(name):
    try:
        p = subprocess.Popen(["man", name], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_man_env())
        try:
            out, _ = p.communicate(timeout=MAN_TIMEOUT)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            return ""
        text = out.decode("utf-8", "replace")
    except Exception:
        return ""
    text = re.sub(r".\x08", "", text)            # overstrike bold/underline
    return re.sub(r"\x1b\[[0-9;]*m", "", text)   # SGR colors


FLAG_LINE = re.compile(r"^\s{1,14}((?:-{1,2}[\w?#][\w.+-]*(?:[= ]?\[?[<A-Za-z_][\w|<>.-]*\]?)?(?:,\s*|\s+or\s+|\s*\|\s*|\s(?=-))?)+)(?:\s{2,}|\t|$)(.*)")
NAME_RE = re.compile(r"-{1,2}[\w?#][\w.+-]*")
ARG_RE = re.compile(r"(?:=|\s)\[?(<?[A-Za-z_][\w|<>.-]*>?)\]?")


def parse_man(name):
    """Convenience: render + parse a man page."""
    return parse_man_text(read_man(name))


def parse_man_text(text):
    """Best-effort extraction of options from rendered man text. Never raises; [] on anything odd."""
    if not text or not text.strip():
        return []
    try:
        return _parse_lines(text.splitlines())
    except Exception:
        return []


def _parse_lines(lines):
    flags, seen = [], set()
    i = 0
    while i < len(lines):
        m = FLAG_LINE.match(lines[i])
        if m:
            spec, desc = m.group(1), m.group(2).strip()
            names = [n for n in NAME_RE.findall(spec)]
            argm = ARG_RE.search(spec[len(names[0]):] if names else "")
            j = i + 1
            ind = len(lines[i]) - len(lines[i].lstrip())
            while j < len(lines) and lines[j].strip() and (len(lines[j]) - len(lines[j].lstrip())) > ind and not FLAG_LINE.match(lines[j]):
                desc += " " + lines[j].strip()
                j += 1
                if len(desc) > 600:
                    break
            desc = re.sub(r"\s+", " ", desc).strip()
            key = tuple(names)
            if names and desc and key not in seen and len(names) <= 4:
                seen.add(key)
                first = re.split(r"(?<=[.;])\s", desc, maxsplit=1)[0]
                flags.append({"names": names, "arg": argm.group(1) if argm else None,
                              "min": _short(first, 3), "normal": first[:160], "verbose": desc[:600], "from": "man"})
            i = j
            continue
        i += 1
    return flags[:300]
