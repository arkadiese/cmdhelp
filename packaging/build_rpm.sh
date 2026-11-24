#!/bin/sh
# Build dist/cmdhelp-<ver>-1.noarch.rpm. Usage: packaging/build_rpm.sh [version]
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
VER=${1:-$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/cmdhelp/__init__.py")}
TOP=$(mktemp -d)
python3 "$ROOT/build/make_pyz.py"
mkdir -p "$TOP/SOURCES"
cp "$ROOT/dist/cmdhelp.pyz" "$ROOT/packaging/cmdhelp.sh" "$ROOT/packaging/cmdhelp.bash" "$ROOT/packaging/cmdhelp.zsh" "$TOP/SOURCES/"
rpmbuild -bb --define "_topdir $TOP" --define "pkg_version $VER" --define "dist %{nil}" "$ROOT/packaging/cmdhelp.spec"
cp "$TOP"/RPMS/noarch/*.rpm "$ROOT/dist/"
ls -l "$ROOT"/dist/*.rpm
