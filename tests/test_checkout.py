"""A real clone under hostile fixture-global autocrlf; never write host settings."""

import os
from pathlib import Path
import subprocess
from unittest.mock import patch

from helper_support import GitFixture, cwd
from release_support import ReleaseCLI
import repository


class CheckoutTests(ReleaseCLI, GitFixture):
    def clone(self, name, *, scoped):
        destination = self.root / name
        env = {**self.env, "GIT_CONFIG_GLOBAL": str(self.global_config)}
        if not scoped:
            for key in ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
                env.pop(key)
        result = subprocess.run(
            ["git", "-c", "protocol.file.allow=always", "clone", "--quiet", "--no-local",
             "--recurse-submodules", str(self.local), str(destination)],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return destination

    def verify_all_raw(self, root):
        differences = []
        for directory in (root, root / "4D-Plugin-SDK", root / "cld2-src"):
            tree = subprocess.check_output(["git", "-C", str(directory), "ls-tree", "-r", "-z", "HEAD"],
                                           env=self.env).decode()
            selected = repository.entries(tree)
            index = subprocess.check_output(["git", "-C", str(directory), "ls-files", "--stage", "-z"],
                                            env=self.env).decode()
            self.assertEqual(repository.entries(index, index=True), selected)
            for name, (mode, oid) in selected.items():
                if mode == "160000":
                    continue
                raw = subprocess.check_output(["git", "-C", str(directory), "cat-file", "blob", oid],
                                              env=self.env)
                if (directory / name).read_bytes() != raw:
                    differences.append(str((directory / name).relative_to(root)))
                if not differences:
                    self.assertEqual(repository.actual_blob(directory / name), (mode, oid))
        return differences

    def test_scoped_false_before_real_recursive_clone_and_late_setting_negative(self):
        self.global_config = self.root / "hostile-global.gitconfig"
        global_bytes = b"[core]\n\tautocrlf = true\n[safe]\n\tbareRepository = explicit\n"
        self.global_config.write_bytes(global_bytes)
        (self.local / "checkout-probe.txt").write_bytes(b"first LF\nsecond LF\n")
        self.git("add", "checkout-probe.txt")
        self.git("commit", "--quiet", "-m", "LF clone oracle")
        sha = self.git("rev-parse", "HEAD")
        positive = self.clone("scoped-before-clone", scoped=True)
        self.assertEqual(self.verify_all_raw(positive), [])
        guarded_env = {**self.env, "GIT_CONFIG_GLOBAL": str(self.global_config)}
        with cwd(positive), patch.dict(os.environ, guarded_env, clear=True):
            repository.verify_checkout(sha)
        negative = self.clone("late-false-setting", scoped=False)
        differences = self.verify_all_raw(negative)
        self.assertIn("checkout-probe.txt", differences)
        self.assertTrue(any(name.startswith("4D-Plugin-SDK/") for name in differences))
        self.assertTrue(any(name.startswith("cld2-src/") for name in differences))
        # Setting false after checkout cannot recover already-converted raw bytes.
        with cwd(negative), patch.dict(os.environ, guarded_env, clear=True):
            with self.assertRaises(ValueError):
                repository.verify_checkout(sha)
        self.exercise_cloned_windows_cli(positive, guarded_env, global_bytes)
        self.assertEqual(self.global_config.read_bytes(), global_bytes)
        self.assertEqual(subprocess.check_output(
            ["git", "config", "--file", str(self.global_config), "--get", "core.autocrlf"],
            env=self.env).strip(), b"true")

    def exercise_cloned_windows_cli(self, checkout, guarded_env, global_bytes):
        self.local = checkout
        self.env = guarded_env
        self.sha = self.git("rev-parse", "HEAD")
        self.assertEqual(self.git("rev-parse", "--show-toplevel"), str(checkout))
        for dependency in ("4D-Plugin-SDK", "cld2-src"):
            self.assertTrue((checkout / dependency / ".git").is_file(),
                            "Matrix must exercise recursively cloned dependencies")
        self.git("remote", "set-url", "origin", str(self.bare))
        self.setup_release_cli()
        self.select()
        names = ((".", ".github/scripts/native.sh"), ("4D-Plugin-SDK", "tool.sh"),
                 ("cld2-src", "tool.sh"))
        for directory, name in names:
            self.assertTrue(self.git("-C", directory, "ls-tree", "HEAD", "--", name).startswith(
                "100755 blob "))
            self.git("-C", directory, "config", "core.filemode", "false")
            (checkout / directory / name).chmod(0o644)
        self.assert_no_api("preflight")
        result = self.command("preflight", windows=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for final in (False, True):
            data = self.populate() if final else {}
            for directory, name in names:
                path = checkout / directory / name
                saved = path.read_bytes()
                for kind in ("raw", "staged", "reversed", "index-mode", "symlink", "directory",
                             "reparse", "ancestor-reparse"):
                    with self.subTest(final=final, directory=directory, kind=kind):
                        self.reset_api()
                        extra = {}
                        if kind == "index-mode":
                            self.git("-C", directory, "update-index", "--chmod=-x", "--", name)
                        elif kind in ("symlink", "directory"):
                            path.unlink()
                            if kind == "symlink":
                                target = self.root / "same-cloned-source-bytes"
                                target.write_bytes(saved)
                                path.symlink_to(target)
                            else:
                                path.mkdir()
                        elif kind in ("reparse", "ancestor-reparse"):
                            target = path if kind == "reparse" else path.parent
                            extra["SIMULATED_REPARSE"] = str(target)
                        else:
                            path.write_bytes(saved + b" unexpected cloned source mutation")
                            if kind in ("staged", "reversed"):
                                self.git("-C", directory, "add", "--", name)
                            if kind == "reversed":
                                path.write_bytes(saved)
                        self.assert_no_api("publish" if final else "preflight",
                                           windows=True, env=extra)
                        self.assertEqual(self.global_config.read_bytes(), global_bytes)
                        self.assert_retained(data)
                        if kind == "directory":
                            path.rmdir()
                        elif kind == "symlink":
                            path.unlink()
                        path.write_bytes(saved)
                        path.chmod(0o644)
                        self.git("-C", directory, "restore", "--staged", "--", name)
                        self.reset_api()
                        result = self.command("check" if final else "preflight", windows=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assert_retained(data)
                        self.assertEqual(self.global_config.read_bytes(), global_bytes)
