_cmdhelp_run() { /usr/bin/cmdhelp "$@"; }
# cmdhelp zsh integration: Ctrl+Space, Alt+h (Esc h) or Ctrl+X h opens the helper with the current line.
# The helper gets the last command, its exit status and the current line via the environment. Output is never read.
[[ -n ${_CMDHELP_LOADED:-} ]] && return 0
_CMDHELP_LOADED=1
_cmdhelp_widget() {
  local st=$? f last
  last=$(fc -ln -1 2>/dev/null)
  f=$(mktemp "${TMPDIR:-/tmp}/cmdhelp.XXXXXX") || return
  ( export CMDHELP_LAST_STATUS="$st" CMDHELP_LAST_CMD="$last" CMDHELP_LINE="$BUFFER"
    _cmdhelp_run --result-file "$f" </dev/tty >/dev/tty 2>&1 )
  if [[ -s $f ]]; then BUFFER=$(<"$f"); CURSOR=${#BUFFER}; fi
  rm -f "$f"
  zle reset-prompt
}
zle -N _cmdhelp_widget
bindkey '^@' _cmdhelp_widget
bindkey '\eh' _cmdhelp_widget
bindkey '^Xh' _cmdhelp_widget
# ?? <line> explains a line; ?? alone explains the previous command, its exit status and what to try next
cmdexplain() {
  local st=$?
  if [[ $# -eq 0 ]]; then
    ( export CMDHELP_LAST_STATUS="$st" CMDHELP_LAST_CMD="$(fc -ln -1)"
      _cmdhelp_run -e --context )
  else
    _cmdhelp_run -e "$*"
  fi
}
alias '??'='noglob cmdexplain'
