"""Explain a full command line token by token, in min / normal / verbose mode."""
import re

from .kb import PREFIX_CMDS

SEP_TOKENS = {"|": "pipe: send stdout of the left command to stdin of the right",
              "||": "OR: run the right side only if the left failed",
              "&&": "AND: run the right side only if the left succeeded",
              ";": "then: run the next command regardless",
              "&": "run in background",
              "|&": "pipe stdout and stderr"}
REDIR = {">": "redirect stdout to file (overwrite)", ">>": "append stdout to file",
         "<": "read stdin from file", "2>": "redirect stderr to file", "2>&1": "send stderr to wherever stdout goes",
         "&>": "redirect stdout+stderr to file", "2>/dev/null": "discard error messages", ">/dev/null": "discard output",
         "<<": "here-document", "<<<": "here-string"}
REDIR_RE = re.compile(r"^(\d*(>>?|<|>\||<<<?)|&>>?)(&[\d-]+)?$|^\d*[<>]&[\d-]+$")
PREFIX_TEXT = {"sudo": "run as root (or -u user)", "time": "measure run time", "nohup": "keep running after logout",
               "nice": "run with lower CPU priority", "ionice": "run with I/O priority", "watch": "re-run every 2s and show output",
               "env": "run with modified environment", "exec": "replace the shell with the command", "timeout": "kill after a time limit",
               "doas": "run as root", "command": "bypass aliases/functions", "strace": "trace system calls", "xargs": "build args from stdin",
               "builtin": "run a shell builtin", "chroot": "run in another root dir"}


# Longest operators first. Same behaviour on every Python version (shlex only splits
# operators glued to words, like a|b or 2>/dev/null, from Python 3.8 on).
OPERATORS = ("<<<", "&>>", "||", "&&", "|&", ";;", ">>", "<<", ">&", "<&", "&>", ">|", "|", "&", ";", "<", ">")


def tokenize(line):
    r"""Small POSIX-shell lexer: words (quotes removed, escapes resolved) and operator tokens.

    Redirect fds are glued to their operator (2>, 2>&1, &>). find's \; is kept as the word \;
    so it is not mistaken for a command separator. An unterminated quote (normal while typing)
    falls back to a plain whitespace split.
    """
    toks, cur, have = [], [], False
    i, n = 0, len(line)

    def flush():
        if have:
            toks.append("".join(cur))
        del cur[:]

    while i < n:
        c = line[i]
        if c in " \t\n":
            flush(); have = False
            i += 1
            continue
        if c == "\\":
            if i + 1 < n and line[i + 1] == ";":
                cur.append("\\;")
            elif i + 1 < n:
                cur.append(line[i + 1])
            have = True
            i += 2
            continue
        if c == "'":
            j = line.find("'", i + 1)
            if j < 0:
                return line.split()
            cur.append(line[i + 1:j]); have = True
            i = j + 1
            continue
        if c == '"':
            j, buf = i + 1, []
            while j < n and line[j] != '"':
                if line[j] == "\\" and j + 1 < n and line[j + 1] in '"\\$`':
                    buf.append(line[j + 1]); j += 2
                else:
                    buf.append(line[j]); j += 1
            if j >= n:
                return line.split()
            cur.append("".join(buf)); have = True
            i = j + 1
            continue
        op = next((o for o in OPERATORS if line.startswith(o, i)), None)
        if op:
            word = "".join(cur)
            fd = ""
            if have and word.isdigit() and op[0] in "<>":
                fd = word                      # 2> 1>> 0<
                del cur[:]; have = False
            flush(); have = False
            i += len(op)
            if op in (">&", "<&"):              # >&2  2>&1  2>&-
                k = i
                while k < n and (line[k].isdigit() or line[k] == "-"):
                    k += 1
                op += line[i:k]
                i = k
            toks.append(fd + op)
            continue
        cur.append(c); have = True
        i += 1
    flush()
    return toks


def split_segments(tokens):
    seg, out = [], []
    for t in tokens:
        if t in SEP_TOKENS:
            out.append((seg, None))
            out.append(([], t))
            seg = []
        else:
            seg.append(t)
    out.append((seg, None))
    return out


class FlagIndex(object):
    def __init__(self, entry):
        self.by = {}
        for f in entry.get("flags", []):
            for n in f["names"]:
                self.by.setdefault(n, f)
            # oldstyle letters: tar 'x', ps 'a'
            for n in f["names"]:
                if len(n) == 1 and n.isalpha():
                    self.by.setdefault(n, f)

    def get(self, n):
        return self.by.get(n)


def _txt(f, mode):
    return f.get(mode) or f.get("normal") or ""


