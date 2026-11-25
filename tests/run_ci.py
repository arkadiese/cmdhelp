"""Run the suite; on GitHub Actions, turn each failure into an ::error annotation.

Annotations are readable through the public check-runs API, so a failing CI job explains itself
without anyone signing in to view the raw logs.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _esc(s):
    return s.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def main():
    sys.path.insert(0, ROOT)
    suite = unittest.defaultTestLoader.discover(os.path.join(ROOT, "tests"), top_level_dir=ROOT)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    problems = [("ERROR", t, tb) for t, tb in result.errors] + [("FAIL", t, tb) for t, tb in result.failures]
    if os.environ.get("GITHUB_ACTIONS") and problems:
        env = "Python %s, %s" % (sys.version.split()[0], sys.stdout.encoding)
        for kind, test, tb in problems[:10]:        # GitHub keeps at most 10 error annotations per step
            print("::error title=%s %s::%s" % (kind, _esc(test.id()), _esc("[%s]\n%s" % (env, tb[-6000:]))))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
