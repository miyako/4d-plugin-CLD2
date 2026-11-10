"""Prevalidate exact CMake outputs before file-only cleanup; preserve source bytes."""

import argparse
import errno
import os
from pathlib import Path
import re
import stat
import subprocess

import repository
import version_model

ROOT = Path(__file__).absolute().parents[2]
PRODUCT = "CLD2"
BUNDLE = Path("CLD2/CLD2-test/Plugins/CLD2.bundle")
CONTENTS = BUNDLE / "Contents"
EXECUTABLE = CONTENTS / "MacOS/CLD2"
WINDOWS = Path("CLD2/CLD2-test/Plugins/CLD2/Contents/Windows64/CLD2.4DX")
DOWNLOAD = Path("winbuild/CLD2.4DX")
BUILD = Path("CLD2/cmake-build")
RESOURCES = ("manifest.json",)
LEAVES = (CONTENTS / "Info.plist", EXECUTABLE, CONTENTS / "Resources/manifest.json",
          CONTENTS / "Windows64/CLD2.4DX", CONTENTS / "_CodeSignature/CodeResources")
FILES = (*LEAVES, DOWNLOAD)
DIRECTORIES = (BUILD,)
BUILD_BUNDLE = BUILD / "CLD2.bundle"


def build_generated(path):
    path = Path(path)
    if not path.is_relative_to(BUILD):
        return False
    relative = path.relative_to(BUILD).as_posix()
    if relative in ("CMakeCache.txt", "Makefile", "cmake_install.cmake"):
        return True
    if relative in ("CLD2.bundle/Contents/Info.plist", "CLD2.bundle/Contents/MacOS/CLD2",
                    "CMakeFiles/CLD2.dir/Info.plist"):
        return True
    if not relative.startswith("CMakeFiles/"):
        return False
    if re.fullmatch(r"CMakeFiles/(?:cmake\.check_cache|Makefile2|Makefile\.cmake|"
                    r"TargetDirectories\.txt|progress\.marks|CMakeDirectoryInformation\.cmake|"
                    r"CMakeConfigureLog\.yaml|"
                    r"CMakeOutput\.log|CMakeError\.log|InstallScripts\.json)", relative):
        return True
    if re.fullmatch(r"CMakeFiles/[0-9.]+/(?:CMake(?:C|CXX)Compiler\.cmake|"
                    r"CMakeSystem\.cmake|CMakeDetermineCompilerABI_(?:C|CXX)\.bin|"
                    r"CompilerIdC/CMakeCCompilerId\.c|CompilerIdCXX/CMakeCXXCompilerId\.cpp|"
                    r"CompilerId(?:C|CXX)/a\.out)", relative):
        return True
    if re.fullmatch(r"CMakeFiles/CLD2\.dir/(?:build\.make|cmake_clean\.cmake|"
                    r"compiler_depend\.(?:make|ts|internal)|depend\.make|flags\.make|"
                    r"link\.txt|progress\.make|DependInfo\.cmake)", relative):
        return True
    if relative.startswith("CMakeFiles/CLD2.dir/"):
        name = path.name
        cmake = (ROOT / "CLD2/CMakeLists.txt").read_text()
        sources = set(re.findall(r"(?:[A-Za-z0-9_-]+\.(?:cc|cpp|c))", cmake))
        if not any(name in (source + ".o", source + ".o.d") for source in sources):
            return False
        object_path = relative.removeprefix("CMakeFiles/CLD2.dir/")
        if object_path in ("CLD2-4dplugin.cpp.o", "CLD2-4dplugin.cpp.o.d"):
            return True
        prefix = ROOT.as_posix().lstrip("/").replace(" ", "_") + "/"
        return object_path in {
            prefix + "cld2-src/internal/" + name,
            prefix + "4D-Plugin-SDK/4D_Plugin_API/" + name,
        } and (
            ("/cld2-src/internal/" in object_path
             and name.endswith((".cc.o", ".cc.o.d")))
            or ("/4D-Plugin-SDK/4D_Plugin_API/" in object_path
                and name in ("4DPluginAPI.c.o", "4DPluginAPI.c.o.d")))
    return False


def generated(path):
    path = Path(path)
    return path in FILES or build_generated(path)


def tracked_generated(path):
    return Path(path) in FILES


def historical_build_inputs(root):
    selected = repository.entries(repository.run(
        "git", "-C", str(root), "ls-tree", "-r", "-z", "HEAD"))
    indexed = repository.entries(repository.run(
        "git", "-C", str(root), "ls-files", "--stage", "-z"), index=True)
    return sorted(path for path in selected.keys() | indexed.keys()
                  if Path(path).is_relative_to(BUILD))


def regular(path, root=ROOT):
    root = Path(root).absolute()
    if any(repository.is_link(parent) for parent in (root, *root.parents)):
        raise ValueError(f"Native checkout has a link/reparse ancestor: {root}")
    path = Path(path)
    relative = path.relative_to(root) if path.is_absolute() else path
    if ".." in relative.parts or relative.is_absolute():
        raise ValueError("Native path escapes checkout")
    current = root
    for part in relative.parts:
        current /= part
        if part == ".git" or repository.is_link(current):
            raise ValueError(f"Git marker/link/reparse native path: {current}")
        try:
            status = current.lstat()
        except FileNotFoundError:
            continue
        if not (stat.S_ISDIR(status.st_mode) or stat.S_ISREG(status.st_mode)):
            raise ValueError(f"Unsupported native type: {current}")
        if stat.S_ISDIR(status.st_mode):
            if status.st_mode & 0o555 != 0o555 or not os.access(current, os.R_OK | os.X_OK):
                raise ValueError(f"Inaccessible native directory: {current}")
            try:
                (current / ".git").lstat()
            except FileNotFoundError as error:
                if error.errno != errno.ENOENT:
                    raise
            else:
                raise ValueError(f"Git marker in native ancestor: {current / '.git'}")
        elif status.st_mode & 0o444 == 0 or not os.access(current, os.R_OK):
            raise ValueError(f"Inaccessible native file: {current}")
    return root / relative