def explain_segment(kb, tokens, mode, man="sync"):
    """Return list of (token, kind, text) tuples."""
    rows = []
    i = 0
    # prefixes: sudo, VAR=val, time ...
    while i < len(tokens) and (tokens[i] in PREFIX_CMDS or re.match(r"^[A-Za-z_]\w*=", tokens[i])):
        t = tokens[i]
        if "=" in t and t not in PREFIX_CMDS:
            rows.append((t, "env", "set env var " + t.split("=")[0] + " for this command"))
        else:
            rows.append((t, "prefix", PREFIX_TEXT.get(t, "wrapper")))
            # swallow wrapper's own options (sudo -u x, timeout 5)
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                opt = tokens[i]
                rows.append((opt, "prefix-opt", "option for " + t))
                if t == "sudo" and opt in ("-u", "-g") and i + 1 < len(tokens):
                    i += 1
                    rows.append((tokens[i], "arg", "user/group"))
                i += 1
            if t in ("timeout", "nice") and i < len(tokens) and re.match(r"^[\d.]+[smhd]?$", tokens[i]):
                rows.append((tokens[i], "arg", "duration" if t == "timeout" else "niceness"))
                i += 1
            continue
        i += 1
    if i >= len(tokens):
        return rows, None
    cmd = tokens[i].split("/")[-1]
    entry = kb.get(cmd, man=man)
    name_used = cmd
    i += 1
    # subcommand: git commit -> git-commit page
    if entry and i < len(tokens) and not tokens[i].startswith("-"):
        sub = tokens[i]
        if kb.has(cmd + "-" + sub):
            rows.append((tokens[i - 1], "cmd", (kb.summary(cmd, mode) if mode != "min" else kb.summary(cmd, "min"))))
            entry = kb.get(cmd + "-" + sub, man=man)
            name_used = cmd + "-" + sub
            rows.append((sub, "sub", entry["summary"][mode]))
            i += 1
        else:
            rows.append((tokens[i - 1], "cmd", entry["summary"][mode]))
            if sub in entry.get("subcommands", {}):
                rows.append((sub, "sub", entry["subcommands"][sub]))
                i += 1
    elif entry:
        rows.append((tokens[i - 1], "cmd", entry["summary"][mode]))
    else:
        rows.append((tokens[i - 1], "cmd", "(unknown command)"))
        entry = {"flags": [], "subcommands": {}, "oldstyle": False}   # still explain redirects/args
        name_used = None

    idx = FlagIndex(entry)
    if name_used and name_used != cmd and kb.get(cmd, man=man):   # subcommand page: fall back to parent's global options
        parent = FlagIndex(kb.get(cmd, man=man))
        for k, v in parent.by.items():
            idx.by.setdefault(k, v)
    first_positional = True
    while i < len(tokens):
        t = tokens[i]
        if t in REDIR or REDIR_RE.match(t):
            dup = re.search(r"[<>]&[\d-]+$", t)          # 2>&1, >&2, 3>&-: no separate target
            rows.append((t, "redir", REDIR.get(t) or ("duplicate/close a file descriptor" if dup else "redirection")))
            if i + 1 < len(tokens) and not dup:
                i += 1
                rows.append((tokens[i], "arg", "target"))
            i += 1
            continue
        if t == "--":
            rows.append((t, "sep", "end of options: everything after is a plain argument"))
            for r in tokens[i + 1:]:
                rows.append((r, "arg", "argument"))
            break
        if t.startswith("--"):
            name, _, val = t.partition("=")
            f = idx.get(name)
            if f:
                rows.append((t, "flag", _txt(f, mode)))
                if f.get("arg") and not val and i + 1 < len(tokens):
                    i += 1
                    rows.append((tokens[i], "arg", "value for " + name))
            else:
                rows.append((t, "flag?", "option (not in knowledge base, see man %s)" % cmd))
            i += 1
            continue
        if t.startswith("-") and len(t) > 1 and not re.match(r"^-\d+(\.\d+)?$", t) or (
                entry.get("oldstyle") and first_positional and re.match(r"^[a-zA-Z]+$", t) and not idx.get(t)
                and all(idx.get("-" + c) or idx.get(c) for c in t)):
            f = idx.get(t)
            if f and re.match(r"^-[a-zA-Z]{2,}$", t) and all(idx.get("-" + ch) for ch in t[1:]) and t not in ("-nn", "-vv", "-vvv", "-XX"):
                f = None  # a bundle tldr recorded as one flag (-ltr): explain letter by letter
            if f:  # whole token is a flag (-nn, -name, -print0, -exec)
                rows.append((t, "flag", _txt(f, mode)))
                if f.get("arg") and i + 1 < len(tokens):
                    if t in ("-exec", "-execdir", "-ok"):
                        j = i + 1
                        parts = []
                        while j < len(tokens) and tokens[j] not in (";", "\\;", "+"):
                            parts.append(tokens[j]); j += 1
                        rows.append((" ".join(parts), "arg", "command run per file ({} = the file)"))
                        if j < len(tokens):
                            rows.append((tokens[j], "arg", "end of -exec (+ batches files, ; runs once per file)"))
                        i = j + 1
                        continue
                    i += 1
                    rows.append((tokens[i], "arg", "value for " + t))
                i += 1
                first_positional = False if not t.startswith("-") else first_positional
                continue
            letters = t[1:] if t.startswith("-") else t
            k = 0
            while k < len(letters):
                c = letters[k]
                if t.startswith("-"):
                    f = idx.get("-" + c)
                else:  # BSD/old style bundle (ps aux, tar xzf): bare letter first
                    f = idx.get(c) or idx.get("-" + c)
                label = ("-" + c) if t.startswith("-") else c
                if f:
                    rows.append((label, "flag", _txt(f, mode)))
                    if f.get("arg"):
                        rest = letters[k + 1:]
                        if rest:
                            rows.append((rest, "arg", "value for -" + c))
                        elif i + 1 < len(tokens):
                            i += 1
                            rows.append((tokens[i], "arg", "value for -" + c))
                        break
                else:
                    rows.append((label, "flag?", "unknown option"))
                k += 1
            if not t.startswith("-"):
                first_positional = False
            i += 1
            continue
        # positional
        if first_positional and t in entry.get("subcommands", {}):
            rows.append((t, "sub", entry["subcommands"][t]))
        else:
            rows.append((t, "arg", _guess_arg(t, cmd)))
        first_positional = False
        i += 1
    return rows, name_used


