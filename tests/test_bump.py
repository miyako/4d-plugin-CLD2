"""Actual bare-Git races, detached CLI identity, and every-call executable guards."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

from helper_support import GitFixture, cwd, source
import bump


class BumpTests(GitFixture):
    def setUp(self):
        super().setUp()
        self.hook = self.local / ".github/hooks/pre-push"
        self.before = {name: (self.local / name).read_bytes()
                       for name in ("VERSION", "CLD2/CMakeLists.txt", "CLD2/Info.plist")}

    def call(self):
        with cwd(self.local), patch.dict(os.environ, self.env, clear=True), \
                patch.object(bump, "HOOK", self.hook):
            return bump.bump_branch(self.sha, self.ref, "patch")

    def command(self, env=None):
        return self.cli(".github/scripts/bump.py", "patch", "--sha", self.sha,
                        "--ref", self.ref, env=env)

    def test_detached_no_identity_single_parent_version_only_literal_trailer_no_tags(self):
        self.git("tag", "-a", "unrelated", "-m", "negative control")
        self.git("checkout", "--quiet", "--detach", self.sha)
        self.git("config", "--unset-all", "user.name")
        self.git("config", "--unset-all", "user.email")
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stderr)
        new = self.git("rev-parse", "HEAD")
        self.assertEqual(self.remote(), new)
        self.assertEqual(self.git("rev-list", "--parents", "-n", "1", new), f"{new} {self.sha}")
        self.assertEqual(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", new), "VERSION")
        for name in ("CLD2/CMakeLists.txt", "CLD2/Info.plist"):
            self.assertEqual((self.local / name).read_bytes(), self.before[name])
        self.assertTrue(self.git("log", "-1", "--format=%B").endswith(
            "Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>"))
        identity = "github-actions[bot] <github-actions[bot]@users.noreply.github.com>"
        self.assertEqual(self.git("log", "-1", "--format=%an <%ae>%n%cn <%ce>"),
                         identity + "\n" + identity)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("--git-dir=" + str(self.bare), "tag", "--list"), "")
        self.assertEqual(self.git("config", "push.followTags"), "true")
        version = source.read(self.local)
        old = source.read()
        self.assertEqual(version, old.rsplit(".", 1)[0] + "." + str(int(old.split(".")[-1]) + 1))

    def test_followtags_negative_control_really_follows(self):
        self.git("tag", "-a", "control", "-m", "fixture only")
        self.git("push", "--quiet", "origin", f"HEAD:{self.ref}")
        self.assertEqual(self.git("--git-dir=" + str(self.bare), "tag", "--list"), "control")

    def test_invalid_ref_sha_guard_and_dirty_inputs_zero_write(self):
        for ref in ("selected", "refs/tags/v1.0.0", "refs/heads/a..b"):
            result = self.cli(".github/scripts/bump.py", "patch", "--sha", self.sha, "--ref", ref)
            self.assertNotEqual(result.returncode, 0)
        for sha in ("a" * 39, "A" * 40, self.ancestor):
            result = self.cli(".github/scripts/bump.py", "patch", "--sha", sha, "--ref", self.ref)
            self.assertNotEqual(result.returncode, 0)
        for flag in ("assume-unchanged", "skip-worktree"):
            self.git("update-index", "--" + flag, "--", "VERSION")
            (self.local / "VERSION").write_bytes(b"9.8.7\n")
            self.assertNotEqual(self.command().returncode, 0)
            (self.local / "VERSION").write_bytes(self.before["VERSION"])
            self.git("update-index", "--no-" + flag, "--", "VERSION")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.sha)
        self.assertEqual(self.remote(), self.sha)

    def peer(self):
        self.git("commit", "--quiet", "--allow-empty", "-m", "peer advance")
        peer = self.git("rev-parse", "HEAD")
        self.git("--git-dir=" + str(self.bare), "fetch", "--quiet", "--no-tags",
                 str(self.local), peer)
        self.git("reset", "--quiet", "--hard", self.sha)
        return peer

    def test_initial_advertised_advance_rewind_delete_are_zero_write(self):
        peer = self.peer()
        for sha in (peer, self.ancestor, "0" * 40):
            self.git("--git-dir=" + str(self.bare), "update-ref", self.ref, sha)
            self.assertNotEqual(self.command().returncode, 0)
            self.assertEqual(self.git("rev-parse", "HEAD"), self.sha)
            self.assertEqual((self.local / "VERSION").read_bytes(), self.before["VERSION"])
        self.git("--git-dir=" + str(self.bare), "update-ref", self.ref, self.sha)

    def race(self, kind):
        peer = self.peer()
        self.git("tag", "-a", "must-not-follow", "-m", "fixture")
        real = bump.run
        expected, pushes = None, 0

        def intercept(*args, **kwargs):
            nonlocal expected, pushes
            if "push" in args:
                pushes += 1
                new = self.git("rev-parse", "HEAD")
                if kind == "same-result":
                    self.git("--git-dir=" + str(self.bare), "fetch", "--quiet", "--no-tags",
                             str(self.local), new)
                expected = {"advance": peer, "rewind": self.ancestor,
                            "delete": "0" * 40, "same-result": new}[kind]
                self.git("--git-dir=" + str(self.bare), "update-ref", self.ref, expected)
            return real(*args, **kwargs)

        with patch.object(bump, "run", side_effect=intercept):
            with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                self.call()
        self.assertEqual(pushes, 1)
        if kind == "delete":
            self.assertNotEqual(self.git("--git-dir=" + str(self.bare), "rev-parse",
                                         "--verify", self.ref, check=False).returncode, 0)
        else:
            self.assertEqual(self.remote(), expected)
        self.assertEqual(self.git("--git-dir=" + str(self.bare), "tag", "--list"), "")

    def test_real_advertisement_advance_after_final_read(self):
        self.race("advance")

    def test_real_advertisement_rewind_after_final_read(self):
        self.race("rewind")

    def test_real_advertisement_delete_after_final_read(self):
        self.race("delete")

    def test_real_advertisement_same_result_zero_records_after_final_read(self):
        self.race("same-result")

    def test_postadvertisement_nonforce_update_cannot_overwrite_peer(self):
        peer = self.peer()
        receive = self.bare / "hooks/pre-receive"
        receive.parent.mkdir(exist_ok=True)
        receive.write_text("#!/bin/sh\nset -eu\nunset GIT_QUARANTINE_PATH\n"
                           f'git --git-dir="{self.bare}" update-ref "{self.ref}" "{peer}" "{self.sha}"\n')
        receive.chmod(0o755)
        self.assertNotEqual(self.command().returncode, 0)
        self.assertEqual(self.remote(), peer)

    def guarded_cli(self, late=None):
        tools = self.closed_tools()
        (tools / "git").unlink()
        log, reads = self.root / "git.jsonl", self.root / "reads"
        saved = self.root / "same-guard"
        saved.write_bytes(self.hook.read_bytes())
        saved.chmod(0o755)
        wrapper = tools / "git"
        wrapper.write_text(f"""#!{sys.executable}
