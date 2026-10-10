# Create a per-user desktop button for the existing verified startup flow.
# No elevation, autorun, service configuration or credentials are installed.
param([string]$DesktopPath = '')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local_runtime.ps1')
$root = Get-ResearchRoot
$launcher = Join-Path $root 'start_researchos.cmd'
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw 'ResearchOS launcher is missing.' }
if ([string]::IsNullOrWhiteSpace($DesktopPath)) {
    $DesktopPath = [Environment]::GetFolderPath('Desktop')
}
if (-not [IO.Path]::IsPathRooted($DesktopPath) -or -not (Test-Path -LiteralPath $DesktopPath -PathType Container)) {
    throw 'Desktop directory must be an existing absolute path.'
}
$desktop = (Resolve-Path -LiteralPath $DesktopPath).Path
# Construct the Unicode name without relying on PowerShell 5 source encoding.
$name = ([string][char]0x542F) + [char]0x52A8 + ' ResearchOS.lnk'
$shortcutPath = Join-Path $desktop $name
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if ((Test-Path -LiteralPath $shortcutPath) -and $shortcut.TargetPath -ine $launcher) {
    throw 'A different desktop shortcut already uses this name; it was not overwritten.'
}
$iconDir = Join-Path $root 'data/runtime/desktop'
New-Item -ItemType Directory -Path $iconDir -Force | Out-Null
$iconPath = Join-Path $iconDir 'researchos.ico'
Add-Type -AssemblyName System.Drawing
$bitmap = [Drawing.Bitmap]::new(256, 256)
$graphics = [Drawing.Graphics]::FromImage($bitmap)
$font = [Drawing.Font]::new('Segoe UI', 150, [Drawing.FontStyle]::Bold, [Drawing.GraphicsUnit]::Pixel)
$brush = [Drawing.SolidBrush]::new([Drawing.Color]::White)
$format = [Drawing.StringFormat]::new()
$png = [IO.MemoryStream]::new()
$ico = [IO.MemoryStream]::new()
$writer = [IO.BinaryWriter]::new($ico)
try {
    $graphics.Clear([Drawing.Color]::FromArgb(232, 20, 0))
    $graphics.TextRenderingHint = [Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $format.Alignment = [Drawing.StringAlignment]::Center
    $format.LineAlignment = [Drawing.StringAlignment]::Center
    $graphics.DrawString('R', $font, $brush, [Drawing.RectangleF]::new(0, 0, 256, 256), $format)
    $bitmap.Save($png, [Drawing.Imaging.ImageFormat]::Png)
    $bytes = $png.ToArray()
    # A Windows PNG-backed ICO: one 256px image, 32-bit color, no temp copy.
    $writer.Write([uint16]0); $writer.Write([uint16]1); $writer.Write([uint16]1)
    $writer.Write([byte]0); $writer.Write([byte]0); $writer.Write([byte]0); $writer.Write([byte]0)
    $writer.Write([uint16]1); $writer.Write([uint16]32)
    $writer.Write([uint32]$bytes.Length); $writer.Write([uint32]22); $writer.Write($bytes)
    $writer.Flush()
    [IO.File]::WriteAllBytes($iconPath, $ico.ToArray())
} finally {
    $writer.Dispose(); $ico.Dispose(); $png.Dispose(); $format.Dispose()
    $brush.Dispose(); $font.Dispose(); $graphics.Dispose(); $bitmap.Dispose()
}
$shortcut.TargetPath = $launcher
$shortcut.Arguments = ''
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = $iconPath + ',0'
$shortcut.Description = 'Start ResearchOS, verify local services and open Chrome.'
$shortcut.WindowStyle = 1 # Show progress/errors; the actual service host stays hidden.
$shortcut.Save()
$readback = $shell.CreateShortcut($shortcutPath)
if ($readback.TargetPath -ine $launcher -or $readback.WorkingDirectory -ine $root -or
    $readback.Arguments -cne '' -or $readback.IconLocation -ine ($iconPath + ',0')) {
    throw 'Desktop launcher readback verification failed.'
}
Write-Host "Desktop launcher ready: $shortcutPath"