BPF = {"host": "BPF: match this host (src or dst)", "net": "BPF: match a network/CIDR", "port": "BPF: match this port (src or dst)",
       "portrange": "BPF: port range a-b", "src": "BPF: source direction", "dst": "BPF: destination direction",
       "and": "BPF: logical AND", "or": "BPF: logical OR", "not": "BPF: negate", "tcp": "BPF: TCP only", "udp": "BPF: UDP only",
       "icmp": "BPF: ICMP only", "arp": "BPF: ARP only", "ip": "BPF: IPv4", "ip6": "BPF: IPv6", "vlan": "BPF: 802.1Q VLAN",
       "ether": "BPF: MAC-level match", "greater": "BPF: packet length >=", "less": "BPF: packet length <="}


def _guess_arg(t, cmd=None):
    if cmd in ("tcpdump", "tshark", "ngrep") and t.lower() in BPF:
        return BPF[t.lower()]
    if re.match(r"^\d+\.\d+\.\d+\.\d+(/\d+)?$", t):
        return "IP address / network"
    if re.match(r"^https?://", t):
        return "URL"
    if re.search(r"\.(tar\.gz|tgz|tar\.xz|tar\.bz2|tar\.zst|tar|zip|gz|xz|bz2|zst|7z)$", t):
        return "archive file"
    if "@" in t and ":" in t:
        return "remote user@host:path"
    if "@" in t:
        return "user@host"
    if t.startswith(("/", "./", "~", "../")) or "/" in t:
        return "path"
    if "*" in t or "?" in t:
        return "glob pattern (quote it if the command should see it)"
    if t.startswith("'") or t.startswith('"'):
        return "quoted string"
    return "argument"


def explain(kb, line, mode="normal", man="sync"):
    """Return dict: rows per segment + related pitfalls/combos for verbose mode."""
    toks = tokenize(line)
    result = {"segments": [], "pitfalls": [], "related": [], "see": []}
    for seg, sep in split_segments(toks):
        if sep:
            result["segments"].append({"sep": sep, "text": SEP_TOKENS[sep]})
            continue
        if not seg:
            continue
        rows, name = explain_segment(kb, seg, mode, man)
        result["segments"].append({"rows": rows, "cmd": name})
        if name:
            e = kb.get(name, man=man)
            result["pitfalls"] += [(name, p) for p in e.get("pitfalls", [])]
            result["see"] += e.get("see", [])
            used = set(r[0] for r in rows if r[1] == "flag")
            scored = []
            for c in e.get("combos", []):
                ctoks = set(tokenize(c["cmd"]))
                letters = set()
                for x in ctoks:
                    if re.match(r"^-[a-zA-Z]+$", x):
                        letters |= set("-" + ch for ch in x[1:])
                s = len(used & (ctoks | letters))
                if s:
                    scored.append((s, c))
            scored.sort(key=lambda x: -x[0])
            result["related"] += [c for _, c in scored[:4]]
    return result


