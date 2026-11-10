"""VERSION controls archives only; source plist metadata is independent."""

import codecs
from pathlib import Path
import plistlib
import re
import xml.etree.ElementTree as ET

SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
PLIST_PATH = Path("CLD2/Info.plist")


def decode(raw):
    for bom, encoding in ((codecs.BOM_UTF8, "utf-8"),
                          (codecs.BOM_UTF16_LE, "utf-16-le"),
                          (codecs.BOM_UTF16_BE, "utf-16-be")):
        if raw.startswith(bom):
            return raw[len(bom):].decode(encoding), encoding, bom
    encoding = ("utf-16-be" if raw[0] == 0 else "utf-16-le") if b"\0" in raw else "utf-8"
    return raw.decode(encoding), encoding, b""


def canonical(value):
    if not isinstance(value, str) or not SEMVER.fullmatch(value):
        raise ValueError(f"not a canonical X.Y.Z version: {value!r}")
    return value


def metadata(raw):
    if raw.startswith(b"bplist"):
        # dict_type detects duplicate keys in binary as well as XML plists.
        class Unique(dict):
            def __setitem__(self, key, value):
                if key in self:
                    raise ValueError(f"duplicate plist key: {key}")
                super().__setitem__(key, value)
        result = plistlib.loads(raw, dict_type=Unique)
        if not isinstance(result, dict):
            raise ValueError("plist must be a dictionary")
    else:
        try:
            plist = ET.fromstring(decode(raw)[0])
        except ET.ParseError as error:
            raise ValueError(f"invalid plist XML: {error}") from error
        if plist.tag != "plist" or len(plist) != 1 or plist[0].tag != "dict":
            raise ValueError("plist must contain exactly one dictionary")
        elements = list(plist[0])
        if len(elements) % 2:
            raise ValueError("unpaired plist dictionary")
        result = {}
        for key, value in zip(elements[::2], elements[1::2]):
            if key.tag != "key" or key.text in result:
                raise ValueError("invalid or duplicate plist key")
            result[key.text] = value.text if value.tag == "string" else None
    canonical(result.get("CFBundleShortVersionString"))
    if "CFBundleVersion" in result:
        canonical(result["CFBundleVersion"])
    for key in ("CFBundleExecutable", "CFBundleIdentifier", "CFBundlePackageType", "CFBundleName"):
        if not isinstance(result.get(key), str) or not result[key] or re.search(r"[$@{}]", result[key]):
            raise ValueError(f"missing/invalid/unresolved plist {key}")
    return result


def source_metadata(root=Path(".")):
    return metadata((Path(root) / PLIST_PATH).read_bytes())


def read(root=Path(".")):
    root = Path(root)
    text, _, _ = decode((root / "VERSION").read_bytes())
    match = re.fullmatch(r"([0-9]+\.[0-9]+\.[0-9]+)(\r\n|\r|\n)?", text)
    if not match:
        raise ValueError("VERSION must contain exactly one canonical version")
    source_metadata(root)
    return canonical(match[1])


def bump(root, mode):
    version = read(root)
    major, minor, patch = map(int, version.split("."))
    if mode == "patch":
        patch += 1
    elif mode == "minor":
        minor, patch = minor + 1, 0
    elif mode == "major":
        major, minor, patch = major + 1, 0, 0
    else:
        raise ValueError("mode must be patch, minor or major")
    new = f"{major}.{minor}.{patch}"
    path = Path(root) / "VERSION"
    text, encoding, bom = decode(path.read_bytes())
    path.write_bytes(bom + text.replace(version, new, 1).encode(encoding))
    return new
