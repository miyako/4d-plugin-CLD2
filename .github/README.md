# CLD2 manual release workflow

## Independent source version and bundle metadata

`VERSION` is the canonical archive/release authority. The original source-only
edit in Bump commit `3a5cb56511898f61c37346639130a81559036ecd` changes this
file only. At migration intake
`7641e4506cc8199ef98d9ba9c6d80bb1be9084b0`, it contains `1.0.5`.

`CLD2/Info.plist` independently declares static
`CFBundleShortVersionString=1.0.0` and `CFBundleVersion=1.0.0`. Neither CMake
nor Bump links those fields to `VERSION`. The original released
`CLD2-1.0.5.zip` independently confirms packaged metadata `1.0.0`/`1.0.0`
(ZIP SHA256 `cf901d9ac0b9dfebe4c8887ef885952e623c5907837c0aa83e586a6fe5a16f11`,
extracted plist SHA256
`6f30e377d47221109f08c06e675f33066cb085db5c4cbd0279bf1d27cec21879`).
The migration does not normalize or rewrite either source.

Versions must be canonical `X.Y.Z`: no leading zeroes, suffixes, extra lines,
or unresolved substitutions. Source short version is required; build version
is optional. Duplicate, missing, unresolved, or invalid source metadata is
rejected before editing. XML and binary built plists must match the independent
selected source metadata, including presence/absence of the build key.

## Bump version

Manually select a **branch** and `patch` (default), `minor`, or `major`.
The workflow checks out immutable `github.sha`, recursively initializes the
selected dependencies, and edits **only `VERSION`**. Encoding, BOM, final line
ending, mode, native files, and plist bytes are preserved.

It creates one nonempty direct-child commit with explicit Actions bot author
and committer and the final literal trailer:

```
Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>
```

The mandatory committed executable `.github/hooks/pre-push` is raw-blob/mode
checked on every guard call, initially and immediately after the final branch
advertisement read. Missing, replaced, nonexecutable, symlink, and reparse hooks
are rejected. Two exact branch reads plus the real pre-push advertisement
guard require one update with the selected old SHA and literal new SHA/HEAD.
A moved, rewound, deleted, or already-updated branch fails; the push is
nonforce, with both `push.followTags=false` and `--no-follow-tags`.
Local commits are retained on late failures for inspection; there is no retry.
Bump never tags, publishes, builds, or dispatches another workflow.

## Build

Manually run **Build** on the desired source commit/ref. There are **no custom
inputs**, tag triggers, workflow links, or default-branch-only restrictions.
All checkouts, including the unrelated Build and Test workflow, select
`github.sha`. Scoped inherited `core.autocrlf=false` applies **before** checkout
and recursive dependency initialization; no host/global Git setting is changed.

Build uses one constant repository-wide cross-ref concurrency group,
`cld2-publication`, with cancellation disabled. GitHub does not promise FIFO
execution or preservation of all pending runs.

The original topology remains version → Windows x64 Release → universal macOS
Release, with the original CMake generators, dependencies, frameworks,
deployment target 10.13, output roots, and artifact paths:

* `CLD2/cmake-build`, Makefiles on macOS and the original Visual Studio generator
  on Windows; no Xcode, `Default`, `OBJROOT`, or output-root overrides.
* Windows artifact `windows-binaries` originates from
  `CLD2/CLD2-test/Plugins/CLD2/Contents/Windows64/CLD2.4DX`,
  downloaded as `winbuild/CLD2.4DX`.
* Final bundle: `CLD2/CLD2-test/Plugins/CLD2.bundle`, with exactly
  `Contents/Info.plist`, `Contents/MacOS/CLD2`,
  `Contents/Resources/manifest.json`, `Contents/Windows64/CLD2.4DX`,
  and `Contents/_CodeSignature/CodeResources`.

The only approved native CMake change replaces whole-bundle
`remove_directory` in macOS POST_BUILD with prevalidated exact generated-file
cleanup. The helper also cleans only the proven CMake output families before
building. It validates **all** targets, ancestors, descendants, types, access,
links/reparse points, and nested `.git` before the first deletion. Unexpected
leaves are refused even inside empty auxiliary directories. Source files and
the copied manifest bytes are retained. Cleanup never removes an output tree.
Each traversed directory below the legitimate checkout root is also probed
with `lstat` for its own `.git` marker, including ancestors outside the output
walk. Any marker type is rejected (file, directory, symlink, dangling/reparse
point, or special file). Only actual `ENOENT` absence is tolerated; permission,
I/O, and wrong-parent errors propagate before any deletion. The checkout
root's legitimate `.git` is exempt; initialized dependency Git markers are not
traversed because dependencies are not cleanup roots. Relative and absolute
native paths receive the same ancestor checks.

