"""Actual CLI fail-closed publication matrices with independent fake gh and real Git."""

import json
from pathlib import Path
import plistlib
import subprocess
import sys
from unittest.mock import patch

from helper_support import GitFixture
from release_support import ReleaseCLI
import native
import release
import repository

BASE = "repos/miyako/4d-plugin-CLD2"


def entry(identifier=1, tag="v9.8.7", draft=False):
    return {"id": identifier, "tag_name": tag, "draft": draft, "prerelease": False}


def ref(tag, sha, kind="commit"):
    return {"ref": "refs/tags/" + tag, "object": {"sha": sha, "type": kind}}


class PublicationTests(ReleaseCLI, GitFixture):
    def setUp(self):
        super().setUp()
        self.setup_release_cli()
        for path in native.FILES:
            target = self.local / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(b"historical output")
        self.git("add", "-f", ".")
        self.git("commit", "--quiet", "-m", "tracked generated leaf fixture")
        self.select()
        self.protected = ("VERSION", "CLD2/Info.plist", "CLD2/CMakeLists.txt",
                          "CLD2/manifest.json", "CLD2/source.cpp", ".gitignore")
        self.baseline = {path: (self.local / path).read_bytes() for path in self.protected}

    def build(self):
        data = self.populate()
        for name in ("CMakeCache.txt", "CMakeFiles/CMakeDirectoryInformation.cmake",
                     "CMakeFiles/CLD2.dir/CLD2-4dplugin.cpp.o",
                     "CLD2.bundle/Contents/MacOS/CLD2"):
            path = self.local / native.BUILD / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fresh CMake output")
            data[str(native.BUILD / name)] = path.read_bytes()
        return data

    def test_clean_preflight_then_dirty_tracked_outputs_create_only_publication(self):
        result = self.command("preflight")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "output").read_text(),
                         f"version={self.version}\ntag={self.tag}\n")
        self.reset_api()
        data = self.build()
        self.assert_no_api("preflight")
        self.assertEqual(self.command("check").returncode, 0)
        self.reset_api()
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual([call["method"] for call in calls],
                         ["GET"] * 4 + ["POST", "GET", "POST", "POST", "POST"])
        self.assertEqual(calls[0]["endpoint"], "repos/miyako/4d-plugin-CLD2")
        self.assertFalse(any(call["endpoint"] == "user" for call in calls))
        self.assertEqual(calls[4]["payload"], {"ref": "refs/tags/" + self.tag, "sha": self.sha})
        self.assertEqual(calls[6]["payload"], {
            "tag_name": self.tag, "name": self.tag, "target_commitish": self.sha,
            "draft": False, "prerelease": False, "body": "", "generate_release_notes": False})
        self.assert_retained(data)
        self.assertTrue(self.git("status", "--porcelain"))

    def test_explicit_token_selected_sha_and_exact_case_fail_before_any_api(self):
        self.build()
        for env in ({"GH_TOKEN": ""}, {"GH_TOKEN": " ", "GITHUB_TOKEN": "not-accepted"},
                    {"GITHUB_REPOSITORY": "miyako/4d-plugin-cld2"},
                    {"GITHUB_REPOSITORY": "miyako/4d-plugin-stomp"},
                    {"GITHUB_SHA": "b" * 40}):
            self.assert_no_api(env=env)

    def test_installation_token_oracle_rejects_user_endpoint_but_actual_cld2_cli_succeeds(self):
        result = subprocess.run(
            [str(self.tools / "gh"), "api", "--method", "GET", "user"],
            cwd=self.local, env=self.env, text=True, capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("403", result.stderr)
        self.assertIn("installation token", result.stderr)
        self.reset_api()
        result = self.command("preflight")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[0]["endpoint"], "repos/miyako/4d-plugin-CLD2")
        self.assertFalse(any(call["endpoint"] == "user" for call in self.calls()))

    def test_actual_cli_independent_canonical_api_identity_and_authentication(self):
        self.build()
        for stage, values in (
                ("identity", [None, {}, {"id": 456, "full_name": "miyako/4d-plugin-cld2"},
                              {"id": True, "full_name": "miyako/4d-plugin-CLD2"},
                              {"id": 0, "full_name": "miyako/4d-plugin-CLD2"},
                              {"id": "456", "full_name": "miyako/4d-plugin-CLD2"}]),):
            for value in values:
                self.reset_api()
                result = self.command(env={"GH_OVERRIDE_STAGE": stage,
                                           "GH_OVERRIDE_JSON": json.dumps(value)})
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(all(call["method"] == "GET" for call in self.calls()))
        for mode in ("identity-401", "identity-403"):
            self.reset_api()
            result = self.command(env={"GH_MODE": mode})
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(self.calls()), 1)
            self.assertEqual(self.calls()[0]["endpoint"], "repos/miyako/4d-plugin-CLD2")
        # A wrong helper literal cannot teach this independent fake oracle a new identity.
        path = self.local / ".github/scripts/release.py"
        path.write_text(path.read_text().replace("miyako/4d-plugin-CLD2", "miyako/4d-plugin-stomp"))
        self.git("add", str(path))
        self.git("commit", "--quiet", "-m", "deliberately wrong repository helper")
        self.select()
        self.reset_api()
        result = self.command(env={"GITHUB_REPOSITORY": "miyako/4d-plugin-stomp"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WRONG CANONICAL CLD2 REPOSITORY", result.stderr)

    def test_all_release_pages_until_empty_drafts_and_prefix_refs(self):
        self.build()
        self.reset_api({"pages": [[entry(i + 1) for i in range(100)], [entry(101)], []],
                        "refs": [ref(self.tag + "0", self.sha), ref(self.tag + "-rc", self.sha)]})
        result = self.command("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        pages = [call["endpoint"] for call in self.calls() if "/releases?" in call["endpoint"]]
        self.assertEqual(pages, [BASE + f"/releases?per_page=100&page={i}" for i in (1, 2, 3)])
        for draft in (True, False):
            self.reset_api({"pages": [[entry()], [entry(2, self.tag, draft)], []]})
            self.assertNotEqual(self.command().returncode, 0)
            self.assertTrue(all(call["method"] == "GET" for call in self.calls()))

    def test_pages_refs_strict_json_schema_network_and_exact404_fail_closed(self):
        self.build()
        malformed = [None, {}, "[]", [None], [{}], [entry(True)], [entry(0)],
                     [dict(entry(), tag_name="")], [dict(entry(), draft=0)],
                     [dict(entry(), prerelease="false")], [entry(1), entry(1)]]
        for stage in ("page1", "page2"):
            for value in malformed:
                self.reset_api({"pages": [[entry(99)], []]})
                result = self.command(env={"GH_OVERRIDE_STAGE": stage,
                                           "GH_OVERRIDE_JSON": json.dumps(value)})
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(all(call["method"] == "GET" for call in self.calls()))
        for value in (None, {}, [None], [{}], [ref("vother", self.sha)],
                      [ref(self.tag, "short")], [ref(self.tag, self.sha, "blob")],
                      [ref(self.tag, self.sha), ref(self.tag, self.sha)]):
            self.reset_api()
            self.assertNotEqual(self.command(env={"GH_OVERRIDE_STAGE": "refs",
                                                  "GH_OVERRIDE_JSON": json.dumps(value)}).returncode, 0)
        for raw in ('not json', '{"id":1,"id":2}', '[NaN]', '[Infinity]', '[1e999]',
                    '[{"id":1,"tag_name":"v9.8.7","draft":false,"prerelease":false,"x":{"a":1,"a":2}}]'):
            self.reset_api()
            self.assertNotEqual(self.command(env={"GH_OVERRIDE_STAGE": "page1",
                                                  "GH_RAW_JSON": raw}).returncode, 0)
        for mode in ("later-error", "exact-network", "exact-auth", "exact-malformed404"):
            self.reset_api({"pages": [[entry()], []]})
            self.assertNotEqual(self.command(env={"GH_MODE": mode}).returncode, 0)
            self.assertTrue(all(call["method"] == "GET" for call in self.calls()))

    def test_all_final_native_leaves_actual_cli_missing_empty_directory_samebytes_symlink(self):
        data = self.build()
        for relative in native.FILES:
            path = self.local / relative
            saved = path.read_bytes()
            for kind in ("missing", "empty", "directory", "symlink"):
                with self.subTest(path=relative, kind=kind):
                    path.unlink()
                    if kind == "empty":
                        path.write_bytes(b"")
                    elif kind == "directory":
                        path.mkdir()
                    elif kind == "symlink":
                        peer = self.root / "same-native-bytes"
                        peer.write_bytes(saved)
                        path.symlink_to(peer)
                    self.assert_no_api()
                    if kind == "directory":
                        path.rmdir()
                    elif path.exists() or path.is_symlink():
                        path.unlink()
                    path.write_bytes(saved)
        result = self.command("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_retained(data)

    def test_final_static_metadata_exact_resources_and_download_windows_equality(self):
        data = self.build()
        for relative in (native.DOWNLOAD, native.CONTENTS / "Windows64/CLD2.4DX",
                         native.CONTENTS / "Resources/manifest.json"):
            path = self.local / relative
            saved = path.read_bytes()
            path.write_bytes(b"different nonempty bytes")
            self.assert_no_api()
            path.write_bytes(saved)
        path = self.local / native.CONTENTS / "Info.plist"
        saved = path.read_bytes()
        metadata = plistlib.loads(saved)
        for key in ("CFBundleVersion", "CFBundleShortVersionString", "CFBundleExecutable"):
            path.write_bytes(plistlib.dumps(dict(metadata, **{key: "9.8.7"})))
            self.assert_no_api()
        path.write_bytes(saved)
        self.assertEqual(self.command("check").returncode, 0)
        self.assert_retained(data)

    def test_source_raw_staged_reversed_hidden_index_initial_and_final(self):
        for final in (False, True):
            data = self.build() if final else {}
            for name in self.protected:
                path = self.local / name
                saved = path.read_bytes()
                for kind in ("raw", "staged", "reversed", "assume-unchanged", "skip-worktree"):
                    with self.subTest(final=final, name=name, kind=kind):
                        if kind in ("assume-unchanged", "skip-worktree"):
                            self.git("update-index", "--" + kind, "--", name)
                        path.write_bytes(saved + b" altered")
                        if kind in ("staged", "reversed"):
                            self.git("add", "--", name)
                        if kind == "reversed":
                            path.write_bytes(saved)
                        self.assert_no_api("publish" if final else "preflight")
                        if kind in ("assume-unchanged", "skip-worktree"):
                            self.git("update-index", "--no-" + kind, "--", name)
                        path.write_bytes(saved)
                        self.git("restore", "--staged", "--", name)
            self.reset_api()
            result = self.command("check" if final else "preflight")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assert_retained(data)

    def test_real_git_fsmonitor_vH_fh_source_initial_and_generated_final(self):
        data = {}
        for final, name in ((False, "CLD2/source.cpp"), (True, str(native.EXECUTABLE))):
            if final:
                data = self.build()
            self.git("config", "core.fsmonitor", "true")
            self.git("update-index", "--fsmonitor-valid", "--", name)
            under_v = self.git("ls-files", "-v", "--", name)
            under_f = self.git("ls-files", "-f", "--", name)
            self.assertEqual(under_v, "H " + name)
            self.assertEqual(under_f, "h " + name)
            self.assert_no_api("publish" if final else "preflight")
            self.git("config", "core.fsmonitor", "false")
            self.git("update-index", "--no-fsmonitor")
            self.reset_api()
            result = self.command("check" if final else "preflight")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_retained(data)

    def test_generated_index_hidden_flags_staging_and_unproven_outputs_before_api(self):
        data = self.build()
        name = str(native.EXECUTABLE)
        for flag in ("assume-unchanged", "skip-worktree"):
            self.git("update-index", "--" + flag, "--", name)
            self.assert_no_api()
            self.git("update-index", "--no-" + flag, "--", name)
        self.git("add", "--", name)
        self.assert_no_api()
        self.git("restore", "--staged", "--", name)
        for name in ("ignored.c", "new.cpp", "CLD2/cmake-build/unexpected.cpp",
                     "CLD2/cmake-build/CMakeFiles/CLD2.dir/unexpected.o",
                     "CLD2/cmake-build/XCBuildData/build.db",
                     "CLD2/cmake-build/CMakeFiles/unexpected/flags.make",
                     str(native.CONTENTS / "Resources/unexpected"),
                     str(native.CONTENTS / "MacOS/runtime.dylib")):
            path = self.local / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"unexpected ignored/source output")
            self.assert_no_api()
            path.unlink()
        self.assertEqual(self.command("check").returncode, 0)
        self.assert_retained(data)

    def test_historical_object_and_compiler_id_sources_immutable_final_and_cleanup_refuses(self):
        names = ("CLD2/cmake-build/CMakeFiles/CLD2.dir/CLD2-4dplugin.cpp.o",
                 "CLD2/cmake-build/CMakeFiles/3.31.0/CompilerIdC/CMakeCCompilerId.c")
        historical = {}
        for name in names:
            path = self.local / name
            path.parent.mkdir(parents=True, exist_ok=True)
            historical[name] = b"historical build input: " + name.encode()
            path.write_bytes(historical[name])
            self.assertTrue(native.generated(name))
            self.assertFalse(native.tracked_generated(name))
        self.git("add", "-f", "--", *names)
        self.git("commit", "--quiet", "-m", "selected historical CMake build inputs")
        self.select()
        result = self.command("preflight")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.build()
        # These selected inputs are not generated-output exemptions, even if a
        # build would otherwise use their names. Keep native outputs dirty.
        for name, raw in historical.items():
            (self.local / name).write_bytes(raw)
            data.pop(name, None)
        for name, raw in historical.items():
            with self.subTest(name=name):
                path = self.local / name
                mutation = raw + b" late source mutation"
                path.write_bytes(mutation)
                self.assert_no_api()
                self.assertEqual(path.read_bytes(), mutation)
                self.assert_retained(data)
                path.write_bytes(raw)
                self.reset_api()
                snapshot = {**data, **historical}
                cleanup = self.cli(".github/scripts/native.py", "clean-macos")
                self.assertNotEqual(cleanup.returncode, 0)
                self.assertIn("historical CMake build inputs", cleanup.stderr)
                self.assertIn(name, cleanup.stderr)
                self.assertEqual(self.calls(), [])
                self.assert_retained(snapshot)
                result = self.command("check")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_retained(snapshot)
                self.assertTrue(self.git("status", "--porcelain"))

    def test_index_only_cmake_input_cleanup_refusal_precedes_every_delete(self):
        data = self.build()
        name = "CLD2/cmake-build/CMakeFiles/3.31.0/CMakeSystem.cmake"
        path = self.local / name
        path.parent.mkdir(parents=True)
        path.write_bytes(b"indexed historical input")
        self.git("add", "-f", "--", name)
        self.assert_no_api()
        cleanup = self.cli(".github/scripts/native.py", "clean-macos")
        self.assertNotEqual(cleanup.returncode, 0)
        self.assertIn(name, cleanup.stderr)
        self.assertIn("historical CMake build inputs", cleanup.stderr)
        self.assertEqual(self.calls(), [])
        self.assert_retained(data)
        self.assertEqual(path.read_bytes(), b"indexed historical input")

    def test_both_gitlinks_selected_index_head_marker_raw_nested_flags(self):
        for final in (False, True):
            data = self.build() if final else {}
            for dependency in ("4D-Plugin-SDK", "cld2-src"):
                selected, other = self.dependency_shas[dependency], self.dependency_others[dependency]
                path = self.local / dependency / "nested/source.c"
                saved = path.read_bytes()
                for kind in ("index", "head", "marker", "symlink", "raw", "staged", "reversed",
                             "index-mode", "mode", "assume-unchanged", "skip-worktree",
                             "untracked", "ignored"):
                    with self.subTest(final=final, dependency=dependency, kind=kind):
                        moved = self.root / "moved"
                        extra = None
                        if kind == "index":
                            self.git("update-index", "--cacheinfo", "160000", other, dependency)
                        elif kind == "head":
                            self.git("-C", dependency, "checkout", "--quiet", "--detach", other)
                        elif kind == "marker":
                            (self.local / dependency / ".git").rename(moved)
                        elif kind == "symlink":
                            (self.local / dependency).rename(moved)
                            (self.local / dependency).symlink_to(moved, target_is_directory=True)
                        elif kind in ("untracked", "ignored"):
                            extra = self.local / dependency / ("ignored.c" if kind == "ignored" else "new.c")
                            extra.write_bytes(b"unexpected")
                        elif kind == "mode":
                            path.chmod(0o755)
                        elif kind == "index-mode":
                            self.git("-C", dependency, "update-index", "--chmod=+x", "--", "nested/source.c")
                        else:
                            if kind in ("assume-unchanged", "skip-worktree"):
                                self.git("-C", dependency, "update-index", "--" + kind, "--", "nested/source.c")
                            path.write_bytes(saved + b" mutation")
                            if kind in ("staged", "reversed"):
                                self.git("-C", dependency, "add", "nested/source.c")
                            if kind == "reversed":
                                path.write_bytes(saved)
                        self.assert_no_api("publish" if final else "preflight")
                        if kind == "symlink":
                            (self.local / dependency).unlink()
                            moved.rename(self.local / dependency)
                        elif kind == "marker":
                            moved.rename(self.local / dependency / ".git")
                        elif kind == "index":
                            self.git("update-index", "--cacheinfo", "160000", selected, dependency)
                        else:
                            if extra:
                                extra.unlink()
                            if kind in ("assume-unchanged", "skip-worktree"):
                                self.git("-C", dependency, "update-index", "--no-" + kind, "--", "nested/source.c")
                            self.git("-C", dependency, "reset", "--quiet", "--hard", selected)
            self.reset_api()
            result = self.command("check" if final else "preflight")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assert_retained(data)

    def test_windows_only_regular_raw_equal_mode_tolerance_root_and_dependencies(self):
        names = ((".", ".github/scripts/native.sh"), ("4D-Plugin-SDK", "tool.sh"),
                 ("cld2-src", "tool.sh"))
        for directory, name in names:
            self.git("-C", directory, "config", "core.filemode", "false")
            (self.local / directory / name).chmod(0o644)
        self.assert_no_api("preflight")
        result = self.command("preflight", windows=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for final in (False, True):
            data = self.build() if final else {}
            for directory, name in names:
                path = self.local / directory / name
                saved = path.read_bytes()
                for kind in ("raw", "staged", "reversed", "index-mode", "symlink", "directory"):
                    self.reset_api()
                    if kind == "index-mode":
                        self.git("-C", directory, "update-index", "--chmod=-x", "--", name)
                    elif kind in ("symlink", "directory"):
                        path.unlink()
                        if kind == "symlink":
                            target = self.root / "samebytes"
                            target.write_bytes(saved)
                            path.symlink_to(target)
                        else:
                            path.mkdir()
                    else:
                        path.write_bytes(saved + b"mutation")
                        if kind in ("staged", "reversed"):
                            self.git("-C", directory, "add", name)
                        if kind == "reversed":
                            path.write_bytes(saved)
                    self.assert_no_api("publish" if final else "preflight", windows=True)
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

    def test_windows_cli_reparse_source_native_leaf_and_ancestors_before_api(self):
        for final in (False, True):
            data = self.build() if final else {}
            targets = [".github/scripts/native.sh", ".github", "4D-Plugin-SDK/tool.sh",
                       "4D-Plugin-SDK", "cld2-src/nested", "cld2-src/nested/source.c"]
            if final:
                targets += [str(native.EXECUTABLE), str(native.CONTENTS)]
            for target in targets:
                self.assert_no_api("publish" if final else "preflight", windows=True,
                                   env={"SIMULATED_REPARSE": target})
            self.reset_api()
            result = self.command("check" if final else "preflight", windows=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assert_retained(data)

    def filter_guard(self, directory, name):
        for directory, name in ((directory, name),):
            path = self.local / directory / name
            saved = path.read_bytes()
            filter_path = self.root / ("filter-" + directory.replace(".", "root") + ".py")
            filter_path.write_text(f"import sys\nsys.stdin.buffer.read()\nsys.stdout.buffer.write({saved!r})\n")
            (self.local / directory / ".gitattributes").write_text(name + " filter=fixture\n")
            self.git("-C", directory, "config", "filter.fixture.clean",
                     f'"{sys.executable}" "{filter_path}"')
            self.git("-C", directory, "add", ".gitattributes")
            self.git("-C", directory, "commit", "--quiet", "-m", "filter fixture")
            if directory != ".":
                self.git("add", directory)
                self.git("commit", "--quiet", "-m", "bind dependency filter")
            self.select()
            for final in (False, True):
                if final:
                    self.build()
                path.write_bytes(b"raw mutation masked by clean filter")
                self.assertEqual(self.git("-C", directory, "diff", "--name-only", "HEAD", "--", name), "")
                self.assert_no_api("publish" if final else "preflight")
                path.write_bytes(saved)
            self.reset_api()
            result = self.command("check")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_raw_clean_filter_root_before_api(self):
        self.filter_guard(".", "CLD2/source.cpp")

    def test_raw_clean_filter_sdk_before_api(self):
        self.filter_guard("4D-Plugin-SDK", "nested/source.c")

    def test_raw_clean_filter_cld2_before_api(self):
        self.filter_guard("cld2-src", "nested/source.c")

    def test_exact_assets_nonempty_regular_paths_and_order_before_api(self):
        self.build()
        names = release.asset_names(self.version)
        for assets in ([], names[:1], names + names[:1], list(reversed(names)),
                       [names[0], names[0]], ["./" + name for name in names],
                       [str(self.local / name) for name in names]):
            self.assert_no_api(assets=assets)
        path = self.local / names[0]
        saved = path.read_bytes()
        for kind in ("empty", "symlink", "directory", "missing"):
            path.unlink()
            if kind == "empty":
                path.write_bytes(b"")
            elif kind == "symlink":
                path.symlink_to(names[1])
            elif kind == "directory":
                path.mkdir()
            self.assert_no_api()
            if kind == "directory":
                path.rmdir()
            elif path.exists() or path.is_symlink():
                path.unlink()
            path.write_bytes(saved)

    def test_late_occupancy_and_all_partial_failures_retain_outputs_never_retry_or_rollback(self):
        self.assertEqual(self.command("preflight").returncode, 0)
        data = self.build()
        for state in ({"pages": [[entry(1, self.tag, True)], []]},
                      {"refs": [ref(self.tag, self.sha)]}):
            self.reset_api(state)
            self.assertNotEqual(self.command().returncode, 0)
            self.assertTrue(all(call["method"] == "GET" for call in self.calls()))
        for mode, count in (("same-tag-race", 5), ("different-tag-race", 5),
                            ("tag-error", 5), ("bad-tag", 5), ("verify-error", 6),
                            ("bad-verify", 6), ("release-error", 7),
                            ("upload-zip", 8), ("upload-dmg", 9)):
            self.reset_api()
            result = self.command(env={"GH_MODE": mode})
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("Manual recovery required", result.stderr)
            self.assertEqual(len(self.calls()), count)
            self.assertFalse(any(call["method"] in ("PATCH", "DELETE") for call in self.calls()))
            self.assertIn("tag", json.loads(self.state.read_text()))
            self.assert_retained(data)

    def test_every_creation_verification_release_upload_response_schema(self):
        self.build()
        proper_ref = ref(self.tag, self.sha)
        proper_release = {
            "id": 789, "tag_name": self.tag, "name": self.tag, "target_commitish": self.sha,
            "draft": False, "prerelease": False, "body": "",
            "upload_url": "https://uploads.github.com/repos/miyako/4d-plugin-CLD2/releases/789/assets{?name,label}"}
        proper_upload = {"id": 45, "name": release.asset_names(self.version)[0],
                         "size": len(b"offline package"), "state": "uploaded"}
        refs = [None, [], {}, dict(proper_ref, ref="refs/tags/wrong"),
                ref(self.tag, "short"), ref(self.tag, self.sha, "tag")]
        releases = [None, [], {}, *(dict(proper_release, **{key: value}) for key, value in (
            ("id", True), ("id", 0), ("id", "789"), ("tag_name", "v900.800.700"),
            ("name", "wrong"), ("target_commitish", "b" * 40), ("draft", True),
            ("draft", 0), ("prerelease", True), ("body", "unexpected"),
            ("upload_url", "https://invalid.example/assets")))]
        uploads = [None, [], {}, *(dict(proper_upload, **{key: value}) for key, value in (
            ("id", True), ("id", 0), ("name", "wrong"), ("size", True),
            ("size", "15"), ("size", 0), ("state", "new")))]
        for stage, variants, count in (("tag", refs, 5), ("verify", refs, 6),
                                       ("release", releases, 7), ("upload", uploads, 8)):
            for value in variants:
                self.reset_api()
                result = self.command(env={"GH_OVERRIDE_STAGE": stage,
                                           "GH_OVERRIDE_JSON": json.dumps(value)})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Manual recovery required", result.stderr)
                self.assertEqual(len(self.calls()), count)
        self.reset_api({"pages": [[entry(1)], []]})
        self.assertNotEqual(self.command(env={"GH_MODE": "reused-id"}).returncode, 0)
        self.assertFalse(any("/assets?name=" in call["endpoint"] for call in self.calls()))


class RepositoryTypeTests(GitFixture):
    def test_reparse_regular_and_ancestor_never_normalized_even_on_windows(self):
        path = self.local / "CLD2/source.cpp"
        actual = path.lstat()
        import types
        reparse = types.SimpleNamespace(st_mode=actual.st_mode, st_file_attributes=0x400)
        original_lstat = Path.lstat

        def fake_lstat(value, *args, **kwargs):
            return reparse if value == path else original_lstat(value, *args, **kwargs)

        with patch.object(Path, "lstat", fake_lstat), patch.object(repository.sys, "platform", "win32"):
            with self.assertRaises(ValueError):
                repository.actual_blob(path)
        ancestor = path.parent
        status = ancestor.lstat()
        reparse_dir = types.SimpleNamespace(st_mode=status.st_mode, st_file_attributes=0x400)

        def fake_ancestor(value, *args, **kwargs):
            return reparse_dir if value == ancestor else original_lstat(value, *args, **kwargs)

        with patch.object(Path, "lstat", fake_ancestor), patch.object(repository.sys, "platform", "win32"):
            with self.assertRaises(ValueError):
                repository.actual_blob(path)
