"""Offline tests. No network, no worker, no config — safe to run anywhere."""
import ast
import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "oat_refresh.py"


def load():
    spec = importlib.util.spec_from_file_location("oat_refresh", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


oat = load()


class TestExtractHandles(unittest.TestCase):
    def test_tiktok_urls(self):
        self.assertEqual(oat.extract_handles(["https://www.tiktok.com/@ana.creates"]), ["ana.creates"])
        self.assertEqual(oat.extract_handles(["tiktok.com/@ana/video/123"]), ["ana"])
        self.assertEqual(oat.extract_handles(["https://www.tiktok.com/@ana?lang=es"]), ["ana"])

    def test_several_links_in_one_cell(self):
        self.assertEqual(
            oat.extract_handles(["https://www.tiktok.com/@a, https://tiktok.com/@b"]), ["a", "b"]
        )
        self.assertEqual(
            oat.extract_handles(["https://www.tiktok.com/@one\nhttps://www.tiktok.com/@two"]),
            ["one", "two"],
        )

    def test_deduplicates_case_insensitively(self):
        self.assertEqual(oat.extract_handles(["tiktok.com/@Dup", "tiktok.com/@dup"]), ["dup"])

    def test_no_answer_variants(self):
        for blank in ("N/A", "n/a", "NONE", "-", "", None):
            self.assertEqual(oat.extract_handles([blank]), [], f"{blank!r} should yield nothing")

    def test_bare_handle_requires_at_sign(self):
        # Handles contain dots, so a domain-shaped guard would reject real ones.
        self.assertEqual(oat.extract_handles(["@ana.b.creates"]), ["ana.b.creates"])
        # ...and without the @, a pasted non-tiktok link must not become a handle.
        self.assertEqual(oat.extract_handles(["instagram.com/someone"]), [])
        self.assertEqual(oat.extract_handles(["https://instagram.com/someone"]), [])


class TestAlloc(unittest.TestCase):
    def test_skips_taken_ids(self):
        taken = {"a01", "a02", "a03"}
        self.assertEqual(oat.alloc("a", taken), "a04")
        self.assertIn("a04", taken)

    def test_ignores_ids_of_another_shape(self):
        # Creators migrated from accounts carry ids like "c_a01"; they must not
        # block "c01" from being allocated.
        self.assertEqual(oat.alloc("c", {"c_a01", "c_a02"}), "c01")


class TestPickColor(unittest.TestCase):
    def test_prefers_unused(self):
        used = {oat.PALETTE[0]}
        self.assertEqual(oat.pick_color(used), oat.PALETTE[1])

    def test_wraps_when_exhausted(self):
        used = set(oat.PALETTE)
        self.assertIn(oat.pick_color(used), oat.PALETTE)


class TestEnvFile(unittest.TestCase):
    def test_parses_comments_quotes_and_equals_in_value(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "env"
            p.write_text(
                '# comment\n\nA=1\nB="two"\nC=\'three\'\nD=has=equals\nbad-line\n', encoding="utf-8"
            )
            self.assertEqual(
                oat._parse_env_file(p),
                {"A": "1", "B": "two", "C": "three", "D": "has=equals"},
            )


class TestConfig(unittest.TestCase):
    def _env(self, **kw):
        base = {"OAT_ENV_FILE": str(pathlib.Path(tempfile.gettempdir()) / "does-not-exist-oat")}
        base.update(kw)
        return mock.patch.dict(os.environ, base, clear=True)

    def test_missing_everything_exits(self):
        with self._env(), self.assertRaises(SystemExit):
            oat.config()

    def test_placeholder_token_rejected(self):
        with self._env(OAT_WORKER_URL="https://x.example", OAT_ADMIN_TOKEN="replace-me"):
            with self.assertRaises(SystemExit):
                oat.config()

    def test_trailing_slash_stripped(self):
        with self._env(OAT_WORKER_URL="https://x.example/", OAT_ADMIN_TOKEN="t"):
            worker, token, _ = oat.config()
            self.assertEqual(worker, "https://x.example")
            self.assertEqual(token, "t")

    def test_bare_admin_token_fallback(self):
        """OAT_ENV_FILE may point at a wrangler .dev.vars, which uses ADMIN_TOKEN."""
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / ".dev.vars"
            p.write_text("ADMIN_TOKEN=from-dev-vars\nSCRAPECREATORS_API_KEY=x\n", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {"OAT_ENV_FILE": str(p), "OAT_WORKER_URL": "https://x.example"},
                clear=True,
            ):
                _, token, _ = oat.config()
                self.assertEqual(token, "from-dev-vars")

    def test_environment_beats_env_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "env"
            p.write_text("OAT_ADMIN_TOKEN=from-file\n", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {"OAT_ENV_FILE": str(p), "OAT_WORKER_URL": "https://x.example",
                 "OAT_ADMIN_TOKEN": "from-env"},
                clear=True,
            ):
                _, token, _ = oat.config()
                self.assertEqual(token, "from-env")


class TestNoDependencies(unittest.TestCase):
    """The repo promises 'standard library only'. Make that promise enforceable."""

    # Everything the script legitimately imports.
    STDLIB = {"argparse", "json", "os", "pathlib", "re", "sys", "urllib"}

    def test_script_imports_only_stdlib(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])

        # Cross-check against the interpreter's own list where available (3.10+),
        # so this does not rot as the allow-list drifts.
        names = getattr(sys, "stdlib_module_names", None)
        if names:
            self.assertEqual(sorted(m for m in found if m not in names), [],
                             "third-party import added to a zero-dependency script")
        self.assertTrue(found <= self.STDLIB, f"unexpected imports: {sorted(found - self.STDLIB)}")

    def test_requirements_declares_no_packages(self):
        req = ROOT / "requirements.txt"
        pkgs = [ln.strip() for ln in req.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        self.assertEqual(pkgs, [], f"requirements.txt should stay empty, found: {pkgs}")

    def test_declared_minimum_python_is_met(self):
        self.assertGreaterEqual(sys.version_info[:2], oat.MIN_PYTHON)


if __name__ == "__main__":
    unittest.main()