The source/index/HEAD and raw bytes are verified initially and again before
publication, including both `git ls-files -v` and `-f`. Both gitlinks,
`4D-Plugin-SDK` and `cld2-src`, must match selected/index/initialized HEAD and
every raw dependency blob. Staging, reverse staging, filters, hidden flags,
untracked and ignored source/config/output drift all fail closed.
Windows regular-file executable-mode differences are tolerated **only on
Windows and only when raw bytes match**; index modes and all links/reparse
points remain strict.

Initial checkouts must be globally clean. Final checks intentionally retain
tracked generated dirty outputs; they never reset files to pretend the build
was clean. Every packaged leaf must be a nonempty regular nonsymlink file.
Only the exact native leaves receive tracked-output exemptions. CMake
intermediate classification applies to untracked outputs only: selected or
indexed historical files in the CMake build root stay raw-byte immutable,
even with recognized object/compiler-ID names. Cleanup refuses those tracked
build inputs before deleting any file.
Resources equal their exact selected source; merged Windows bytes equal the
downloaded artifact. Unsigned and signed-final validation are distinct.
`lipo -archs` must include exact `arm64` and `x86_64` tokens; additional
architectures are allowed, as in the original policy.

Original Developer ID import, runtime codesign, ZIP/DMG construction, and
notary credential profile remain. Signing is strictly verified. **Both**
notary submissions must exit successfully and return strict JSON
`status=Accepted`; duplicate/nonfinite JSON is rejected. The DMG is stapled
and bundle signing strictly reverified before final publication validation.

## Create-only publication and recovery

`GH_TOKEN` must be explicitly nonempty. An authenticated repository API response
must carry a positive repository ID and independently match exact
`miyako/4d-plugin-CLD2`. This supports the workflow's GitHub App installation
token (`github.token`); it deliberately does not require the user-only `/user`
endpoint. Authentication401/403 errors are fatal. Before native
work and after all build/sign/notary/staple checks, publication enumerates every
release page **until empty**, including drafts, and checks matching/exact API
tag refs and the exact Git advertisement. Authentication, schema, malformed
JSON, network, and later-page errors are fatal; only a validated exact-ref
HTTP404 after authentication means absence.

If available, publication separately POSTs a new tag ref at selected SHA,
verifies API and Git tag identity, separately POSTs a new public release with
tag/name `vX.Y.Z`, target selected SHA, empty body, no generated notes, and
`draft=false`/`prerelease=false`. It requires a positive new ID not found in
prior pages. Only then are exact `CLD2-X.Y.Z.zip` and `.dmg` uploaded to that
new ID; sanitized names, positive IDs, integer sizes, and uploaded state are
checked. Booleans do not count as numeric IDs or sizes.

There is **no** reuse, clobber, PATCH, DELETE, rollback, retry, or combined
`gh release create` asset operation. On a race or partial failure, stop and
inspect the retained tag, release ID, assets, local commit, and generated
files. An operator must decide manual recovery; rerunning the occupied version
fails closed rather than replacing publication objects. Bump a new source
version and run Build separately if a new release is required.

## Offline validation

From the repository root, with Python 3, PyYAML, PowerShell at
`/usr/local/bin/pwsh`, and actionlint available:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tests/run_offline.py
/opt/homebrew/bin/actionlint .github/workflows/*.yml
```

The full runner rejects skips, concurrent full runs, and leftover fixtures.
All fixtures live under disposable `tests/.offline-*` paths and are removed.
Real Git/bare remotes, detached Bump CLI, advertisement races, hostile-global
recursive clone/line-ending oracles, and publication CLI use local-only data.
The same real recursive clone runs Windows-mode CLI positives and
raw/staged/reversed/index-mode/link/directory/reparse negatives for the root
and both cloned dependencies, initially and with retained final native output.
Restored positives retain those output bytes and the hostile fixture-global
configuration remains byte-for-byte unchanged throughout.
Native/credential commands execute only closed-PATH oracles, including real
Bash and PowerShell control flow; no real CMake/compiler/4D/sign/notary/API
publication runs. Windows mode/reparse semantics are additionally modeled
in actual CLI subprocesses; these offline cases do not replace hosted Windows
or macOS native execution. Original recipe fixtures are pinned to intake;
live version expectations remain valid after a genuine Bump.

Implementation adapts verified libarchive helpers at
`9547d09522fc422ddd754fb088165b3d1d1d3073`,
stomp Windows/reparse/scoped-checkout patterns at
`ab9f5e51dba5b8b6ec1a1b70e191082fcb73fb41`, and the shell per-call hook
integrity pattern at `ee33f21111d9a042101ccc11d68672a7a0067e9c`.
CLD2 has no VERSION-linked plist template, libarchive build,
APR, jsoncpp, libtool, runtime-dylib, or Xcode exceptions.
