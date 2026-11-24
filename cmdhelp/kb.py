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
from collections import Counter

MODES = ("min", "normal", "verbose")
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "cmdhelp")
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
        self._expanded = {}
        self._man_cache = None
        self.history = Counter()
        self._load_history()
        self.names = sorted(self._raw)

    # ---------- entries ----------
    def has(self, name):
        return name in self._raw

    def get(self, name):
        if name not in self._raw:
            return None
        if name not in self._expanded:
            e = self._raw[name]
            if e.get("t"):
                e = self._expand_tldr(name, e)
            e = dict(e)
            self._merge_man_flags(name, e)
            self._expanded[name] = e
        return self._expanded[name]

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

    # ---------- man page flag extraction (no execution of the target program) ----------
    def _man_flags(self, name):
        if self._man_cache is None:
            self._man_cache = {}
            try:
                with open(os.path.join(CACHE_DIR, "man_flags.json")) as fh:
                    self._man_cache = json.load(fh)
            except (IOError, OSError, ValueError):
                pass
        if name in self._man_cache:
            return self._man_cache[name]
        flags = parse_man(name)
        self._man_cache[name] = flags
        try:
            if not os.path.isdir(CACHE_DIR):
                os.makedirs(CACHE_DIR)
            with open(os.path.join(CACHE_DIR, "man_flags.json"), "w") as fh:
                json.dump(self._man_cache, fh)
        except (IOError, OSError):
            pass
        return flags

    def _merge_man_flags(self, name, e):
        if not re.match(r"^[\w.+-]+$", name):
            return
        have = set(n for f in e["flags"] for n in f["names"])
        man = self._man_flags(name)
        extra = []
        for f in man:
            if set(f["names"]) & have:
                # enrich tldr-derived flag with the real man description
                for g in e["flags"]:
                    if set(g["names"]) & set(f["names"]) and e.get("source") == "tldr":
                        g["normal"] = f["normal"]
                        g["verbose"] = f["verbose"]
                continue
            extra.append(f)
        e["flags"] = e["flags"] + extra
        e["man_flags"] = len(man)


FLAG_LINE = re.compile(r"^\s{1,14}((?:-{1,2}[\w?#][\w.+-]*(?:[= ]?\[?[<A-Za-z_][\w|<>.-]*\]?)?(?:,\s*|\s+or\s+|\s*\|\s*|\s(?=-))?)+)(?:\s{2,}|\t|$)(.*)")
NAME_RE = re.compile(r"-{1,2}[\w?#][\w.+-]*")
ARG_RE = re.compile(r"(?:=|\s)\[?(<?[A-Za-z_][\w|<>.-]*>?)\]?")


def parse_man(name):
    """Extract option names + descriptions from the local man page (or --help for a few safe tools)."""
    text = ""
    env = dict(os.environ, MANWIDTH="160", MANPAGER="cat", PAGER="cat", LANG="C", LC_ALL="C", MAN_KEEP_FORMATTING="0", GROFF_NO_SGR="1")
    try:
        p = subprocess.Popen(["man", name], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        out, _ = p.communicate(timeout=4)
        text = out.decode("utf-8", "replace")
        text = re.sub(r".\x08", "", text)  # strip overstrike bold/underline
        text = re.sub(r"\x1b\[[0-9;]*m", "", text)  # strip SGR colors
    except Exception:
        text = ""
    if not text.strip():
        return []
    lines = text.splitlines()
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
                first = re.split(r"(?<=[.;])\s", desc, 1)[0]
                flags.append({"names": names, "arg": argm.group(1) if argm else None,
                              "min": _short(first, 3), "normal": first[:160], "verbose": desc[:600], "from": "man"})
            i = j
            continue
        i += 1
    return flags[:300]
