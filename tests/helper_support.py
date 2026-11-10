"""Project-local disposable real-Git fixtures; never use host Git configuration."""

import contextlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).absolute().parents[1]
INTAKE = "7641e4506cc8199ef98d9ba9c6d80bb1be9084b0"
TRAILER = "Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>"
sys.path.insert(0, str(ROOT / ".github/scripts"))
import source_version as source
import native


@contextlib.contextmanager
def cwd(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def original(path):
    return subprocess.check_output(["git", "show", f"{INTAKE}:{path}"], cwd=ROOT)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / "tests" / (".offline-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)

    def write(self, relative, data):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def sources(self, destination=None):
        destination = self.root if destination is None else destination
        for name in ("VERSION", "CLD2/Info.plist", "CLD2/CMakeLists.txt", "CLD2/manifest.json"):
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        shutil.copytree(ROOT / ".github", destination / ".github",
                        ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)

    def populate(self, destination=None, *, binary=True):
        root = self.local if destination is None else destination
        for path in native.FILES:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if path == native.CONTENTS / "Info.plist":
                import plistlib
                metadata = plistlib.loads((root / "CLD2/Info.plist").read_bytes())
                target.write_bytes(plistlib.dumps(metadata, fmt=(
                    plistlib.FMT_BINARY if binary else plistlib.FMT_XML)))
            elif path == native.CONTENTS / "Resources/manifest.json":
                target.write_bytes((root / "CLD2/manifest.json").read_bytes())
            elif path in (native.DOWNLOAD, native.CONTENTS / "Windows64/CLD2.4DX"):
                target.write_bytes(b"fresh Windows fixture")
            else:
                target.write_bytes(b"fresh native fixture")
        for suffix in ("zip", "dmg"):
            (root / f"CLD2-{source.read(root)}.{suffix}").write_bytes(b"offline package")
        return {str(path): (root / path).read_bytes() for path in native.FILES}


class GitFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.local = self.root / "checkout"
        self.local.mkdir()
        self.bare = self.root / "origin.git"
        self.home = self.root / "home"
        self.home.mkdir()
        templates = self.root / "git-templates"
        templates.mkdir()
        self.env = {
            "PATH": os.environ["PATH"], "HOME": str(self.home),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.autocrlf",
            "GIT_CONFIG_VALUE_0": "false", "GIT_TERMINAL_PROMPT": "0",
            "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C", "LANG": "C",
            "GIT_EXEC_PATH": subprocess.check_output(["git", "--exec-path"], text=True).strip(),
            "GIT_TEMPLATE_DIR": str(templates)}
        self.git("init", "--quiet", "-b", "selected")
        for key, value in (("user.name", "Offline Fixture"),
                           ("user.email", "fixture@example.invalid"),
                           ("commit.gpgsign", "false"), ("tag.gpgsign", "false"),
                           ("core.filemode", "true"), ("push.followTags", "true"),
                           ("safe.bareRepository", "explicit")):
            self.git("config", key, value)
        self.git("commit", "--quiet", "--allow-empty", "-m", "ancestor")
        self.ancestor = self.git("rev-parse", "HEAD")
        self.sources(self.local)
        self.dependency_shas, self.dependency_others = {}, {}
        modules = ""
        for name in ("4D-Plugin-SDK", "cld2-src"):
            path = self.local / name
            path.mkdir()
            self.git("init", "--quiet", str(path))
            for key, value in (("user.name", "Offline Dependency"),
                               ("user.email", "dependency@example.invalid"),
                               ("commit.gpgsign", "false"), ("core.filemode", "true")):
                self.git("-C", name, "config", key, value)
            (path / "nested").mkdir()
            (path / "nested/source.c").write_bytes(b"immutable nested source\n")
            (path / "tool.sh").write_bytes(b"#!/bin/sh\nexit 0\n")
            (path / "tool.sh").chmod(0o755)
            (path / ".gitignore").write_bytes(b"ignored.c\n")
            self.git("-C", name, "add", ".")
            self.git("-C", name, "commit", "--quiet", "-m", "dependency source")
            self.dependency_shas[name] = self.git("-C", name, "rev-parse", "HEAD")
            self.git("-C", name, "commit", "--quiet", "--allow-empty", "-m", "alternate")
            self.dependency_others[name] = self.git("-C", name, "rev-parse", "HEAD")
            self.git("-C", name, "reset", "--quiet", "--hard", self.dependency_shas[name])
            modules += f'[submodule "{name}"]\n\tpath = {name}\n\turl = {path}\n'
        (self.local / ".gitmodules").write_text(modules)
        (self.local / ".gitignore").write_bytes(b"ignored.c\nCLD2/cmake-build/\n")
        (self.local / "CLD2/source.cpp").write_bytes(b"protected source\n")
        # Track the three historical packaged leaves, just as the real intake does.
        for name in ("Info.plist", "MacOS/CLD2", "Resources/manifest.json"):
            path = self.local / native.CONTENTS / name
            path.parent.mkdir(parents=True, exist_ok=True)
            source_path = self.local / ("CLD2/Info.plist" if name == "Info.plist"
                                       else "CLD2/manifest.json")
            path.write_bytes(b"historical executable" if name == "MacOS/CLD2"
                             else source_path.read_bytes())
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "selected source")
        self.sha = self.git("rev-parse", "HEAD")
        self.ref = "refs/heads/selected"
        self.git("init", "--bare", "--quiet", str(self.bare))
        self.git("remote", "add", "origin", str(self.bare))
        self.git("-c", "push.followTags=false", "push", "--quiet", "--no-follow-tags",
                 "origin", f"HEAD:{self.ref}")

    def git(self, *args, input=None, check=True):
        if "commit" in args and "-m" in args and TRAILER not in args:
            args = (*args, "-m", TRAILER)
        result = subprocess.run(["git", *args], cwd=self.local, env=self.env, input=input,
                                text=True, capture_output=True, check=check)
        return result.stdout.strip() if check else result

    def remote(self):
        return self.git("--git-dir=" + str(self.bare), "rev-parse", self.ref)

    def cli(self, relative, *args, env=None, input=None):
        return subprocess.run([sys.executable, relative, *args], cwd=self.local,
                              env=self.env if env is None else env, text=True, input=input,
                              capture_output=True, timeout=60)

    def closed_tools(self):
        tools = self.root / "tools"
        tools.mkdir(exist_ok=True)
        exec_path = subprocess.check_output(["git", "--exec-path"], text=True).strip()
        for name, executable in (
                ("git", shutil.which("git")), ("python", sys.executable),
                ("python3", sys.executable), ("git-upload-pack", exec_path + "/git-upload-pack"),
                ("git-receive-pack", exec_path + "/git-receive-pack")):
            path = tools / name
            if not path.exists():
                path.symlink_to(executable)
        return tools
