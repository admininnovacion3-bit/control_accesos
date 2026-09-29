# Ejecutar una sola vez. Crea un acceso directo de ControlAsist en el escritorio.
$desktopPath = [Environment]::GetFolderPath('Desktop')
$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$shortcutPath = Join-Path $desktopPath 'ControlAsist.lnk'

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $projectPath 'Abrir_ControlAsist.cmd'
$shortcut.WorkingDirectory = $projectPath
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,14"
$shortcut.Description = 'Iniciar ControlAsist local'
$shortcut.Save()

Write-Host "Acceso directo creado: $shortcutPath"
