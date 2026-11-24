#!/usr/bin/env python3
"""Build cmdhelp/data/kb.json from tldr-pages + curated entries + top500 ranking."""
import json, os, re, sys, glob, importlib

HERE = os.path.dirname(os.path.abspath(__file__))
TLDR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "tldr")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "cmdhelp", "data", "kb.json.gz")

# ---- ranking ----
rank, cats = [], {}
for line in open(os.path.join(HERE, "top500.txt")):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    c, names = line.split(":", 1)
    for n in names.split():
        if n not in cats:
            rank.append(n); cats[n] = c

# ---- tldr ----
FLAG_RE = re.compile(r"\{\{\[([^\]]+)\]\}\}")       # {{[-c|--create]}}
PH_RE = re.compile(r"\{\{(.*?)\}\}")                  # {{path/to/file}}
MNEMONIC_RE = re.compile(r"\[([^\]]+)\]")              # [c]reate -> c reate


def clean_cmd(s):
    # option alternatives: keep the short one, it's what people type
    s = FLAG_RE.sub(lambda m: m.group(1).split("|")[0], s)
    s = PH_RE.sub(lambda m: "<" + m.group(1) + ">" if not m.group(1).startswith("-") else m.group(1), s)
    return s


def clean_desc(s):
    return MNEMONIC_RE.sub(lambda m: m.group(1), s).rstrip(":").strip()


def short(text, n=4):
    w = re.sub(r"[`.,:;()]", "", text).split()
    return " ".join(w[:n]).lower()


def parse_tldr(path):
    name, desc, more, examples = None, [], None, []
    cur = None
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        if line.startswith("# "):
            name = line[2:].strip()
        elif line.startswith("> "):
            t = line[2:].strip()
            if t.startswith("More information"):
                m = re.search(r"<(.*?)>", t); more = m.group(1) if m else None
            elif not t.startswith("See also") and not t.startswith("Note") and not t.startswith("This command is an alias"):
                desc.append(t)
            elif t.startswith("This command is an alias"):
                desc.append(t)
        elif line.startswith("- "):
            cur = clean_desc(line[2:])
        elif line.startswith("`") and cur:
            raw_cmd = line.strip("`")
            flags = []
            for m in FLAG_RE.finditer(raw_cmd):
                flags.append(m.group(1).split("|"))
            examples.append({"desc": cur, "cmd": clean_cmd(raw_cmd), "flags": flags})
            cur = None
    return name, desc, more, examples


def tldr_compact(name, desc, more, examples):
    # compact form expanded at runtime by cmdhelp.kb.expand_tldr
    return {"t": 1, "d": desc, "u": more, "x": [[e["desc"], e["cmd"], ["|".join(a) for a in e["flags"]]] for e in examples]}


def tldr_entry(name, desc, more, examples):
    d0 = desc[0] if desc else name
    verbose = " ".join(desc) + (f" More: {more}" if more else "")
    flags = {}
    for ex in examples:
        for alts in ex["flags"]:
            key = alts[0]
            if key not in flags:
                flags[key] = {"names": alts, "arg": None, "min": short(ex["desc"], 3),
                              "normal": f"Used for: {ex['desc']}.", "verbose": f"Used for: {ex['desc']}. Example: {ex['cmd']}"}
    combos = [{"cmd": ex["cmd"], "min": short(ex["desc"]), "normal": ex["desc"] + ".",
               "verbose": ex["desc"] + ".", "tags": []} for ex in examples]
    return {"summary": {"min": short(d0, 4), "normal": d0, "verbose": verbose},
            "flags": list(flags.values()), "combos": combos, "pitfalls": [], "oldstyle": False,
            "subcommands": {}, "see": [], "source": "tldr", "url": more}


cmds = {}
# linux overrides common for same name
for platform in ("common", "linux"):
    for p in sorted(glob.glob(os.path.join(TLDR, "pages", platform, "*.md"))):
        name, desc, more, ex = parse_tldr(p)
        key = os.path.basename(p)[:-3]
        cmds[key] = (name or key, desc, more, ex)

# ---- curated merge ----
sys.path.insert(0, os.path.join(HERE, "curated"))
import _dsl  # noqa
for mod in sorted(glob.glob(os.path.join(HERE, "curated", "[!_]*.py"))):
    importlib.import_module(os.path.basename(mod)[:-3])

for name, cur in _dsl.REG.items():
    base = cmds.get(name)
    if base:
        base = tldr_entry(*base)
        # keep curated texts, append tldr examples not already present
        have = {c["cmd"] for c in cur["combos"]}
        extra = [c for c in base["combos"] if c["cmd"] not in have]
        for c in extra:
            c["tags"] = ["tldr"]
        cur["combos"] += extra
        names = {n for f in cur["flags"] for n in f["names"]}
        cur["flags"] += [f for f in base["flags"] if not set(f["names"]) & names]
        cur["url"] = base.get("url")
    cur["source"] = "curated+tldr" if base else "curated"
    cmds[name] = cur

# compact everything not curated
for k, v in list(cmds.items()):
    if isinstance(v, tuple):
        cmds[k] = tldr_compact(*v)

# subcommand pages: git-commit -> git's subcommands
for key in list(cmds):
    if "-" in key:
        parent, sub = key.split("-", 1)
        if parent in cmds and "-" not in sub:
            par = cmds[parent]; child = cmds[key]
            text = child["d"][0] if child.get("t") else child["summary"]["normal"]
            par.setdefault("s" if par.get("t") else "subcommands", {}).setdefault(sub, text)

for n, e in cmds.items():
    if cats.get(n):
        e["category"] = cats[n]

os.makedirs(os.path.dirname(OUT), exist_ok=True)
kb = {"version": 1, "rank": rank, "categories": cats, "cmds": cmds}
import gzip
with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as fh:
    json.dump(kb, fh, ensure_ascii=False, separators=(",", ":"))
print(f"commands: {len(cmds)}  curated: {len(_dsl.REG)}  ranked: {len(rank)}  size: {os.path.getsize(OUT)//1024} KiB")