def nonempty(path, root=ROOT):
    path = regular(path, root)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing/empty/nonregular native leaf: {path}")
    with path.open("rb"):
        pass
    return path


def inspect_tree(relative, allowed, root=ROOT):
    root = Path(root).absolute()
    path = regular(relative, root)
    if not path.exists():
        return []
    if not path.is_dir():
        raise ValueError(f"Expected native output directory: {path}")
    checked = []
    for directory, dirs, files in os.walk(path, followlinks=False, onerror=raise_walk):
        for name in sorted(dirs + files):
            child = regular(Path(directory) / name, root)
            rel = child.relative_to(root)
            if child.is_dir() and allowed(rel):
                raise ValueError(f"Generated file has directory type: {rel}")
            if child.is_file():
                if not allowed(rel):
                    raise ValueError(f"Unexpected native leaf: {rel}")
                with child.open("rb"):
                    pass
                checked.append(child)
    return checked


def raise_walk(error):
    raise error


def validate_paths(paths, root=ROOT):
    for path in paths:
        regular(path, root)
    inspect_tree(BUILD, build_generated, root)
    inspect_tree(BUNDLE, lambda path: path in LEAVES, root)


def clean(platform, root=ROOT):
    root = Path(root).absolute()
    version_model.read(root)
    if platform not in ("macos", "windows", "bundle"):
        raise ValueError("Unknown cleanup platform")
    allowed = set(LEAVES if platform != "windows" else (
        WINDOWS, WINDOWS.parents[1] / "Resources/manifest.json"))
    output = BUNDLE if platform != "windows" else WINDOWS.parents[2]
    checked = inspect_tree(output, lambda path: path in allowed, root)
    if platform != "bundle":
        checked += inspect_tree(BUILD, build_generated, root)
        historical = historical_build_inputs(root)
        if historical:
            raise ValueError("Cleanup refuses selected/indexed historical CMake build inputs: "
                             + ", ".join(historical))
    # Validate absent leaf paths too: a late wrong-type directory cannot hide
    # merely because os.walk lists it as a directory rather than a file.
    for relative in allowed:
        path = regular(relative, root)
        if path.exists() and not path.is_file():
            raise ValueError(f"Generated leaf has wrong type: {path}")
    protected = {root / CONTENTS / "Resources/manifest.json",
                 root / WINDOWS.parents[1] / "Resources/manifest.json"}
    for path in checked:
        if not os.access(path.parent, os.W_OK) or path.parent.stat().st_mode & 0o222 == 0:
            raise ValueError(f"Unwritable cleanup parent: {path.parent}")
    for path in checked:
        if path not in protected:
            path.unlink()


def validate_resources(root=ROOT):
    source = nonempty(Path("CLD2/manifest.json"), root)
    target = nonempty(CONTENTS / "Resources/manifest.json", root)
    if source.read_bytes() != target.read_bytes():
        raise ValueError("Packaged resource differs from exact source manifest")


def verify_resources():
    validate_resources(Path("."))


def validate(root=ROOT):
    root = Path(root)
    version = version_model.read(root)
    built = version_model.metadata(nonempty(CONTENTS / "Info.plist", root).read_bytes())
    source = version_model.source_metadata(root)
    for key in ("CFBundleShortVersionString", "CFBundleVersion", "CFBundleExecutable",
                "CFBundleIdentifier", "CFBundlePackageType", "CFBundleName"):
        if built.get(key) != source.get(key):
            raise ValueError(f"Built plist differs from independent source {key}")
    for path in LEAVES[:-1]:
        nonempty(path, root)
    downloaded = nonempty(DOWNLOAD, root)
    if downloaded.read_bytes() != nonempty(CONTENTS / "Windows64/CLD2.4DX", root).read_bytes():
        raise ValueError("Merged Windows binary differs from downloaded artifact")
    validate_resources(root)
    inspect_tree(BUNDLE, lambda path: path in LEAVES, root)
    return version


def validate_final(root=Path(".")):
    version = validate(root)
    for path in FILES:
        nonempty(path, root)
    validate_paths((*FILES, *DIRECTORIES), root)
    return version


def architectures(output):
    if not {"arm64", "x86_64"} <= set(output.strip().split()):
        raise ValueError("Expected exact arm64 and x86_64 architecture tokens")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("clean-macos", "clean-windows", "clean-bundle",
                                           "validate", "unsigned", "architectures", "windows"))
    args = parser.parse_args()
    if args.command.startswith("clean-"):
        clean(args.command[6:])
    elif args.command == "validate":
        validate_final()
    elif args.command == "unsigned":
        validate()
    elif args.command == "windows":
        nonempty(WINDOWS)
    else:
        path = nonempty(EXECUTABLE)
        result = subprocess.run(["lipo", "-archs", str(path)], check=True,
                                text=True, capture_output=True)
        architectures(result.stdout)


if __name__ == "__main__":
    main()
