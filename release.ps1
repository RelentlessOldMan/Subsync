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

# 3. Write the version back (UTF-8, no BOM) and commit ONLY if it actually changed --
#    so re-releasing the current version (e.g. the first v1.0.0) doesn't fail on an empty commit.
$py = [regex]::Replace($py, '__version__\s*=\s*"\d+\.\d+\.\d+"', "__version__ = `"$ver`"")
[System.IO.File]::WriteAllText("$PSScriptRoot\subsync.py", $py)
if (git status --porcelain -- subsync.py) {
    git add subsync.py
    git commit --quiet -m "Release v$ver"
    git push --quiet origin main
}

# 4. Tag and push the tag.
git tag "v$ver"
git push --quiet origin "v$ver"

# 5. Bundle the double-click experience (launcher + icon) alongside the one file.
$zip = "$PSScriptRoot\Subsync.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path subsync.py, Subsync.cmd, subsync.ico, README.md, LICENSE -DestinationPath $zip

# 6. Create the GitHub release with both assets.
$notes = @"
**Subsync v$ver** - a single-file, dependency-free ``.srt`` -> keystroke player that drives a lagging synced-lyric display back into time by hand.

### Run it (Windows, needs Python 3.8+)
- **Easiest:** download **Subsync.zip** below, extract it, and double-click **Subsync.cmd**.
- **One file:** download **subsync.py** and run  ``python subsync.py``  (then Load SRT, or drag an ``.srt`` on).

Full how-to + screenshots: https://github.com/RelentlessOldMan/Subsync#readme
"@
gh release create "v$ver" subsync.py $zip --title "Subsync v$ver" --notes $notes

Remove-Item $zip -Force   # asset is uploaded; don't leave it in the working tree
Write-Host "`nReleased v$ver -> https://github.com/RelentlessOldMan/Subsync/releases/tag/v$ver"
