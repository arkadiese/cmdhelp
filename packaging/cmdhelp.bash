# cmdhelp bash integration: Ctrl+Space or Alt+h opens the helper with the current line,
# ?? explains a command line (no args = the previous command).
_cmdhelp_run() { /usr/bin/cmdhelp "$@"; }
_cmdhelp_widget() {
  local f; f=$(mktemp "${TMPDIR:-/tmp}/cmdhelp.XXXXXX") || return
  _cmdhelp_run --result-file "$f" --initial "$READLINE_LINE" </dev/tty >/dev/tty 2>&1
  if [ -s "$f" ]; then READLINE_LINE=$(cat "$f"); READLINE_POINT=${#READLINE_LINE}; fi
  rm -f "$f"
}
bind -x '"\C-@": _cmdhelp_widget'
bind -x '"\eh": _cmdhelp_widget'
cmdexplain() { if [ $# -eq 0 ]; then _cmdhelp_run -e "$(fc -ln -2 -2 | sed 's/^[[:space:]]*//')"; else _cmdhelp_run -e "$*"; fi; }
alias '??'='cmdexplain'
