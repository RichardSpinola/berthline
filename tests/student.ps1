# Runs as a plain user: unpacks the zip on the Desktop, then tests it like a student would.
param([string]$Python)
$env:Path = "$Python;$env:Path"
# Start-Process keeps the caller's environment, so point it at this account.
$casa = 'C:\Users\student'
$env:USERPROFILE = $casa
$env:HOMEPATH = '\Users\student'
$env:USERNAME = 'student'
$env:APPDATA = "$casa\AppData\Roaming"
$env:LOCALAPPDATA = "$casa\AppData\Local"
$env:TEMP = "$casa\AppData\Local\Temp"
$env:TMP = $env:TEMP
whoami
whoami /groups | Select-String 'Administrators|High Mandatory|Medium Mandatory'
$mesa = Join-Path $casa 'Desktop'
New-Item -ItemType Directory -Force $mesa, $env:TEMP | Out-Null
tar -xf C:\check\berthline-windows.zip -C $mesa
$pacote = Join-Path $mesa 'berthline-windows'
Get-ChildItem $pacote | Select-Object -ExpandProperty Name

& "$Python\python.exe" C:\check\tests\hub_clicks.py $pacote C:\check\tests\out
$cliques = $LASTEXITCODE
Get-Process | Where-Object { $_.Path -like "$pacote*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

& "$pacote\node\node.exe" C:\check\tests\smoke.js $pacote
$smoke = $LASTEXITCODE
Write-Output "clicks=$cliques smoke=$smoke"
if ($cliques -ne 0 -or $smoke -ne 0) { exit 1 }
exit 0
