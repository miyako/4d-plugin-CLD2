#!/bin/bash
set -euo pipefail

case "${1:?native phase required}" in
  build)
    python3 .github/scripts/native.py clean-macos
    (
      cd CLD2
      mkdir -p cmake-build && cd cmake-build
      cmake .. -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_OSX_ARCHITECTURES="arm64;x86_64" \
        -DCMAKE_OSX_DEPLOYMENT_TARGET="${MACOS_DEPLOYMENT_TARGET:?}"
      cmake --build .
    )
    python3 .github/scripts/native.py architectures
    ;;
  merge)
    python3 - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, ".github/scripts")
import native
source = native.nonempty(native.DOWNLOAD)
target = native.regular(native.CONTENTS / "Windows64/CLD2.4DX")
if target.exists() and not target.is_file():
    raise ValueError("Windows merge destination must be a regular file")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(source.read_bytes())
native.validate()
PY
    echo "BUNDLE_PATH=CLD2/CLD2-test/Plugins/CLD2.bundle" >> "$GITHUB_ENV"
    ;;
  sign)
    python3 .github/scripts/native.py unsigned
    IDENTITY=$(security find-identity -v -p codesigning "$KEYCHAIN_PATH" \
      | grep "Developer ID Application" | head -1 | sed -E 's/.*"(.*)".*/\1/')
    test -n "$IDENTITY"
    codesign --verbose --deep --timestamp --force --options=runtime \
      --sign "$IDENTITY" "$BUNDLE_PATH"
    codesign --verify --deep --strict --verbose=2 "$BUNDLE_PATH"
    ;;
  package)
    VERSION=$(python3 .github/scripts/source_version.py)
    ZIP_PATH="CLD2-${VERSION}.zip"
    DMG_PATH="CLD2-${VERSION}.dmg"
    ditto -c -k --keepParent "$BUNDLE_PATH" "$ZIP_PATH"
    hdiutil create -format UDBZ -volname CLD2 -srcfolder "$BUNDLE_PATH" "$DMG_PATH"
    for asset in "$ZIP_PATH" "$DMG_PATH"; do
      xcrun notarytool submit "$asset" --keychain-profile "notarytool-profile" \
        --keychain "$KEYCHAIN_PATH" --wait --output-format json > "$RUNNER_TEMP/notary-result.json"
      python3 - "$RUNNER_TEMP/notary-result.json" <<'PY'
import sys
sys.path.insert(0, ".github/scripts")
from release import strict_json
from pathlib import Path
result = strict_json(Path(sys.argv[1]).read_text())
if not isinstance(result, dict) or result.get("status") != "Accepted":
    raise SystemExit("notarization did not return Accepted")
PY
    done
    xcrun stapler staple "$DMG_PATH"
    codesign --verify --deep --strict --verbose=2 "$BUNDLE_PATH"
    python3 .github/scripts/native.py validate
    echo "ZIP_PATH=$ZIP_PATH" >> "$GITHUB_ENV"
    echo "DMG_PATH=$DMG_PATH" >> "$GITHUB_ENV"
    ;;
  *)
    echo "unknown native phase: $1" >&2
    exit 1
    ;;
esac