# ---------- plain-text / ANSI rendering (used by `cmdhelp explain` and fallback mode) ----------
C = {"cmd": "\033[1;36m", "sub": "\033[1;36m", "flag": "\033[1;33m", "flag?": "\033[33m", "arg": "\033[32m",
     "redir": "\033[35m", "prefix": "\033[1;35m", "prefix-opt": "\033[35m", "env": "\033[35m", "sep": "\033[1;34m",
     "dim": "\033[2m", "warn": "\033[1;31m", "r": "\033[0m", "b": "\033[1m"}


def render_text(kb, line, mode="normal", color=True, man="sync"):
    c = C if color else {k: "" for k in C}
    res = explain(kb, line, mode, man)
    out = []
    if mode == "min":
        parts = []
        for s in res["segments"]:
            if "sep" in s:
                parts.append(c["sep"] + s["sep"] + c["r"])
                continue
            for tok, kind, text in s["rows"]:
                if kind == "arg" and not text.startswith("value"):
                    parts.append(c["arg"] + tok + c["r"])
                else:
                    parts.append("%s%s%s %s(%s)%s" % (c.get(kind, ""), tok, c["r"], c["dim"], text, c["r"]))
        return "  ".join(parts)
    width = 4
    for s in res["segments"]:
        for tok, kind, text in s.get("rows", []):
            width = max(width, min(len(tok), 28))
    for s in res["segments"]:
        if "sep" in s:
            out.append("%s%s%s  %s%s%s" % (c["sep"], s["sep"].ljust(width), c["r"], c["dim"], s["text"], c["r"]))
            continue
        for tok, kind, text in s["rows"]:
            indent = "" if kind in ("cmd", "prefix", "env") else "  "
            out.append("%s%s%s%s  %s" % (indent, c.get(kind, ""), tok.ljust(width - len(indent)), c["r"], text))
    if mode == "verbose":
        if res["pitfalls"]:
            out.append("")
            out.append(c["warn"] + "Watch out:" + c["r"])
            for name, p in res["pitfalls"]:
                out.append("  - %s" % p)
        if res["related"]:
            out.append("")
            out.append(c["b"] + "Related ready-made combos:" + c["r"])
            for r in res["related"]:
                out.append("  %s%s%s  %s" % (c["flag"], r["cmd"], c["r"], r["normal"]))
        if res["see"]:
            out.append("")
            out.append(c["dim"] + "See also: " + ", ".join(dict.fromkeys(res["see"])) + c["r"])
    return "\n".join(out)


def render_command(kb, name, mode="normal", color=True, limit=None, man="sync"):
    """Cheat-sheet view of one command."""
    c = C if color else {k: "" for k in C}
    e = kb.get(name, man=man)
    if not e:
        return "No entry for '%s'." % name
    out = ["%s%s%s  %s" % (c["cmd"], name, c["r"], e["summary"][mode]), ""]
    combos = e.get("combos", [])
    if limit is None:
        limit = {"min": 8, "normal": 15, "verbose": 100}[mode]
    if combos:
        out.append(c["b"] + "Use cases:" + c["r"])
        w = min(max(len(x["cmd"]) for x in combos[:limit]), 60)
        for x in combos[:limit]:
            if mode == "min":
                out.append("  %s%s%s  %s# %s%s" % (c["flag"], x["cmd"].ljust(w), c["r"], c["dim"], x["min"], c["r"]))
            elif mode == "normal":
                out.append("  %s%s%s\n      %s" % (c["flag"], x["cmd"], c["r"], x["normal"]))
            else:
                out.append("  %s%s%s\n      %s" % (c["flag"], x["cmd"], c["r"], x["verbose"]))
        out.append("")
    flags = e.get("flags", [])
    if flags and mode != "min":
        out.append(c["b"] + "Options:" + c["r"])
        flimit = 40 if mode == "normal" else 400
        for f in flags[:flimit]:
            n = ", ".join(f["names"]) + ((" " + f["arg"]) if f.get("arg") else "")
            out.append("  %s%-28s%s %s" % (c["flag"], n, c["r"], f[mode] if mode in f else f["normal"]))
        if len(flags) > flimit:
            out.append(c["dim"] + "  ... %d more (verbose mode shows all)" % (len(flags) - flimit) + c["r"])
        out.append("")
    if mode == "verbose" and e.get("subcommands"):
        out.append(c["b"] + "Subcommands:" + c["r"])
        for k, v in sorted(e["subcommands"].items()):
            out.append("  %s%-18s%s %s" % (c["sub"], k, c["r"], v))
        out.append("")
    if mode == "verbose" and e.get("pitfalls"):
        out.append(c["warn"] + "Watch out (common StackOverflow/ServerFault traps):" + c["r"])
        for p in e["pitfalls"]:
            out.append("  - " + p)
        out.append("")
    if mode == "verbose" and e.get("see"):
        out.append(c["dim"] + "See also: " + ", ".join(e["see"]) + c["r"])
    return "\n".join(out).rstrip()
