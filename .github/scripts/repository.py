"""Verify immutable Git bytes, including hidden index flags and dependency trees."""

import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

DEPENDENCIES = ("4D-Plugin-SDK", "cld2-src")


def run(*args, input=None, env=None):
    return subprocess.run(args, input=input, env=env, text=True, check=True,
                          stdout=subprocess.PIPE).stdout.rstrip("\n")


def selected_sha(sha):
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected immutable selected github.sha")
    if run("git", "rev-parse", "HEAD") != sha:
        raise ValueError("Checkout HEAD does not match selected SHA")


def entries(output, *, index=False):
    result = {}
    for record in filter(None, output.split("\0")):
        header, path = record.split("\t", 1)
        if index:
            mode, oid, stage = header.split()
            if stage != "0":
                raise ValueError("Unmerged index")
        else:
            mode, kind, oid = header.split()
            if kind != "blob" and not (
                    mode == "160000" and kind == "commit" and path in DEPENDENCIES):
                raise ValueError("Unsupported non-blob checkout entry")
        if mode not in ("100644", "100755", "160000") or (
                mode == "160000" and path not in DEPENDENCIES):
            raise ValueError("Unsupported checkout type")
        if path in result:
            raise ValueError("Duplicate checkout entry")
        result[path] = (mode, oid)
    return result


def is_link(path):
    try:
        status = Path(path).lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(status.st_mode) or bool(
        getattr(status, "st_file_attributes", 0) & 0x400)


def actual_blob(path):
    path = Path(path)
    if any(is_link(parent) for parent in path.parents) or is_link(path):
        raise ValueError(f"Link/reparse point in tracked path: {path}")
    status = path.lstat()
    if not stat.S_ISREG(status.st_mode):
        raise ValueError(f"Expected regular tracked file: {path}")
    data = path.read_bytes()
    oid = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    return ("100755" if status.st_mode & 0o111 else "100644"), oid


def worktree_matches(actual, expected):
    return actual[1] == expected[1] and (
        actual[0] == expected[0] or (
            sys.platform == "win32" and actual[0] in ("100644", "100755")
            and expected[0] in ("100644", "100755")))


def matches_blob(path, expected):
    return worktree_matches(actual_blob(path), expected)


def hidden_flags(root=Path(".")):
    for flag in ("-v", "-f"):
        if any(record and record[:2] != "H " for record in
               run("git", "-C", str(root), "ls-files", flag, "-z").split("\0")):
            raise ValueError("Hidden index/stat flags are unsupported")


def validate_dependency(path, sha):
    path = Path(path)
    if is_link(path) or not path.is_dir() or is_link(path / ".git"):
        raise ValueError("Dependency must be an initialized nonsymlink checkout")
    if not (path / ".git").exists():
        raise ValueError("Missing initialized dependency Git marker")
    git = lambda *args: run("git", "-C", str(path), *args)
    if git("rev-parse", "HEAD") != sha:
        raise ValueError("Dependency HEAD differs from selected gitlink")
    selected = entries(git("ls-tree", "-r", "-z", sha))
    indexed = entries(git("ls-files", "--stage", "-z"), index=True)
    if selected != indexed or any(mode == "160000" for mode, _ in selected.values()):
        raise ValueError("Dependency index differs or contains an unexpected nested gitlink")
    hidden_flags(path)
    if git("ls-files", "--others", "-z") or git("status", "--porcelain", "--ignored"):
        raise ValueError("Dependency source has tracked/untracked/ignored changes")
    for name, expected in selected.items():
        if not matches_blob(path / name, expected):
            raise ValueError(f"Raw dependency source differs: {path / name}")


def verify_checkout(sha, *, generated=lambda path: False,
                    tracked_generated=lambda path: False, assets=(), final=False):
    selected_sha(sha)
    selected = entries(run("git", "ls-tree", "-r", "-z", sha))
    indexed = entries(run("git", "ls-files", "--stage", "-z"), index=True)
    hidden_flags()
    if selected != indexed:
        raise ValueError("Index differs from immutable selected tree")
    for path, expected in selected.items():
        if expected[0] == "160000":
            validate_dependency(path, expected[1])
        elif not (final and tracked_generated(path)):
            if not matches_blob(path, expected):
                raise ValueError(f"Working source/config differs from selected SHA: {path}")
    untracked = filter(None, run("git", "ls-files", "--others", "-z").split("\0"))
    if any(not (final and (generated(path) or path in assets)) for path in untracked):
        raise ValueError("Untracked/ignored unexpected source/config/output")
    if not final and run("git", "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Preflight requires a completely clean source checkout")