import json,os,pathlib,subprocess,sys
args=sys.argv[1:]
with open(os.environ['GUARD_LOG'],'a') as out: out.write(json.dumps(args)+'\\n')
result=subprocess.run([{shutil.which("git")!r},*args],capture_output=True)
if args[:3]==['ls-remote','--refs','origin'] and result.returncode==0:
    counter=pathlib.Path(os.environ['GUARD_READS'])
    count=int(counter.read_text())+1 if counter.exists() else 1
    counter.write_text(str(count))
    if count==2 and os.environ.get('TAMPER'):
        hook=pathlib.Path('.github/hooks/pre-push')
        hook.unlink()
        if os.environ['TAMPER']=='symlink': hook.symlink_to(os.environ['GUARD_SAVED'])
        elif os.environ['TAMPER']=='replacement':
            hook.write_bytes(b'#!/bin/sh\\nexit 0\\n'); hook.chmod(0o755)
        elif os.environ['TAMPER']=='nonexec':
            hook.write_bytes(pathlib.Path(os.environ['GUARD_SAVED']).read_bytes()); hook.chmod(0o644)
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
sys.exit(result.returncode)
""")
        wrapper.chmod(0o755)
        env = {**self.env, "PATH": str(tools), "GUARD_LOG": str(log),
               "GUARD_READS": str(reads), "GUARD_SAVED": str(saved), "TAMPER": late or ""}
        result = self.command(env)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        calls = [json.loads(row) for row in log.read_text().splitlines()]
        self.assertFalse(any("push" in call for call in calls))
        self.assertEqual(self.remote(), self.sha)
        return reads

    def test_initial_samebytes_symlink_exit0_missing_nonexec_guards_zero_write(self):
        original = self.hook.read_bytes()
        same = self.root / "same"
        same.write_bytes(original)
        same.chmod(0o755)
        for kind in ("symlink", "replacement", "missing", "nonexec"):
            with self.subTest(kind=kind):
                self.hook.unlink(missing_ok=True)
                if kind == "symlink":
                    self.hook.symlink_to(same)
                elif kind != "missing":
                    self.hook.write_bytes(original if kind == "nonexec" else b"#!/bin/sh\nexit 0\n")
                    self.hook.chmod(0o644 if kind == "nonexec" else 0o755)
                result = self.command()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.remote(), self.sha)
                self.assertEqual(self.git("rev-parse", "HEAD"), self.sha)
                self.assertEqual((self.local / "VERSION").read_bytes(), self.before["VERSION"])
        self.hook.write_bytes(original)
        self.hook.chmod(0o755)

    def test_late_samebytes_symlink_guard_never_pushes(self):
        self.assertEqual(self.guarded_cli("symlink").read_text(), "2")

    def test_late_exit0_executable_guard_never_pushes(self):
        self.assertEqual(self.guarded_cli("replacement").read_text(), "2")

    def test_late_missing_guard_never_pushes(self):
        self.assertEqual(self.guarded_cli("missing").read_text(), "2")

    def test_late_nonexecutable_guard_never_pushes(self):
        self.assertEqual(self.guarded_cli("nonexec").read_text(), "2")

    def test_committed_guard_mode_and_absence_cannot_be_substituted(self):
        for kind in ("mode", "absent"):
            if kind == "mode":
                self.git("update-index", "--chmod=-x", "--", ".github/hooks/pre-push")
            else:
                self.git("update-index", "--force-remove", "--", ".github/hooks/pre-push")
            self.git("commit", "--quiet", "-m", "invalid guard fixture")
            self.hook.chmod(0o755)
            with cwd(self.local), patch.object(bump, "HOOK", self.hook):
                with self.assertRaises(ValueError):
                    bump.require_guard()

    def test_actual_guard_exact_one_record_head_old_new_ref_and_commit_contract(self):
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stderr)
        new = self.git("rev-parse", "HEAD")
        env = {**self.env, "BUMP_EXPECTED_SHA": self.sha,
               "BUMP_EXPECTED_REF": self.ref, "BUMP_NEW_SHA": new}
        row = f"{new} {new} {self.ref} {self.sha}\n"
        for local in (new, "HEAD"):
            result = self.cli(".github/scripts/bump.py", "--guard", env=env,
                              input=row.replace(new + " ", local + " ", 1))
            self.assertEqual(result.returncode, 0, result.stderr)
        for invalid in ("", row * 2, "malformed\n", row.replace(self.sha, self.ancestor),
                        row.replace(self.ref, "refs/heads/other"),
                        row.replace(new + " ", "refs/heads/selected ", 1),
                        row.replace(new, self.sha, 1)):
            self.assertNotEqual(self.cli(".github/scripts/bump.py", "--guard",
                                         env=env, input=invalid).returncode, 0)
        tree = self.git("rev-parse", "HEAD^{tree}")
        for parents, selected, message in (
                (["-p", self.sha, "-p", self.ancestor], tree, bump.TRAILER),
                (["-p", self.sha], self.git("rev-parse", self.sha + "^{tree}"), bump.TRAILER),
                (["-p", new], tree, bump.TRAILER),
                (["-p", self.sha], tree, "missing trailer")):
            child = self.git("commit-tree", selected, *parents, input=message + "\n")
            self.git("reset", "--quiet", "--hard", child)
            bad_env = {**env, "BUMP_NEW_SHA": child}
            result = self.cli(".github/scripts/bump.py", "--guard", env=bad_env,
                              input=f"{child} {child} {self.ref} {self.sha}\n")
            self.assertNotEqual(result.returncode, 0)
