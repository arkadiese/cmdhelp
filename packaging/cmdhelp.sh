# /etc/profile.d/cmdhelp.sh - enable cmdhelp keybindings in interactive bash/zsh.
# Opt out per user with: export CMDHELP_DISABLE=1  (in ~/.bashrc before /etc/bashrc is sourced, or ~/.profile)
if [ -z "${CMDHELP_DISABLE:-}" ] && [ -t 0 ]; then
  case $- in
    *i*)
      if [ -n "${BASH_VERSION:-}" ]; then
        . /usr/share/cmdhelp/cmdhelp.bash
      elif [ -n "${ZSH_VERSION:-}" ]; then
        . /usr/share/cmdhelp/cmdhelp.zsh
      fi
      ;;
  esac
fi
