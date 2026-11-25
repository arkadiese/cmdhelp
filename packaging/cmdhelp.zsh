# cmdhelp zsh integration: Ctrl+Space, Alt+h (or Esc h) or Ctrl+X h opens the helper with the current line,
# ?? explains a command line (no args = the previous command).
# Fedora's /etc/zshrc does not read /etc/profile.d for non-login shells, so add to ~/.zshrc:
#   source /usr/share/cmdhelp/cmdhelp.zsh
[[ -n ${_CMDHELP_LOADED:-} ]] && return 0
_CMDHELP_LOADED=1
_cmdhelp_run() { /usr/bin/cmdhelp "$@"; }
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
bindkey '^Xh' _cmdhelp_widget   # fallback for terminals that eat Ctrl+Space / Alt (MobaXterm, PuTTY)
cmdexplain() { if [[ $# -eq 0 ]]; then _cmdhelp_run -e "$(fc -ln -1)"; else _cmdhelp_run -e "$*"; fi; }
alias '??'='noglob cmdexplain'
