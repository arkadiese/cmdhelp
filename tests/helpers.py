import tests  # noqa: F401  (sandbox env first)
from cmdhelp.kb import KB
from cmdhelp.explain import explain

_KB = None


def kb():
    """One shared KB per test run (loading takes ~50 ms). Man lookups are disabled unless a test opts in."""
    global _KB
    if _KB is None:
        _KB = KB()
    return _KB


def rows(line, mode="normal", man="none"):
    """Flatten explain() into [(token, kind, text), ...] across all segments (separators included)."""
    out = []
    for seg in explain(kb(), line, mode, man=man)["segments"]:
        if "sep" in seg:
            out.append((seg["sep"], "sep", seg["text"]))
        else:
            out.extend(seg["rows"])
    return out


def kinds(line, **kw):
    return [(t, k) for t, k, _ in rows(line, **kw)]


def text_for(line, token, **kw):
    for t, k, txt in rows(line, **kw):
        if t == token:
            return txt
    raise AssertionError("token %r not in %r" % (token, kinds(line, **kw)))
