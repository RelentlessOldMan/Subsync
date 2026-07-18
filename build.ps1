# Build Subsync.exe -- a self-contained Windows app (no Python needed on the target).
# Regenerates the icon, then freezes subsync.py with PyInstaller into dist\Subsync.exe.
# Run this whenever you cut a release so the exe isn't a stale snapshot.
#
#   powershell -ExecutionPolicy Bypass -File build.ps1
#
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> Regenerating subsync.ico"
python make_icon.py

Write-Host "==> Freezing subsync.py -> dist\Subsync.exe (onefile, windowed)"
$exe = Join-Path $PSScriptRoot "dist\Subsync.exe"
# Delete any prior exe FIRST so a failed build can't leave a stale one that
# looks like success. (We also clear build\ ourselves instead of PyInstaller's
# --clean, which intermittently hits a lock removing build\Subsync\localpycs
# while Defender scans the freshly written exe.)
Remove-Item $exe -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $PSScriptRoot "build") -Recurse -Force -ErrorAction SilentlyContinue

# --onefile   : single portable .exe
# --windowed  : no console window (like pythonw)
# --icon      : Explorer file icon on the exe itself
# --add-data  : bundle the .ico so _set_app_icon can find it under sys._MEIPASS at runtime
python -m PyInstaller --noconfirm --onefile --windowed `
  --name Subsync --icon subsync.ico --add-data "subsync.ico;." subsync.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Write-Host ""
if (Test-Path $exe) {
  $mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
  Write-Host "Done: $exe ($mb MB)" -ForegroundColor Green
} else {
  Write-Error "Build finished but dist\Subsync.exe is missing"
}
