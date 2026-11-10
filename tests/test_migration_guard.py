import os
import subprocess
import sys

from helper_support import GitFixture


class MigrationGuardTests(GitFixture):
    def setUp(self):
        super().setUp()
        self.path = self.local / ".github/migration-hooks/pre-push"
        self.ref = "refs/heads/miyako-simplify-cld2-workflows"
        self.log = self.root / "advertisement"
        self.values = {**self.env, "MIGRATION_HEAD": self.sha, "MIGRATION_OLD": self.ancestor,
                       "MIGRATION_ADVERTISEMENT_LOG": str(self.log)}

    def invoke(self, row=None, *, env=None, check=False):
        return subprocess.run([sys.executable, str(self.path), *(["--check"] if check else [])],
                              cwd=self.local, env=self.values if env is None else env,
                              text=True, input=row, capture_output=True, timeout=30)

    def test_exact_literal_single_advertisement_and_receipt(self):
        row = f"{self.sha} {self.sha} {self.ref} {self.ancestor}\n"
        self.assertEqual(self.invoke(check=True).returncode, 0)
        self.assertFalse(self.log.exists())
        self.assertEqual(self.invoke(row).returncode, 0)
        self.assertEqual(self.log.read_text(), row)
        for invalid in ("", row * 2, row.replace(self.sha + " ", "HEAD ", 1),
                        row.replace(self.ref, "refs/heads/main"),
                        row.replace(self.ancestor, "0" * 40),
                        row.replace(self.sha, self.ancestor, 1)):
            self.assertNotEqual(self.invoke(invalid).returncode, 0)
            self.assertEqual(self.log.read_text(), row)

    def test_missing_environment_wrong_head_and_guard_content_mode_or_symlink(self):
        for env in (self.env, {**self.values, "MIGRATION_HEAD": "A" * 40},
                    {**self.values, "MIGRATION_HEAD": self.ancestor}):
            self.assertNotEqual(self.invoke(check=True, env=env).returncode, 0)
        saved = self.path.read_bytes()
        peer = self.root / "same-guard"
        peer.write_bytes(saved)
        peer.chmod(0o755)
        for kind in ("mode", "replacement", "symlink"):
            self.path.unlink()
            if kind == "symlink":
                self.path.symlink_to(peer)
            else:
                self.path.write_bytes(saved if kind == "mode" else b"#!/bin/sh\nexit 0\n")
                self.path.chmod(0o644 if kind == "mode" else 0o755)
            self.assertNotEqual(self.invoke(check=True).returncode, 0)
        self.assertFalse(self.log.exists())

    def test_migration_guard_rejects_both_index_flag_channels(self):
        for flag in ("assume-unchanged", "skip-worktree"):
            self.git("update-index", "--" + flag, "--", "VERSION")
            self.assertNotEqual(self.invoke(check=True).returncode, 0)
            self.git("update-index", "--no-" + flag, "--", "VERSION")
        self.git("config", "core.fsmonitor", "true")
        self.git("update-index", "--fsmonitor-valid", "--", "VERSION")
        self.assertEqual(self.git("ls-files", "-v", "--", "VERSION"), "H VERSION")
        self.assertEqual(self.git("ls-files", "-f", "--", "VERSION"), "h VERSION")
        self.assertNotEqual(self.invoke(check=True).returncode, 0)
