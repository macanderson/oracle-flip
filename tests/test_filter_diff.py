import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "oracle"))

from filter_diff import allowed, filter_diff, glob_to_regex  # noqa: E402

SRC = """diff --git a/src/billing/proration.py b/src/billing/proration.py
--- a/src/billing/proration.py
+++ b/src/billing/proration.py
@@ -1 +1 @@
-old
+new
"""
TEST = """diff --git a/tests/test_proration.py b/tests/test_proration.py
--- a/tests/test_proration.py
+++ b/tests/test_proration.py
@@ -1 +1 @@
-assert x == 1
+assert x == 2
"""
CONFTEST = """diff --git a/src/conftest.py b/src/conftest.py
new file mode 100644
--- /dev/null
+++ b/src/conftest.py
@@ -0,0 +1 @@
+import sys; sys.exit(0)
"""
CI = """diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1 +1 @@
-run: pytest
+run: true
"""

ALLOW = ["src/**"]
DENY = ["**/tests/**", "**/test_*.py", "**/conftest.py", ".github/**"]


class GlobTests(unittest.TestCase):
    def test_double_star_spans_directories(self):
        self.assertTrue(glob_to_regex("src/**").match("src/a/b/c.py"))
        self.assertTrue(glob_to_regex("src/**").match("src/c.py"))
        self.assertFalse(glob_to_regex("src/**").match("lib/c.py"))

    def test_single_star_stays_in_one_segment(self):
        self.assertTrue(glob_to_regex("**/test_*.py").match("a/b/test_x.py"))
        self.assertTrue(glob_to_regex("**/test_*.py").match("test_x.py"))
        self.assertFalse(glob_to_regex("src/*.py").match("src/a/b.py"))

    def test_deny_wins_over_allow(self):
        self.assertTrue(allowed("src/billing/proration.py", ALLOW, DENY))
        self.assertFalse(allowed("src/conftest.py", ALLOW, DENY))
        self.assertFalse(allowed("src/tests/test_x.py", ALLOW, DENY))

    def test_empty_allowlist_allows_everything_not_denied(self):
        self.assertTrue(allowed("anything/at/all.py", [], DENY))
        self.assertFalse(allowed(".github/workflows/ci.yml", [], DENY))


class FilterDiffTests(unittest.TestCase):
    def test_keeps_source_and_drops_tests_config_and_ci(self):
        kept, dropped = filter_diff(SRC + TEST + CONFTEST + CI, ALLOW, DENY)
        self.assertEqual(kept, SRC)
        self.assertEqual(dropped, ["tests/test_proration.py", "src/conftest.py", ".github/workflows/ci.yml"])

    def test_empty_diff_yields_empty_output(self):
        kept, dropped = filter_diff("", ALLOW, DENY)
        self.assertEqual(kept, "")
        self.assertEqual(dropped, [])

    def test_preamble_without_header_is_never_applied(self):
        kept, dropped = filter_diff("garbage before any header\n" + SRC, ALLOW, DENY)
        self.assertEqual(kept, SRC)
        self.assertEqual(dropped, [])


if __name__ == "__main__":
    unittest.main()
