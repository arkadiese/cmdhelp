#!/usr/bin/env python3
"""Package cmdhelp/ (with vendored prompt_toolkit + KB) into dist/cmdhelp.pyz."""
import os, shutil, tempfile, zipapp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
shutil.copytree(os.path.join(ROOT, "cmdhelp"), os.path.join(tmp, "cmdhelp"),
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
with open(os.path.join(tmp, "__main__.py"), "w") as fh:
    fh.write("import sys\nfrom cmdhelp.__main__ import run\nsys.exit(run())\n")
os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
out = os.path.join(ROOT, "dist", "cmdhelp.pyz")
zipapp.create_archive(tmp, out, interpreter="/usr/bin/env python3", compressed=True)
os.chmod(out, 0o755)
shutil.rmtree(tmp)
print("wrote", out, os.path.getsize(out) // 1024, "KiB")
