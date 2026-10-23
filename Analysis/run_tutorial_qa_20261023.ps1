$ErrorActionPreference = 'Stop'
$taskProject = Split-Path $PSScriptRoot -Parent
$taskQa = Join-Path $PSScriptRoot 'input\tutorial_20261023'
$taskManaged = Join-Path $taskProject 'Game\WIN\TidesOfNumenera_Data\Managed'
$taskDll = Join-Path $taskManaged 'Assembly-CSharp.dll'
$taskProbe = Join-Path $taskManaged 'TutorialLayoutProbe.dll'
$taskExpected = '677CB9884B3ADC18A65005D37A55784164821F484F970339CD15297105686664'
if (Get-Process -Name TidesOfNumenera -ErrorAction SilentlyContinue) { throw 'Game already running' }
if (Test-Path -LiteralPath $taskProbe) { throw 'Existing probe must not be overwritten' }
if ((Get-FileHash -LiteralPath $taskDll).Hash -ne $taskExpected) { throw 'Unexpected game assembly' }
if ((Get-FileHash -LiteralPath (Join-Path $taskQa 'Assembly-CSharp.original.dll')).Hash -ne $taskExpected) { throw 'Invalid backup' }
$taskGame = $null
$taskInstalled = $false
$taskStartedAt = Get-Date
$taskGamePath = (Get-Item -LiteralPath (Join-Path $taskProject 'Game\WIN\TidesOfNumenera.exe')).FullName
try {
    Copy-Item -LiteralPath (Join-Path $taskQa 'TutorialLayoutProbe.dll') -Destination $taskProbe
    $taskInstalled = $true
    Copy-Item -LiteralPath (Join-Path $taskQa 'Assembly-CSharp.probe.dll') -Destination $taskDll
    $taskGame = Start-Process -FilePath (Join-Path $taskProject 'Game\WIN\TidesOfNumenera.exe') -WorkingDirectory (Join-Path $taskProject 'Game\WIN') -WindowStyle Hidden -PassThru
    Write-Output ('Started owned QA process ' + $taskGame.Id)
    for ($taskTick = 0; $taskTick -lt 35; $taskTick++) {
        if (Test-Path -LiteralPath (Join-Path $taskQa 'done.txt')) { Start-Sleep -Seconds 2; break }
        if ($taskGame.HasExited) {
            # Steam may replace the initial process during its startup handshake.
            $taskReplacement = Get-Process -Name TidesOfNumenera -ErrorAction SilentlyContinue | Where-Object { $_.StartTime -ge $taskStartedAt } | Select-Object -First 1
            if ($taskReplacement) { $taskGame = $taskReplacement }
        }
        Start-Sleep -Seconds 2
    }
    if (-not $taskGame.HasExited) { Stop-Process -Id $taskGame.Id; $taskGame.WaitForExit() }
    if (-not (Test-Path -LiteralPath (Join-Path $taskQa 'done.txt'))) { throw 'Bounded QA did not complete; inspect local output log' }
    Get-Content -LiteralPath (Join-Path $taskQa 'metrics.txt')
} finally {
    if ($null -ne $taskGame -and -not $taskGame.HasExited) { Stop-Process -Id $taskGame.Id; $taskGame.WaitForExit() }
    Copy-Item -LiteralPath (Join-Path $taskQa 'Assembly-CSharp.original.dll') -Destination $taskDll
    if ($taskInstalled) {
        if ((Get-FileHash -LiteralPath $taskProbe).Hash -ne (Get-FileHash -LiteralPath (Join-Path $taskQa 'TutorialLayoutProbe.dll')).Hash) { throw 'Probe changed unexpectedly' }
        Remove-Item -LiteralPath $taskProbe
    }
    if ((Get-FileHash -LiteralPath $taskDll).Hash -ne $taskExpected) { throw 'Assembly restoration failed' }
    Write-Output 'Original managed assembly restored and temporary probe removed'
}
