#!/bin/sh
# cmdhelp installer: copies the single-file app to ~/.local/bin and wires up bash/zsh.
# Usage: sh install.sh [path/to/cmdhelp.pyz]
set -e
SRC="${1:-$(dirname "$0")/cmdhelp.pyz}"
DEST="${CMDHELP_DEST:-$HOME/.local/bin}"
PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "python3 not found (need 3.6+)"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,6) else 1)' || { echo "python3 >= 3.6 required"; exit 1; }

mkdir -p "$DEST"
cp "$SRC" "$DEST/cmdhelp.pyz"
chmod 755 "$DEST/cmdhelp.pyz"
ln -sf "$DEST/cmdhelp.pyz" "$DEST/cmdhelp"

add_rc() {
  rc="$1"; sh_name="$2"
  [ -f "$rc" ] || return 0
  grep -q 'cmdhelp.pyz --init' "$rc" 2>/dev/null && { echo "already in $rc"; return 0; }
  printf '\n# cmdhelp: Ctrl+Space / Alt+h = command helper, ?? = explain last command\n[ -t 0 ] && eval "$("%s" "%s" --init %s)"\n' "$PY" "$DEST/cmdhelp.pyz" "$sh_name" >> "$rc"
  echo "added to $rc"
}
add_rc "$HOME/.bashrc" bash
add_rc "$HOME/.zshrc" zsh
echo "Installed. Open a new shell, type a command and press Ctrl+Space (or Alt+h)."
