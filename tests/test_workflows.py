"""Immutable intake comparisons constrain every native recipe and unrelated test."""

import re
import subprocess
import unittest

import yaml
from helper_support import ROOT, original
import native


def load(name, intake=False):
    raw = original(".github/workflows/" + name) if intake else (
        ROOT / ".github/workflows" / name).read_bytes()
    return yaml.load(raw, Loader=yaml.BaseLoader)


class WorkflowTests(unittest.TestCase):
    def test_exact_manual_build_source_only_bump_and_no_linkage(self):
        build, bump = load("release.yml"), load("bump-version.yml")
        self.assertEqual(build["name"], "Build")
        self.assertEqual(build["on"], {"workflow_dispatch": ""})
        self.assertEqual(set(bump["on"]), {"workflow_dispatch"})
        inputs = bump["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"mode"})
        self.assertEqual(inputs["mode"], {
            "type": "choice", "description": "Semantic version bump",
            "options": ["patch", "minor", "major"], "default": "patch", "required": "true"})
        self.assertEqual(build["concurrency"],
                         {"group": "cld2-publication", "cancel-in-progress": "false"})
        for workflow in (build, bump):
            for job in workflow["jobs"].values():
                self.assertNotIn("if", job)
                for step in job["steps"]:
                    self.assertNotIn("if", step)
                    for forbidden in ("workflow run", "repository_dispatch", "workflow_dispatch"):
                        self.assertNotIn(forbidden, step.get("run", ""))
                    self.assertNotIn("${{", step.get("run", ""))
        raw = (ROOT / ".github/workflows/release.yml").read_text()
        for forbidden in ("inputs.", "github.ref", "softprops", "bump.py"):
            self.assertNotIn(forbidden, raw)

    def test_all_checkouts_sha_and_inherited_scoped_conversion_before_checkout(self):
        files = sorted((ROOT / ".github/workflows").glob("*.yml"))
        self.assertEqual([path.name for path in files], ["bump-version.yml", "release.yml", "test.yml"])
        for path in files:
            workflow = load(path.name)
            self.assertEqual(workflow["env"]["GIT_CONFIG_COUNT"], "1")
            self.assertEqual(workflow["env"]["GIT_CONFIG_KEY_0"], "core.autocrlf")
            self.assertEqual(workflow["env"]["GIT_CONFIG_VALUE_0"], "false")
            self.assertNotIn("git config --global", path.read_text())
            for job in workflow["jobs"].values():
                checkouts = [step for step in job["steps"] if
                             step.get("uses", "").startswith("actions/checkout@")]
                self.assertEqual(len(checkouts), 1)
                self.assertEqual(checkouts[0]["with"], {
                    "ref": "${{ github.sha }}", "submodules": "recursive", "fetch-depth": "0"})

    def test_original_test_trigger_topology_and_all_original_commands_exact(self):
        before, after = load("test.yml", True), load("test.yml")
        self.assertEqual(before["on"], after["on"])
        self.assertEqual(after["on"], {"push": {"tags": ["*"]}, "workflow_dispatch": ""})
        after.pop("env")
        steps = after["jobs"]["test"]["steps"]
        steps[0]["with"].pop("ref")
        for step in steps:
            if "run" in step:
                step["run"] = re.sub(r"^# shellcheck disable=SC[0-9]+\n", "", step["run"], flags=re.M)
        self.assertEqual(after, before)

    def test_intake_native_cmake_all_bytes_except_approved_single_cleanup_line(self):
        before = original("CLD2/CMakeLists.txt")
        after = (ROOT / "CLD2/CMakeLists.txt").read_bytes()
        self.assertEqual(after, before.replace(
            b'COMMAND ${CMAKE_COMMAND} -E remove_directory "${PLUGIN_OUTPUT}"',
            b'COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/../.github/scripts/native.py" clean-bundle'))
        for name in ("CLD2/Info.plist", "CLD2/manifest.json", ".gitmodules",
                     "CLD2/CLD2-test/Plugins/CLD2.bundle/Contents/Info.plist",
                     "CLD2/CLD2-test/Plugins/CLD2.bundle/Contents/MacOS/CLD2",
                     "CLD2/CLD2-test/Plugins/CLD2.bundle/Contents/Resources/manifest.json"):
            self.assertEqual((ROOT / name).read_bytes(), original(name), name)
        self.assertEqual(subprocess.check_output(["git", "ls-tree", "HEAD", "--",
                                                  "4D-Plugin-SDK", "cld2-src"], cwd=ROOT).decode(),
                         "160000 commit cd97d1876d4258b56d2516e8ad2816f4ee93e0b5\t4D-Plugin-SDK\n"
                         "160000 commit b56fa78a2fe44ac2851bae5bf4f4693a0644da7b\tcld2-src\n")

    def test_original_native_commands_and_outputs_are_not_reinvented(self):
        before, after = load("release.yml", True), load("release.yml")
        self.assertEqual(list(before["jobs"]), list(after["jobs"]))
        for name, job in after["jobs"].items():
            self.assertEqual(job["runs-on"], before["jobs"][name]["runs-on"])
            self.assertEqual(job.get("needs"), before["jobs"][name].get("needs"))
        mac_before = before["jobs"]["build-macos"]["steps"]
        mac_after = after["jobs"]["build-macos"]["steps"]
        get = lambda steps, name: next(step for step in steps if step.get("name") == name)
        for name in ("download windows binaries", "import Developer ID certificate"):
            self.assertEqual(get(mac_after, name), get(mac_before, name))
        credentials = get(mac_before, "store notarytool credentials")["run"]
        self.assertEqual(get(mac_after, "store notarytool credentials")["run"],
                         "set -euo pipefail\n" + credentials)
        windows = (ROOT / ".github/scripts/native.ps1").read_text()
        self.assertIn("Set-Location cmake-build", windows)
        self.assertIn("cmake .. -A x64\n", windows)
        self.assertIn("cmake --build . --config Release\n", windows)
        self.assertIn("catch [System.Management.Automation.ItemNotFoundException]", windows)
        self.assertNotIn("SilentlyContinue", windows)
        self.assertNotRegex(windows, r"catch\s*\{")
        native_shell = (ROOT / ".github/scripts/native.sh").read_text()
        expected_build = get(mac_before, "build macOS plugin (universal)")["run"].replace(
            "${{ env.PRODUCT_NAME }}", "CLD2").replace(
            "${{ env.MACOS_DEPLOYMENT_TARGET }}", "${MACOS_DEPLOYMENT_TARGET:?}")
        normalized = "\n".join(line.strip() for line in native_shell.splitlines())
        self.assertIn("\n".join(line.strip() for line in expected_build.splitlines()), normalized)
        self.assertIn("codesign --verbose --deep --timestamp --force --options=runtime", native_shell)
        self.assertIn('ditto -c -k --keepParent "$BUNDLE_PATH" "$ZIP_PATH"', native_shell)
        self.assertIn('hdiutil create -format UDBZ -volname CLD2 -srcfolder "$BUNDLE_PATH" "$DMG_PATH"',
                      native_shell)
        self.assertIn("codesign --verify --deep --strict", native_shell)
        self.assertEqual(str(native.WINDOWS),
                         "CLD2/CLD2-test/Plugins/CLD2/Contents/Windows64/CLD2.4DX")
        self.assertEqual(get(after["jobs"]["build-windows"]["steps"], "upload windows binaries")["with"],
                         {"name": "windows-binaries", "path": str(native.WINDOWS),
                          "if-no-files-found": "error"})

    def test_generated_paths_closed_families_no_broad_exemption(self):
        for path in ("CLD2/cmake-build/CMakeCache.txt",
                     "CLD2/cmake-build/CMakeFiles/CMakeDirectoryInformation.cmake",
                     "CLD2/cmake-build/CMakeFiles/CLD2.dir/CLD2-4dplugin.cpp.o",
                     "CLD2/cmake-build/CLD2.bundle/Contents/MacOS/CLD2"):
            self.assertTrue(native.generated(path), path)
        for path in ("CLD2/cmake-build/anything.o",
                     "CLD2/cmake-build/CMakeFiles/Other.dir/CLD2-4dplugin.cpp.o",
                     "CLD2/cmake-build/CMakeFiles/CLD2.dir/arbitrary/CLD2-4dplugin.cpp.o",
                     "CLD2/cmake-build/CMakeFiles/CLD2.dir/unexpected.cpp.o",
                     "CLD2/cmake-build/XCBuildData/build.db",
                     "CLD2/cmake-build/libarchive/libarchive.a",
                     "CLD2/CLD2-test/Plugins/Default/CLD2.bundle/Contents/Info.plist",
                     "CLD2/CLD2-test/Plugins/CLD2.bundle/Contents/Resources/arbitrary"):
            self.assertFalse(native.generated(path), path)
