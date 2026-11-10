"""Shared actual publication CLI harness for initialized and real-clone fixtures."""

import json
import subprocess
import sys

from helper_support import ROOT, source
import release


class ReleaseCLI:
    def setup_release_cli(self):
        self.tools = self.closed_tools()
        gh = self.tools / "gh"
        gh.write_text("#!" + sys.executable + "\n" + (ROOT / "tests/fake_gh.py").read_text())
        gh.chmod(0o755)
        self.log, self.state = self.root / "gh.jsonl", self.root / "state.json"
        self.state.write_text("{}")
        self.version = source.read(self.local)
        self.tag = "v" + self.version
        self.env.update(PATH=str(self.tools), GH_TOKEN="offline-fixture",
                        GITHUB_REPOSITORY="miyako/4d-plugin-CLD2",
                        GITHUB_OUTPUT=str(self.root / "output"),
                        GH_STATE=str(self.state), GH_LOG=str(self.log),
                        GH_BARE_ORIGIN=str(self.bare), GITHUB_SHA=self.sha)

    def select(self):
        self.sha = self.git("rev-parse", "HEAD")
        self.env["GITHUB_SHA"] = self.sha
        self.git("--git-dir=" + str(self.bare), "fetch", "--quiet", "--no-tags",
                 str(self.local), self.sha)

    def command(self, name="publish", *, env=None, assets=None, windows=False):
        args = [name, "--sha", self.sha]
        if name == "publish":
            args += release.asset_names(self.version) if assets is None else assets
        values = {**self.env, **(env or {})}
        if windows:
            bootstrap = (
                "import runpy,sys,types,os;from pathlib import Path;sys.dont_write_bytecode=True;"
                "sys.path.insert(0,'.github/scripts');import repository;"
                "repository.sys=types.SimpleNamespace(platform='win32');"
                "original=Path.lstat;"
                "target=os.environ.get('SIMULATED_REPARSE');"
                "Path.lstat=lambda p,*a,**k:("
                "types.SimpleNamespace(st_mode=original(p,*a,**k).st_mode,st_file_attributes=0x400)"
                "if target and str(p.absolute())==str(Path(target).absolute())"
                "else original(p,*a,**k));"
                "sys.argv=['.github/scripts/release.py',*sys.argv[1:]];"
                "runpy.run_path('.github/scripts/release.py',run_name='__main__')")
            return subprocess.run([sys.executable, "-c", bootstrap, *args], cwd=self.local,
                                  env=values, text=True, capture_output=True, timeout=60)
        return self.cli(".github/scripts/release.py", *args, env=values)

    def calls(self):
        return [json.loads(row) for row in self.log.read_text().splitlines()] if self.log.exists() else []

    def reset_api(self, state=None):
        self.state.write_text(json.dumps(state or {}))
        self.log.unlink(missing_ok=True)
        self.git("--git-dir=" + str(self.bare), "update-ref", "-d", "refs/tags/" + self.tag)

    def assert_no_api(self, name="publish", **kwargs):
        self.log.unlink(missing_ok=True)
        result = self.command(name, **kwargs)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.calls(), [], result.stderr)
        return result

    def assert_retained(self, data):
        for name, raw in data.items():
            self.assertEqual((self.local / name).read_bytes(), raw, name)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.sha)
