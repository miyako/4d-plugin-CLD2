$ErrorActionPreference = 'Stop'
python -c "import os,sys; sys.path.insert(0,'.github/scripts'); import repository; repository.verify_checkout(os.environ['GITHUB_SHA'])"
if ($LASTEXITCODE -ne 0) { throw 'Windows source validation failed' }
python .github/scripts/native.py clean-windows
if ($LASTEXITCODE -ne 0) { throw 'Windows output cleanup failed' }
Push-Location CLD2
try {
    # Cleanup retains directories; the original fresh-build recipe is unchanged.
    try { $build = Get-Item -LiteralPath 'cmake-build' -Force -ErrorAction Stop }
    catch [System.Management.Automation.ItemNotFoundException] { $build = $null }
    if ($null -eq $build) { New-Item -ItemType Directory -Path 'cmake-build' | Out-Null }
    Set-Location cmake-build
    cmake .. -A x64
    if ($LASTEXITCODE -ne 0) { throw 'Windows CMake configure failed' }
    cmake --build . --config Release
    if ($LASTEXITCODE -ne 0) { throw 'Windows CMake build failed' }
} finally {
    Pop-Location
}
python .github/scripts/native.py windows
if ($LASTEXITCODE -ne 0) { throw 'Windows artifact validation failed' }
