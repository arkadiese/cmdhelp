"""cmdhelp entry point.

  cmdhelp                         interactive TUI
  cmdhelp tar -xzvf x.tgz         TUI pre-filled with a line
  cmdhelp -e 'tar -xzvf x.tgz'    explain a line (no TUI, no dependencies)
  cmdhelp -s tar                  cheat sheet for a command
  cmdhelp -m verbose ...          minimal | normal | verbose
  cmdhelp --init bash|zsh         print shell integration code
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODE_ALIASES = {"min": "min", "minimal": "min", "m": "min", "1": "min",
                "normal": "normal", "n": "normal", "2": "normal",
                "verbose": "verbose", "v": "verbose", "full": "verbose", "3": "verbose"}

SHELL_INIT = {
    "bash": r'''# cmdhelp bash integration: Ctrl+Space, Alt+h (Esc h) or Ctrl+X h opens the helper with the current line
_cmdhelp_widget() {
  local f; f=$(mktemp "${TMPDIR:-/tmp}/cmdhelp.XXXXXX") || return
  _cmdhelp_run --result-file "$f" --initial "$READLINE_LINE" </dev/tty >/dev/tty 2>&1
  if [ -s "$f" ]; then READLINE_LINE=$(cat "$f"); READLINE_POINT=${#READLINE_LINE}; fi
  rm -f "$f"
}
bind -x '"\C-@": _cmdhelp_widget'
bind -x '"\eh": _cmdhelp_widget'
bind -x '"\C-xh": _cmdhelp_widget'
cmdexplain() { if [ $# -eq 0 ]; then _cmdhelp_run -e "$(fc -ln -2 -2 | sed 's/^[[:space:]]*//')"; else _cmdhelp_run -e "$*"; fi; }
alias '??'='cmdexplain'
''',
    "zsh": r'''# cmdhelp zsh integration: Ctrl+Space, Alt+h (Esc h) or Ctrl+X h opens the helper with the current line
_cmdhelp_widget() {
  local f; f=$(mktemp "${TMPDIR:-/tmp}/cmdhelp.XXXXXX") || return
  _cmdhelp_run --result-file "$f" --initial "$BUFFER" </dev/tty >/dev/tty 2>&1
  if [[ -s $f ]]; then BUFFER=$(<"$f"); CURSOR=${#BUFFER}; fi
  rm -f "$f"
  zle reset-prompt
}
zle -N _cmdhelp_widget
bindkey '^@' _cmdhelp_widget
bindkey '\eh' _cmdhelp_widget
bindkey '^Xh' _cmdhelp_widget
cmdexplain() { if [[ $# -eq 0 ]]; then _cmdhelp_run -e "$(fc -ln -1)"; else _cmdhelp_run -e "$*"; fi; }
alias '??'='noglob cmdexplain'
''',
}


def _import_pt():
    try:
        import prompt_toolkit  # noqa
        v = tuple(int(x) for x in prompt_toolkit.__version__.split(".")[:2])
        if v >= (3, 0):
            return True
    except Exception:
        pass
    vend = os.path.join(HERE, "_vendor")
    sys.path.insert(0, vend)
    for m in [m for m in list(sys.modules) if m.startswith(("prompt_toolkit", "wcwidth"))]:
        del sys.modules[m]
    try:
        import prompt_toolkit  # noqa
        return True
    except Exception:
        return False


def _enable_marker():
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "cmdhelp", "enabled")


def _toggle(on):
    m = _enable_marker()
    if on:
        d = os.path.dirname(m)
        if not os.path.isdir(d):
            os.makedirs(d, 0o700)
        open(m, "a").close()
        print("cmdhelp enabled for %s. Open a new shell (bash), or run:" % os.environ.get("USER", "you"))
        print("  bash: source /etc/profile.d/cmdhelp.sh")
        print("  zsh:  add 'source /usr/share/cmdhelp/cmdhelp.zsh' to ~/.zshrc")
        print("Keys: Ctrl+Space, Alt+h (or Esc then h), Ctrl+X then h.  ?? = explain last command.")
    else:
        try:
            os.unlink(m)
        except OSError:
            pass
        print("cmdhelp disabled for new shells. Remove any 'source .../cmdhelp.zsh' line from ~/.zshrc too.")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="cmdhelp", description="Interactive shell command helper with explanations.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("-m", "--mode", default=os.environ.get("CMDHELP_MODE", "normal"),
                   help="minimal | normal | verbose (env CMDHELP_MODE)")
    p.add_argument("-e", "--explain", action="store_true", help="explain the given command line and exit")
    p.add_argument("-s", "--sheet", metavar="CMD", help="print a cheat sheet for CMD and exit")
    p.add_argument("--init", choices=["bash", "zsh"], help="print shell integration code")
    p.add_argument("--enable", action="store_true", help="turn on the keybindings for your user (RPM install)")
    p.add_argument("--disable", action="store_true", help="turn off the keybindings for your user")
    p.add_argument("--initial", default=None, help=argparse.SUPPRESS)
    p.add_argument("--result-file", default=None, help=argparse.SUPPRESS)
    p.add_argument("--no-color", action="store_true")
    from . import __version__
    p.add_argument("-V", "--version", action="version", version="cmdhelp " + __version__)
    p.add_argument("line", nargs=argparse.REMAINDER, help="command line to pre-fill / explain")
    a = p.parse_args(argv)
    if "--no-color" in a.line:
        a.line.remove("--no-color"); a.no_color = True
    mode = MODE_ALIASES.get(a.mode.lower(), "normal")
    color = not a.no_color and sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    if a.enable or a.disable:
        return _toggle(a.enable)

    if a.init:
        me = os.path.abspath(sys.argv[0])
        if me.endswith(".pyz") or os.path.isfile(me) and not me.endswith("__main__.py"):
            run = '"%s" "%s" "$@"' % (sys.executable, me)
        else:
            run = 'PYTHONPATH="%s${PYTHONPATH:+:$PYTHONPATH}" "%s" -m cmdhelp "$@"' % (os.path.dirname(HERE), sys.executable)
        print("_cmdhelp_run() { %s; }" % run)
        print(SHELL_INIT[a.init])
        return 0

    from .kb import KB
    kb = KB()
    line = " ".join(a.line).strip()

    if a.sheet:
        from .explain import render_command
        print(render_command(kb, a.sheet, mode, color))
        return 0
    if a.explain:
        from .explain import render_text
        if not line:
            line = sys.stdin.read().strip()
        print(render_text(kb, line, mode, color))
        return 0

    if not _import_pt():
        sys.stderr.write("prompt_toolkit unavailable; falling back to explain mode. Use: cmdhelp -e '<command>'\n")
        return 1
    from .tui import run_tui
    initial = a.initial if a.initial is not None else line
    r = run_tui(kb, mode, initial, a.result_file)
    return 0 if r else 1


def run():
    try:
        return main()
    except BrokenPipeError:
        try:
            sys.stdout = open(os.devnull, "w")
        except Exception:
            pass
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(run())
