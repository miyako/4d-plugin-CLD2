"""Actual workflow Bash and PowerShell execute only closed-PATH native oracles."""

import json
import os
from pathlib import Path
import re
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

    def ancestor_cleanup_command(self, platform, entry="cli"):
        if entry == "bash":
            script = next(step["run"] for step in self.jobs["build-macos"]["steps"]
                          if step.get("name") == "build macOS plugin (universal)")
            return ["/bin/bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script]
        if entry == "powershell":
            source = (self.local / ".github/scripts/native.ps1").read_text()
            # Execute the actual cleanup/build tail, not the initial global-clean
            # guard: stale outputs must reach cleanup to test this failure.
            script = source.splitlines()[0] + "\n" + source[source.index(
                "python .github/scripts/native.py clean-windows"):]
            return ["/usr/local/bin/pwsh", "-NoLogo", "-NoProfile", "-NonInteractive",
                    "-Command", script]
        if entry == "postbuild":
            source = (self.local / "CLD2/CMakeLists.txt").read_text()
            match = re.search(
                r'COMMAND python3 "\$\{CMAKE_CURRENT_SOURCE_DIR\}/../([^"]+)" (clean-bundle)',
                source)
            self.assertIsNotNone(match)
            self.assertEqual(platform, "bundle")
            return [str(self.tools / "python3"), match[1], match[2]]
        return [sys.executable, ".github/scripts/native.py", "clean-" + platform]

    def ancestor_outputs(self):
        data = self.populate()
        windows = self.local / native.WINDOWS
        windows.parent.mkdir(parents=True, exist_ok=True)
        windows.write_bytes(b"existing Windows output before ancestor check")
        resource = native.WINDOWS.parents[1] / "Resources/manifest.json"
        copied = self.local / resource
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_bytes((self.local / "CLD2/manifest.json").read_bytes())
        cache = self.local / native.BUILD / "CMakeCache.txt"
        cache.parent.mkdir(exist_ok=True)
        cache.write_bytes(b"later existing cache before ancestor check")
        data.update({str(native.WINDOWS): windows.read_bytes(), str(resource): copied.read_bytes(),
                     str(native.BUILD / "CMakeCache.txt"): cache.read_bytes()})
        return data

    def assert_ancestor_retained(self, data):
        for relative, raw in data.items():
            self.assertEqual((self.local / relative).read_bytes(), raw, relative)
        self.assertFalse(self.log.exists(), "Ancestor rejection must precede every native command")
        self.assertFalse(self.api_log.exists(), "Ancestor rejection must precede every API call")

    def ancestor_case(self, platform, ancestor, kind, entry="cli"):
        data = self.ancestor_outputs()
        self.log.unlink(missing_ok=True)
        self.api_log.unlink(missing_ok=True)
        marker = self.local / ancestor / ".git"
        if kind == "file":
            marker.write_bytes(b"gitdir: forbidden ancestor metadata\n")
        elif kind == "directory":
            marker.mkdir()
        elif kind == "symlink":
            target = self.root / "marker-target"
            target.write_bytes(b"existing metadata target")
            marker.symlink_to(target)
        elif kind == "dangling":
            marker.symlink_to(self.root / "absent-metadata-target")
        elif kind == "fifo":
            os.mkfifo(marker)
        command = self.ancestor_cleanup_command(platform, entry)
        if kind in ("reparse", "dangling-reparse", "permission", "io", "not-directory"):
            command = [sys.executable, "-c", f"""
import errno, runpy, stat, sys, types
from pathlib import Path
sys.path.insert(0, ".github/scripts")
target = Path({str(marker)!r})
kind = {kind!r}
original = Path.lstat
def lstat(path, *args, **kwargs):
    if path.absolute() == target:
        if kind in ("reparse", "dangling-reparse"):
            mode = stat.S_IFDIR if kind == "reparse" else stat.S_IFLNK
            return types.SimpleNamespace(st_mode=mode, st_file_attributes=0x400)
        if kind == "permission":
            raise PermissionError(errno.EACCES, "ancestor Git probe denied", str(path))
        if kind == "io":
            raise OSError(errno.EIO, "ancestor Git probe I/O failure", str(path))
        raise NotADirectoryError(errno.ENOTDIR, "ancestor Git probe wrong parent", str(path))
    return original(path, *args, **kwargs)
Path.lstat = lstat
sys.argv = [".github/scripts/native.py", {"clean-" + platform!r}]
runpy.run_path(".github/scripts/native.py", run_name="__main__")
"""]
        result = subprocess.run(command, cwd=self.local, env=self.env, text=True,
                                capture_output=True, timeout=60)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(str(marker), result.stderr)
        if kind == "permission":
            self.assertIn("PermissionError", result.stderr)
        elif kind in ("io", "not-directory"):
            self.assertIn("ancestor Git probe", result.stderr)
        else:
            self.assertIn("Git marker in native ancestor", result.stderr)
        self.assert_ancestor_retained(data)
        if kind == "directory":
            marker.rmdir()
        elif kind in ("file", "symlink", "dangling", "fifo"):
            marker.unlink()
        result = subprocess.run(self.ancestor_cleanup_command(platform, entry), cwd=self.local,
                                env=self.env, text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path in (native.CONTENTS / "Resources/manifest.json",
                     native.WINDOWS.parents[1] / "Resources/manifest.json"):
            self.assertEqual((self.local / path).read_bytes(), data[str(path)])
        self.assertEqual((self.local / "CLD2/manifest.json").read_bytes(),
                         data[str(native.CONTENTS / "Resources/manifest.json")])
        self.assertFalse(self.api_log.exists())

    def test_ancestor_git_physical_marker_all_cleanup_plans_before_any_unlink(self):
        for platform in ("macos", "windows", "bundle"):
            ancestors = ["CLD2", "CLD2/CLD2-test", "CLD2/CLD2-test/Plugins"]
            if platform != "bundle":
                ancestors.append(str(native.BUILD))
            for ancestor in ancestors:
                for kind in ("file", "directory", "symlink", "dangling", "fifo"):
                    with self.subTest(platform=platform, ancestor=ancestor, kind=kind):
                        self.ancestor_case(platform, ancestor, kind)

    def test_ancestor_git_reparse_and_typed_probe_errors_are_not_absence(self):
        for platform in ("macos", "windows", "bundle"):
            for ancestor in ("CLD2", "CLD2/CLD2-test/Plugins"):
                for kind in ("reparse", "dangling-reparse", "permission", "io", "not-directory"):
                    with self.subTest(platform=platform, ancestor=ancestor, kind=kind):
                        self.ancestor_case(platform, ancestor, kind)

    def test_ancestor_git_actual_extracted_bash_powershell_postbuild_no_native_or_api(self):
        for platform, entry in (("macos", "bash"), ("windows", "powershell"),
                                ("bundle", "postbuild")):
            ancestors = ["CLD2", "CLD2/CLD2-test", "CLD2/CLD2-test/Plugins"]
            if platform != "bundle":
                ancestors.append(str(native.BUILD))
            for ancestor in ancestors:
                with self.subTest(entry=entry, ancestor=ancestor):
                    self.ancestor_case(platform, ancestor, "directory", entry)

    def test_ancestor_git_relative_absolute_consistency_and_root_metadata_exemption(self):
        self.ancestor_outputs()
        for ancestor, leaf in (
                ("CLD2", native.EXECUTABLE), ("CLD2/CLD2-test", native.EXECUTABLE),
                ("CLD2/CLD2-test/Plugins", native.WINDOWS),
                (str(native.BUILD), native.BUILD / "CMakeCache.txt")):
            marker = self.local / ancestor / ".git"
            marker.write_bytes(b"gitdir: forbidden\n")
            for path in (leaf, self.local / leaf):
                result = self.cli("-c", (
                    "import sys;from pathlib import Path;sys.path.insert(0,'.github/scripts');"
                    f"import native;native.regular(Path({str(path)!r}),Path.cwd())"))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Git marker in native ancestor", result.stderr)
            marker.unlink()
            self.assertEqual(native.regular(leaf, self.local),
                             native.regular(self.local / leaf, self.local))
        # A real checkout may own either a .git directory or a worktree-style
        # gitfile. Neither is nested cleanup metadata, and dependencies are not walked.
        original_git = self.local / ".git"
        relocated = self.root / "legitimate-root.git"
        original_git.rename(relocated)
        original_git.write_text("gitdir: " + str(relocated) + "\n")
        self.assertEqual(self.git("rev-parse", "--show-toplevel"), str(self.local))
        for platform in ("macos", "windows", "bundle"):
            self.ancestor_outputs()
            result = self.cli(".github/scripts/native.py", "clean-" + platform)
            self.assertEqual(result.returncode, 0, result.stderr)
        for dependency in ("4D-Plugin-SDK", "cld2-src"):
            self.assertEqual(self.git("-C", dependency, "rev-parse", "HEAD"),
                             self.dependency_shas[dependency])
