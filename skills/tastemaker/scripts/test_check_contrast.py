#!/usr/bin/env python3
"""Regression tests for check_contrast.py."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from skills.tastemaker.scripts import check_contrast


class ContrastCliTests(unittest.TestCase):
    def run_cli(self, *args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", ["check_contrast.py", *args]):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                returncode = check_contrast.main()
        return SimpleNamespace(
            returncode=returncode,
            stdout=stdout.getvalue(),
            stderr=stderr.getvalue(),
        )

    def json_cli(self, *args):
        result = self.run_cli(*args)
        return result, json.loads(result.stdout)

    def test_pair_json_is_stable_and_reports_failure(self):
        first = self.run_cli("--json", "ffffff", "ffffff")
        second = self.run_cli("ffffff", "ffffff", "--json")
        self.assertEqual(first.returncode, 1)
        self.assertEqual(first.stdout, second.stdout)
        payload = json.loads(first.stdout)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["mode"], "pair")
        self.assertFalse(payload["passed"])
        self.assertEqual(payload["pairs"][0]["classification"], "decorative")

    def test_palette_json_preserves_alternative_label_rule(self):
        result, payload = self.json_cli(
            "--palette",
            "text=050315",
            "bg=fbfbfe",
            "primary=2f27ce",
            "accent=433bff",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["mode"], "palette")
        self.assertEqual(len(payload["pairs"]), 5)

    def test_matrix_json_contains_every_pair_and_groups(self):
        result, payload = self.json_cli(
            "--json", "--matrix", "text=000000", "bg=ffffff", "border=777777"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(payload["pairs"]), 3)
        grouped = payload["legal_pairings"]
        self.assertEqual(
            len(grouped["text_safe"] + grouped["ui_safe"] + grouped["decorative"]), 3
        )
        self.assertIn("text/bg", grouped["text_safe"])

    def test_text_output_is_unchanged_without_json(self):
        result = self.run_cli("000000", "ffffff")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout,
            "[PASS] given pair: 21.00:1 (floor 4.5:1) — #000000 vs #ffffff\n",
        )

    def test_style_lock_passes_then_names_regressed_pair(self):
        template = """# Style lock

## Palette
- Background: #{background}
- Text primary: #000000
- Primary: #777777

## Color contract
- Text-safe (>=4.5): text/bg (21.00), text/primary (4.69)
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            lock = Path(temp_dir) / "style-lock.md"
            lock.write_text(template.format(background="ffffff"), encoding="utf-8")
            passing = self.run_cli("--style-lock", str(lock))
            self.assertEqual(passing.returncode, 0, passing.stdout + passing.stderr)

            lock.write_text(template.format(background="111111"), encoding="utf-8")
            failing = self.run_cli("--style-lock", str(lock))
            self.assertEqual(failing.returncode, 1)
            self.assertIn("[FAIL] text/bg", failing.stdout)

    def test_style_lock_missing_role_is_configuration_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock = Path(temp_dir) / "style-lock.md"
            lock.write_text(
                "## Palette\n- Background: #ffffff\n\n"
                "## Color contract\n- Text-safe (>=4.5): text/bg\n",
                encoding="utf-8",
            )
            result = self.run_cli("--style-lock", str(lock))
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing palette roles: text", result.stderr)


if __name__ == "__main__":
    unittest.main()
