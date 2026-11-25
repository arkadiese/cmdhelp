# /etc/profile.d/cmdhelp.sh - cmdhelp keybindings for interactive bash/zsh. OPT-IN per user.
#
# Installing the package changes nobody's shell. A user turns it on with:
#     cmdhelp --enable          (creates ~/.config/cmdhelp/enabled)
# or by exporting CMDHELP_ENABLE=1. An admin can enable it for every user with:
#     touch /etc/cmdhelp/enable-all
# CMDHELP_DISABLE=1 always wins.
if [ -z "${CMDHELP_DISABLE:-}" ] && [ -t 0 ]; then
  case $- in
    *i*)
      if [ -n "${CMDHELP_ENABLE:-}" ] \
         || [ -e "${XDG_CONFIG_HOME:-$HOME/.config}/cmdhelp/enabled" ] \
         || [ -e /etc/cmdhelp/enable-all ]; then
        if [ -n "${BASH_VERSION:-}" ]; then
          . /usr/share/cmdhelp/cmdhelp.bash
        elif [ -n "${ZSH_VERSION:-}" ]; then
          . /usr/share/cmdhelp/cmdhelp.zsh
        fi
      fi
      ;;
  esac
fi
