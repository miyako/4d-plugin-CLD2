# CLD2

A 4D plugin that wraps [Google's Compact Language Detector 2 (CLD2)](https://github.com/CLD2Owners/cld2) for automatic language detection. Pass any text and get back a structured object with the detected language, confidence info, and top-3 language candidates.

## Requirements

- 4D v21.1 or later

## Installation

Download the latest release from the [Releases](../../releases) page.

### macOS & Windows (single download)

1. Download the `.zip` from the release
2. Extract to get the `CLD2.bundle` folder
3. Copy the `.bundle` into your 4D application's **Plugins** folder (or your database's **Plugins** folder)
4. Restart 4D

### macOS only (notarized DMG)

1. Download the `.dmg` from the release
2. Mount it and copy the `.bundle` into your **Plugins** folder
3. Restart 4D

## Commands

### `CLD2`

Detects the language of the given text and returns a structured object.

```4d
$result:=CLD2($text)
```

| Parameter | Type | Direction | Description |
|---|---|---|---|
| `$text` | Text | in | The text to analyze |
| `$result` | Object | return | Detection results |

**Return object properties:**

| Property | Type | Description |
|---|---|---|
| `language` | Text | ISO 639-1 code (e.g. `"en"`, `"fr"`, `"ja"`) |
| `languageName` | Text | Full name (e.g. `"ENGLISH"`) |
| `reliable` | Boolean | `True` if detection is confident |
| `textBytes` | Integer | Bytes of text analyzed |
| `languages` | Collection | Top 3 candidates with `code`, `name`, `percent` |

**Example:**

```4d
$result:=CLD2("This is a test in English")
// $result.language = "en"
// $result.languageName = "ENGLISH"
// $result.reliable = True

$result:=CLD2("これは日本語のテストです")
// $result.language = "ja"
```

## Building from Source

```bash
git clone --recursive https://github.com/miyako/4d-plugin-CLD2.git
cd 4d-plugin-CLD2/CLD2
mkdir cmake-build && cd cmake-build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build .
```

## License

CLD2 is licensed under the [Apache License 2.0](https://github.com/CLD2Owners/cld2/blob/master/LICENSE).
