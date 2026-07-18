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
# --onefile   : single portable .exe
# --windowed  : no console window (like pythonw)
# --icon      : Explorer file icon on the exe itself
# --add-data  : bundle the .ico so _set_app_icon can find it under sys._MEIPASS at runtime
python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name Subsync --icon subsync.ico --add-data "subsync.ico;." subsync.py

Write-Host ""
$exe = Join-Path $PSScriptRoot "dist\Subsync.exe"
if (Test-Path $exe) {
  $mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
  Write-Host "Done: $exe ($mb MB)" -ForegroundColor Green
} else {
  Write-Error "Build finished but dist\Subsync.exe is missing"
}
