"""Actual workflow Bash and PowerShell execute only closed-PATH native oracles."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

import yaml
from helper_support import GitFixture, ROOT, source
import native


class NativeTests(GitFixture):
    def setUp(self):
        super().setUp()
        self.tools = self.closed_tools()
        for tool in ("cmake", "lipo", "base64", "security", "codesign", "ditto", "hdiutil", "xcrun"):
            path = self.tools / tool
            path.write_text("#!" + sys.executable + "\n" + (ROOT / "tests/fake_native.py").read_text())
            path.chmod(0o755)
        for tool in ("bash", "grep", "head", "sed", "mkdir"):
            (self.tools / tool).symlink_to(shutil.which(tool))
        gh = self.tools / "gh"
        gh.write_text("#!" + sys.executable + "\n" + (ROOT / "tests/fake_gh.py").read_text())
        gh.chmod(0o755)
        self.log, self.api_log = self.root / "native.jsonl", self.root / "gh.jsonl"
        self.state = self.root / "state.json"
        self.state.write_text("{}")
        self.version = source.read(self.local)
        self.env.update(
            PATH=str(self.tools), NATIVE_LOG=str(self.log), OFFLINE_CHECKOUT=str(self.local),
            GITHUB_SHA=self.sha, EVENT_SHA=self.sha, GH_TOKEN="offline-fixture",
            GITHUB_REPOSITORY="miyako/4d-plugin-CLD2", GITHUB_OUTPUT=str(self.root / "output"),
            GITHUB_ENV=str(self.root / "env"), GH_STATE=str(self.state),
            GH_LOG=str(self.api_log), GH_BARE_ORIGIN=str(self.bare),
            MACOS_DEPLOYMENT_TARGET="10.13", RUNNER_TEMP=str(self.root),
            BUNDLE_PATH=str(native.BUNDLE), KEYCHAIN_PATH=str(self.root / "offline.keychain"),
            CERT_BASE64="b2ZmbGluZQ==", CERT_PASSWORD="offline-only", KEYCHAIN_PASSWORD="offline-only",
            APPLE_ID="offline@example.invalid", TEAM_ID="OFFLINE", APP_PASSWORD="offline-only",
            ZIP_PATH=f"CLD2-{self.version}.zip", DMG_PATH=f"CLD2-{self.version}.dmg",
            POWERSHELL_TELEMETRY_OPTOUT="1", DOTNET_CLI_TELEMETRY_OPTOUT="1")
        self.jobs = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())["jobs"]

    def calls(self):
        return [json.loads(row) for row in self.log.read_text().splitlines()] if self.log.exists() else []

    def phase(self, phase, success=True, *, extra=None, powershell=False):
        if powershell:
            command = ["/usr/local/bin/pwsh", "-NoLogo", "-NoProfile", "-NonInteractive",
                       "-File", ".github/scripts/native.ps1"]
        else:
            command = ["/bin/bash", "--noprofile", "--norc", ".github/scripts/native.sh", phase]
        result = subprocess.run(command, cwd=self.local, env={**self.env, **(extra or {})},
                                text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def pipeline(self, checkout=None, extra=None):
        checkout = checkout or self.local
        env = {**self.env, "OFFLINE_CHECKOUT": str(checkout), **(extra or {})}
        for job in ("version", "build-macos"):
            for step in self.jobs[job]["steps"]:
                if step.get("uses", "").startswith("actions/download-artifact@"):
                    path = checkout / native.DOWNLOAD
                    path.parent.mkdir(exist_ok=True)
                    path.write_bytes(b"fresh Windows fixture")
                if "run" not in step:
                    continue
                self.assertNotIn("${{", step["run"])
                result = subprocess.run(
                    ["/bin/bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
                    cwd=checkout, env=env, text=True, capture_output=True, timeout=60)
                if result.returncode:
                    return result
        return result

    def test_complete_real_workflow_pipeline_only_stubs_and_publication_after_staple(self):
        result = self.pipeline()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.local / native.EXECUTABLE).read_bytes(), b"fresh macOS fixture")
        self.assertEqual((self.local / native.CONTENTS / "Windows64/CLD2.4DX").read_bytes(),
                         b"fresh Windows fixture")
        self.assertEqual((self.local / native.CONTENTS / "_CodeSignature/CodeResources").read_bytes(),
                         b"fresh signature")
        calls = self.calls()
        index = lambda name: next(i for i, call in enumerate(calls) if call[0] == name)
        self.assertLess(index("cmake"), index("lipo"))
        self.assertLess(index("lipo"), index("codesign"))
        self.assertLess(index("codesign"), index("ditto"))
        self.assertEqual(sum(call[:3] == ["xcrun", "notarytool", "submit"] for call in calls), 2)
        self.assertIn(["xcrun", "stapler", "staple", f"CLD2-{self.version}.dmg"], calls)
        self.assertEqual(native.validate_final(self.local), self.version)
        api = [json.loads(row) for row in self.api_log.read_text().splitlines()]
        self.assertEqual(sum(row["method"] == "POST" for row in api), 4)
        self.assertTrue(self.git("status", "--porcelain"))

    def test_windows_original_recipe_actual_powershell_closed_path(self):
        self.phase("windows", powershell=True)
        self.assertEqual((self.local / native.WINDOWS).read_bytes(), b"fresh Windows fixture")
        self.assertEqual([call for call in self.calls() if call[0] == "cmake"],
                         [["cmake", "..", "-A", "x64"],
                          ["cmake", "--build", ".", "--config", "Release"]])

    def test_windows_native_configure_build_and_missing_artifact_failures(self):
        initial = self.root / "initial"
        shutil.copytree(self.local, initial)
        for i, extra in enumerate(({"FAIL_CMAKE": "configure"}, {"FAIL_CMAKE": "build"},
                                    {"STALE_BUILD": "1"}, {"FAIL_TOOL": "cmake"})):
            checkout = self.root / f"case-{i}"
            shutil.copytree(initial, checkout)
            env = {**self.env, "OFFLINE_CHECKOUT": str(checkout), **extra}
            result = subprocess.run(
                ["/usr/local/bin/pwsh", "-NoLogo", "-NoProfile", "-NonInteractive",
                 "-File", ".github/scripts/native.ps1"],
                cwd=checkout, env=env, text=True, capture_output=True, timeout=60)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.api_log.exists())

    def test_every_native_credential_arch_sign_notary_staple_failure_never_publishes(self):
        cases = [{"FAIL_TOOL": name} for name in
                 ("base64", "security", "xcrun", "cmake", "lipo", "codesign", "ditto", "hdiutil")]
        cases += [{"FAIL_CMAKE": "configure"}, {"FAIL_CMAKE": "build"}, {"STALE_BUILD": "1"},
                  {"ARCHES": "arm64e x86_64"}, {"ARCHES": "arm64 x86_64h"},
                  {"MISSING_IDENTITY": "1"}, {"FAIL_VERIFY": "1"}, {"STAPLE_EXIT": "8"}]
        for suffix in ("ZIP", "DMG"):
            cases += [{"NOTARY_EXIT_" + suffix: "5"},
                      {"NOTARY_JSON_" + suffix: '{"status":"Invalid"}'}]
            cases += [{"NOTARY_JSON_" + suffix: raw} for raw in (
                "not json", "[]", "{}", '{"status":"Invalid","status":"Accepted"}',
                '{"status":"Accepted","extra":{"id":1,"id":2}}',
                '{"status":"Accepted","extra":NaN}', '{"status":"Accepted","extra":Infinity}',
                '{"status":"Accepted","extra":-Infinity}', '{"status":"Accepted","extra":1e999}')]
        for i, extra in enumerate(cases):
            with self.subTest(extra=extra):
                checkout = self.root / f"case-{i}"
                shutil.copytree(self.local, checkout)
                self.log.unlink(missing_ok=True)
                self.api_log.unlink(missing_ok=True)
                self.state.write_text("{}")
                result = self.pipeline(checkout, extra)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = [json.loads(row) for row in self.api_log.read_text().splitlines()]
                self.assertFalse(any(row["method"] == "POST" for row in calls), calls)

    def test_exact_architecture_tokens_extras_permitted(self):
        self.phase("build", extra={"ARCHES": "arm64 x86_64 arm64e i386"})
        for output in ("arm64e x86_64", "arm64 x86_64h", "", "i386"):
            with self.assertRaises(ValueError):
                native.architectures(output)

    def cleanup_negative(self, kind, platform="macos"):
        self.populate()
        earlier = self.local / native.CONTENTS / "Info.plist"
        later = self.local / native.CONTENTS / "Windows64/CLD2.4DX"
        before = (earlier.read_bytes(), later.read_bytes())
        build = self.local / native.BUILD
        build.mkdir()
        path = build / "CMakeCache.txt"
        path.write_bytes(b"late cache")
        other = self.root / "same-bytes"
        other.write_bytes(b"late cache")
        if kind == "wrongtype":
            path.unlink()
            path.mkdir()
        elif kind == "inaccessible":
            path.chmod(0)
        elif kind == "ancestor":
            build.rename(self.root / "moved-build")
            build.symlink_to(self.root / "moved-build", target_is_directory=True)
        elif kind == "symlink":
            path.unlink()
            path.symlink_to(other)
        elif kind == "nested-git":
            (build / ".git").mkdir()
        elif kind == "unexpected":
            (build / "empty").mkdir()
            (build / "empty/arbitrary.cpp").write_bytes(b"protected")
        elif kind == "fifo":
            path.unlink()
            os.mkfifo(path)
        elif kind == "directory":
            directory = self.local / native.CONTENTS / "_CodeSignature"
            directory.chmod(0)
        result = self.cli(".github/scripts/native.py", "clean-" + platform, env=self.env)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual((earlier.read_bytes(), later.read_bytes()), before)
        self.assertFalse(self.log.exists(), "No native command may precede cleanup validation")
        self.assertFalse(self.api_log.exists())
        if kind == "wrongtype":
            path.rmdir()
            path.write_bytes(b"late cache")
        elif kind == "inaccessible":
            path.chmod(0o644)
        elif kind == "ancestor":
            build.unlink()
            (self.root / "moved-build").rename(build)
        elif kind == "symlink":
            path.unlink()
            path.write_bytes(other.read_bytes())
        elif kind == "nested-git":
            (build / ".git").rmdir()
        elif kind == "unexpected":
            (build / "empty/arbitrary.cpp").unlink()
        elif kind == "fifo":
            path.unlink()
            path.write_bytes(b"late cache")
        elif kind == "directory":
            (self.local / native.CONTENTS / "_CodeSignature").chmod(0o755)
        manifest = self.local / native.CONTENTS / "Resources/manifest.json"
        saved = manifest.read_bytes()
        result = self.cli(".github/scripts/native.py", "clean-" + platform, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(manifest.read_bytes(), saved)
        self.assertEqual((self.local / "CLD2/manifest.json").read_bytes(), saved)
        self.assertFalse(path.exists())

    def test_closed_cli_cleanup_prevalidates_late_wrongtype_before_firstdelete(self):
        self.cleanup_negative("wrongtype")

    def test_closed_cli_cleanup_prevalidates_late_inaccessible_before_firstdelete(self):
        self.cleanup_negative("inaccessible")

    def test_closed_cli_cleanup_prevalidates_ancestor_links(self):
        self.cleanup_negative("ancestor")

    def test_closed_cli_cleanup_prevalidates_samebytes_links(self):
        self.cleanup_negative("symlink")

    def test_closed_cli_cleanup_prevalidates_nested_git(self):
        self.cleanup_negative("nested-git")

    def test_closed_cli_cleanup_prevalidates_empty_auxiliary_directory_unexpected_leaf(self):
        self.cleanup_negative("unexpected")

    def test_closed_cli_cleanup_prevalidates_nonregular_fifo(self):
        self.cleanup_negative("fifo")

    def test_closed_cli_cleanup_prevalidates_late_inaccessible_directory(self):
        self.cleanup_negative("directory")

    def test_unsigned_gate_separate_from_final_and_no_sign_on_invalid_leaves(self):
        self.populate()
        signature = self.local / native.CONTENTS / "_CodeSignature/CodeResources"
        signature.unlink()
        native.validate(self.local)
        with self.assertRaises(ValueError):
            native.validate_final(self.local)
        for relative in native.LEAVES[:-1]:
            path = self.local / relative
            saved = path.read_bytes()
            for kind in ("missing", "empty", "directory", "symlink"):
                path.unlink()
                if kind == "empty":
                    path.write_bytes(b"")
                elif kind == "directory":
                    path.mkdir()
                elif kind == "symlink":
                    target = self.root / "same-output"
                    target.write_bytes(saved)
                    path.symlink_to(target)
                self.log.unlink(missing_ok=True)
                self.phase("sign", success=False)
                self.assertFalse(self.log.exists())
                if kind == "directory":
                    path.rmdir()
                elif path.exists() or path.is_symlink():
                    path.unlink()
                path.write_bytes(saved)
        self.phase("sign")
        native.validate_final(self.local)
