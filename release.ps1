<#
  Cut a Subsync release in one shot: bump __version__ in subsync.py -> commit + tag + push ->
  create the GitHub release with two assets:
    * subsync.py   -- the one file (run: python subsync.py)
    * Subsync.zip  -- py + Subsync.cmd + subsync.ico, so end users can just double-click

  Commit your actual changes first (this only commits the version bump), then run:
    powershell -ExecutionPolicy Bypass -File .\release.ps1            # bump patch (1.0.0 -> 1.0.1)
    powershell -ExecutionPolicy Bypass -File .\release.ps1 1.2.0      # explicit version
    powershell -ExecutionPolicy Bypass -File .\release.ps1 1.0.0      # re-release current (no bump)

  Needs: gh (authenticated) and a clean working tree.
#>
param([string]$Version)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# 1. Require a clean tree so the tag captures your committed work (not half-finished edits).
if (git status --porcelain) { throw "Working tree not clean - commit or stash your changes first, then re-run." }

# 2. Find the current version in subsync.py and decide the new one.
$py = [System.IO.File]::ReadAllText("$PSScriptRoot\subsync.py")
if ($py -notmatch '__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"') { throw "Couldn't find __version__ in subsync.py" }
if ($Version) {
    if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version must look like X.Y.Z" }
    $ver = $Version
} else {
    $ver = "{0}.{1}.{2}" -f $Matches[1], $Matches[2], ([int]$Matches[3] + 1)
}

# 3. Stamp the version AND the build timestamp into subsync.py (UTF-8, no BOM) so a
#    downloaded copy -- which has no .git to derive them from -- still shows both. The
#    fresh timestamp always changes the file, so the release commit is never empty.
$stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm")
$py = [regex]::Replace($py, '__version__\s*=\s*"\d+\.\d+\.\d+"', "__version__ = `"$ver`"")
$py = [regex]::Replace($py, '__build__\s*=\s*"[^"]*"', "__build__ = `"$stamp`"")
[System.IO.File]::WriteAllText("$PSScriptRoot\subsync.py", $py)
if (git status --porcelain -- subsync.py) {
    git add subsync.py
    git commit --quiet -m "Release v$ver ($stamp)"
    git push --quiet origin main
}

# 4. Tag and push the tag.
git tag "v$ver"
git push --quiet origin "v$ver"

# 5. Freeze the standalone .exe (no Python needed on the target). build.ps1 stats the
#    exe's own mtime for its build timestamp, so it's stamped correctly by this run.
powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\build.ps1"
$exe = "$PSScriptRoot\dist\Subsync.exe"
if (-not (Test-Path $exe)) { throw "build.ps1 did not produce dist\Subsync.exe" }

# 6. Bundle the double-click experience (launcher + icon) alongside the one file.
$zip = "$PSScriptRoot\Subsync.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path subsync.py, Subsync.cmd, subsync.ico, README.md, LICENSE -DestinationPath $zip

# 7. Create the GitHub release with all three assets (exe / zip / one file).
$notes = @"
**Subsync v$ver** - a single-file, dependency-free ``.srt`` -> keystroke player that drives a lagging synced-lyric display back into time by hand.

### Run it (Windows)
- **Easiest (no Python):** download **Subsync.exe** below and double-click it.
- **Double-click the script:** download **Subsync.zip**, extract, and run **Subsync.cmd** (needs Python 3.8+).
- **One file:** download **subsync.py** and run  ``python subsync.py``  (then Load SRT, or drag an ``.srt`` on).

Full how-to + screenshots: https://github.com/RelentlessOldMan/Subsync#readme
"@
gh release create "v$ver" $exe subsync.py $zip --title "Subsync v$ver" --notes $notes

Remove-Item $zip -Force   # asset is uploaded; don't leave it in the working tree
Write-Host "`nReleased v$ver -> https://github.com/RelentlessOldMan/Subsync/releases/tag/v$ver"
