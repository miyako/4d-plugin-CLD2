import codecs
import plistlib

from helper_support import Fixture, ROOT, original, source
import version_model
import native


class VersionTests(Fixture):
    def setUp(self):
        super().setUp()
        self.sources()

    def test_original_authority_and_independent_metadata_are_preserved(self):
        self.assertEqual(original("VERSION"), b"1.0.5\n")
        self.assertEqual((ROOT / "CLD2/Info.plist").read_bytes(), original("CLD2/Info.plist"))
        for key in ("CFBundleShortVersionString", "CFBundleVersion"):
            self.assertEqual(version_model.source_metadata(self.root)[key], "1.0.0")
        cmake = (ROOT / "CLD2/CMakeLists.txt").read_text()
        self.assertNotIn("PLUGIN_VERSION", cmake)
        self.assertNotIn("VERSION", cmake.replace("cmake_minimum_required(VERSION 3.15)", ""))

    def test_modes_encoding_bom_lineendings_and_native_bytes(self):
        before = {name: (self.root / name).read_bytes()
                  for name in ("CLD2/CMakeLists.txt", "CLD2/Info.plist", "CLD2/manifest.json")}
        path = self.root / "VERSION"
        for encoding, bom in (("utf-8", b""), ("utf-8", codecs.BOM_UTF8),
                              ("utf-16-le", codecs.BOM_UTF16_LE),
                              ("utf-16-be", codecs.BOM_UTF16_BE)):
            for ending in ("", "\r\n", "\n", "\r"):
                for mode, expected in (("patch", "1.2.4"), ("minor", "1.3.0"), ("major", "2.0.0")):
                    with self.subTest(encoding=encoding, ending=ending, mode=mode):
                        path.write_bytes(bom + ("1.2.3" + ending).encode(encoding))
                        path.chmod(0o640)
                        self.assertEqual(source.bump(mode, self.root), expected)
                        self.assertEqual(path.read_bytes(), bom + (expected + ending).encode(encoding))
                        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        for name, raw in before.items():
            self.assertEqual((self.root / name).read_bytes(), raw)

    def test_invalid_version_or_plist_fails_before_any_write(self):
        path = self.root / "VERSION"
        for value in (b"", b"01.2.3", b"1.02.3\n", b"1.2.03", b"v1.2.3",
                      b"1.2.3-rc", b"1.2.3\n\n", b" 1.2.3", b"1.2.3 "):
            path.write_bytes(value)
            with self.assertRaises((ValueError, UnicodeError)):
                source.bump("patch", self.root)
            self.assertEqual(path.read_bytes(), value)
        path.write_bytes(b"1.2.3\n")
        plist = self.root / "CLD2/Info.plist"
        saved = plist.read_bytes()
        mutations = [
            saved.replace(b"<string>1.0.0</string>", b"<string>${UNRESOLVED}</string>"),
            saved.replace(b"<key>CFBundleShortVersionString</key>", b"<key>absent</key>"),
            saved.replace(b"</dict>", b"<key>CFBundleVersion</key><string>1.0.0</string></dict>"),
            saved.replace(b"<string>1.0.0</string>", b"<integer>1</integer>"), b"invalid"]
        duplicate = plistlib.loads(saved)
        duplicate["CFBundleVersioX"] = "1.0.0"
        mutations.append(plistlib.dumps(duplicate, fmt=plistlib.FMT_BINARY).replace(
            b"CFBundleVersioX", b"CFBundleVersion"))
        for raw in mutations:
            plist.write_bytes(raw)
            with self.assertRaises(ValueError):
                source.bump("patch", self.root)
            self.assertEqual(path.read_bytes(), b"1.2.3\n")

    def test_selected_static_metadata_may_differ_without_version_linkage(self):
        path = self.root / "CLD2/Info.plist"
        metadata = plistlib.loads(path.read_bytes())
        metadata.update(CFBundleShortVersionString="2.3.4", CFBundleVersion="7.8.9")
        raw = plistlib.dumps(metadata).decode().replace("<dict>\n", "<dict>\r\n")
        for encoding, bom in (("utf-8", codecs.BOM_UTF8),
                              ("utf-16-le", codecs.BOM_UTF16_LE),
                              ("utf-16-be", codecs.BOM_UTF16_BE)):
            text = raw.replace('encoding="UTF-8"', 'encoding="UTF-16"') if "16" in encoding else raw
            encoded = bom + text.encode(encoding)
            path.write_bytes(encoded)
            source.bump("patch", self.root)
            self.assertEqual(path.read_bytes(), encoded)
            for binary in (False, True):
                # Populate built metadata independently of the source XML encoding.
                self.populate(self.root, binary=binary)
                self.assertEqual(native.validate(self.root), source.read(self.root))

    def test_xml_and_binary_built_plists_match_static_source_not_archive_version(self):
        self.populate(self.root)
        for binary in (True, False):
            self.populate(self.root, binary=binary)
            self.assertEqual(native.validate(self.root), source.read(self.root))
            path = self.root / native.CONTENTS / "Info.plist"
            metadata = plistlib.loads(path.read_bytes())
            metadata["CFBundleShortVersionString"] = "9.8.7"
            path.write_bytes(plistlib.dumps(metadata))
            with self.assertRaises(ValueError):
                native.validate(self.root)

    def test_optional_build_key_and_mixed_source_endings_stay_independent(self):
        path = self.root / "CLD2/Info.plist"
        raw = path.read_bytes().replace(
            b"    <key>CFBundleVersion</key>\n    <string>1.0.0</string>\n", b"")
        raw = raw.replace(b"<dict>\n", b"<dict>\r\n")
        path.write_bytes(raw)
        self.assertNotIn("CFBundleVersion", version_model.source_metadata(self.root))
        source.bump("patch", self.root)
        self.assertEqual(path.read_bytes(), raw)
        self.populate(self.root)
        native.validate_final(self.root)
        built = self.root / native.CONTENTS / "Info.plist"
        metadata = plistlib.loads(built.read_bytes())
        metadata["CFBundleVersion"] = "1.0.0"
        built.write_bytes(plistlib.dumps(metadata))
        with self.assertRaises(ValueError):
            native.validate_final(self.root)
