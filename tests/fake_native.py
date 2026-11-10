"""Native and credential command oracle; no real developer or signing tool runs."""

import base64
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

tool, args = Path(sys.argv[0]).name, sys.argv[1:]
with open(os.environ["NATIVE_LOG"], "a") as out:
    out.write(json.dumps([tool, *args]) + "\n")
root = Path(os.environ["OFFLINE_CHECKOUT"])
contents = root / "CLD2/CLD2-test/Plugins/CLD2.bundle/Contents"
if os.environ.get("FAIL_TOOL") == tool:
    sys.exit(23)
if tool == "cmake":
    if args[0] == "--build":
        windows = "--config" in args
        assert args == (["--build", ".", "--config", "Release"] if windows else ["--build", "."])
        if os.environ.get("FAIL_CMAKE") == "build":
            sys.exit(4)
        if os.environ.get("STALE_BUILD"):
            sys.exit(0)
        if windows:
            path = root / "CLD2/CLD2-test/Plugins/CLD2/Contents/Windows64/CLD2.4DX"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fresh Windows fixture")
        else:
            subprocess.run([sys.executable, str(root / ".github/scripts/native.py"),
                            "clean-bundle"], cwd=root, check=True)
            target = contents / "MacOS/CLD2"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fresh macOS fixture")
            source = plistlib.loads((root / "CLD2/Info.plist").read_bytes())
            (contents / "Info.plist").write_bytes(plistlib.dumps(source, fmt=plistlib.FMT_BINARY))
            (contents / "Resources").mkdir(exist_ok=True)
            shutil.copyfile(root / "CLD2/manifest.json", contents / "Resources/manifest.json")
            (Path.cwd() / "CMakeCache.txt").write_bytes(b"fresh cache")
            output = Path.cwd() / "CMakeFiles/CLD2.dir/CLD2-4dplugin.cpp.o"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"fresh object")
            (Path.cwd() / "CMakeFiles/CMakeDirectoryInformation.cmake").write_bytes(b"directory metadata")
    else:
        assert args in (
            ["..", "-A", "x64"],
            ["..", "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_OSX_ARCHITECTURES=arm64;x86_64",
             "-DCMAKE_OSX_DEPLOYMENT_TARGET=10.13"]), args
        assert Path.cwd() == root / "CLD2/cmake-build"
        if os.environ.get("FAIL_CMAKE") == "configure":
            sys.exit(5)
elif tool == "lipo":
    assert args == ["-archs", str(contents / "MacOS/CLD2")], args
    print(os.environ.get("ARCHES", "arm64 x86_64"))
elif tool == "base64":
    assert args == ["--decode", "-o", str(Path(os.environ["RUNNER_TEMP"]) / "certificate.p12")]
    Path(args[-1]).write_bytes(base64.b64decode(sys.stdin.read()))
elif tool == "security":
    if args[0] == "find-identity":
        print("" if os.environ.get("MISSING_IDENTITY") else
              '  1) OFFLINE "Developer ID Application: Fixture"')
elif tool == "codesign":
    if "--verify" in args:
        assert "--deep" in args and "--strict" in args
        if os.environ.get("FAIL_VERIFY"):
            sys.exit(7)
    else:
        assert args == ["--verbose", "--deep", "--timestamp", "--force", "--options=runtime",
                        "--sign", "Developer ID Application: Fixture", str(contents.parent.relative_to(root))]
        (contents / "_CodeSignature").mkdir(exist_ok=True)
        (contents / "_CodeSignature/CodeResources").write_bytes(b"fresh signature")
elif tool in ("ditto", "hdiutil"):
    version = (root / "VERSION").read_text().strip()
    expected = f"CLD2-{version}.{'zip' if tool == 'ditto' else 'dmg'}"
    assert args[-1] == expected, args
    if tool == "ditto":
        assert args[:4] == ["-c", "-k", "--keepParent", str(contents.parent.relative_to(root))]
    else:
        assert args[:-1] == ["create", "-format", "UDBZ", "-volname", "CLD2",
                            "-srcfolder", str(contents.parent.relative_to(root))]
    Path(args[-1]).write_bytes(b"offline package")
elif tool == "xcrun":
    if args[:2] == ["notarytool", "submit"]:
        suffix = Path(args[2]).suffix[1:]
        assert args[3:] == ["--keychain-profile", "notarytool-profile", "--keychain",
                            os.environ["KEYCHAIN_PATH"], "--wait", "--output-format", "json"]
        print(os.environ.get("NOTARY_JSON_" + suffix.upper(),
                             os.environ.get("NOTARY_JSON", '{"id":"offline","status":"Accepted"}')))
        sys.exit(int(os.environ.get("NOTARY_EXIT_" + suffix.upper(),
                                   os.environ.get("NOTARY_EXIT", "0"))))
    elif args[:2] == ["stapler", "staple"]:
        if os.environ.get("STAPLE_EXIT"):
            sys.exit(int(os.environ["STAPLE_EXIT"]))
    else:
        assert args[:2] == ["notarytool", "store-credentials"], args
else:
    sys.exit("UNSTUBBED NATIVE TOOL: " + tool)
