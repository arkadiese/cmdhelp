"""Tiny authoring DSL for curated entries.

Every text field has three levels:
  min     - 1-4 words, for people who know the tool and just need a reminder
  normal  - one clear sentence
  verbose - full explanation, why/when, example, gotchas
"""

REG = {}


def F(names, minimal, normal, verbose=None, arg=None):
    """A flag. names: space separated aliases, e.g. '-z --gzip'."""
    return {"names": names.split(), "arg": arg, "min": minimal,
            "normal": normal, "verbose": verbose or normal}


def C(cmd, minimal, normal, verbose=None, tags=""):
    """A ready-made combination (use case)."""
    return {"cmd": cmd, "min": minimal, "normal": normal,
            "verbose": verbose or normal, "tags": tags.split()}


def cmd(name, minimal, normal, verbose, flags=(), combos=(), pitfalls=(),
        oldstyle=False, subcommands=None, see=()):
    REG[name] = {
        "summary": {"min": minimal, "normal": normal, "verbose": verbose},
        "flags": list(flags),
        "combos": list(combos),
        "pitfalls": list(pitfalls),
        "oldstyle": oldstyle,          # accepts bundled letters without dash (tar xzf, ps aux)
        "subcommands": subcommands or {},
        "see": list(see),
        "source": "curated",
    }
