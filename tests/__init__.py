"""Test package. Isolates HOME/XDG dirs BEFORE cmdhelp is imported, so tests never read
the developer's shell history or write to their real cache."""
import os
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix="cmdhelp-test-")
os.environ["HOME"] = _SANDBOX
os.environ["XDG_CACHE_HOME"] = os.path.join(_SANDBOX, ".cache")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_SANDBOX, ".config")
os.environ.pop("HISTFILE", None)
os.environ.pop("CMDHELP_MODE", None)
os.environ["NO_COLOR"] = "1"
SANDBOX = _SANDBOX
