_cmdhelp_run() { /usr/bin/cmdhelp "$@"; }
# cmdhelp bash integration: Ctrl+Space, Alt+h (Esc h) or Ctrl+X h opens the helper with the current line.
# The helper gets the last command, its exit status and the current line via the environment. Output is never read.
_cmdhelp_widget() {
  local st=$? f last
  last=$(fc -ln -1 2>/dev/null | sed 's/^[[:space:]]*//')
  f=$(mktemp "${TMPDIR:-/tmp}/cmdhelp.XXXXXX") || return
  ( export CMDHELP_LAST_STATUS="$st" CMDHELP_LAST_CMD="$last" CMDHELP_LINE="$READLINE_LINE"
    _cmdhelp_run --result-file "$f" </dev/tty >/dev/tty 2>&1 )
  if [ -s "$f" ]; then READLINE_LINE=$(cat "$f"); READLINE_POINT=${#READLINE_LINE}; fi
  rm -f "$f"
}
bind -x '"\C-@": _cmdhelp_widget'
bind -x '"\eh": _cmdhelp_widget'
bind -x '"\C-xh": _cmdhelp_widget'
# ?? <line> explains a line; ?? alone explains the previous command, its exit status and what to try next
cmdexplain() {
  local st=$?
  if [ $# -eq 0 ]; then
    ( export CMDHELP_LAST_STATUS="$st" CMDHELP_LAST_CMD="$(fc -ln -2 -2 | sed 's/^[[:space:]]*//')"
      _cmdhelp_run -e --context )
  else
    _cmdhelp_run -e "$*"
  fi
}
alias '??'='cmdexplain'
