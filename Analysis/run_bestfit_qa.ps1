$ErrorActionPreference='Stop'
$taskProject=Split-Path $PSScriptRoot -Parent
$taskQa=Join-Path $PSScriptRoot 'input\tutorial_bestfit_20261023'
$taskOriginal=Join-Path $PSScriptRoot 'input\tutorial_20261023\Assembly-CSharp.original.dll'
$taskGameRoot=(Get-Item -LiteralPath (Join-Path $taskProject 'Game')).Target
$taskExe=Join-Path $taskGameRoot 'WIN\TidesOfNumenera.exe'
$taskManaged=Join-Path $taskGameRoot 'WIN\TidesOfNumenera_Data\Managed'
$taskDll=Join-Path $taskManaged 'Assembly-CSharp.dll'
$taskProbe=Join-Path $taskManaged 'TutorialBestFitProbe.dll'
$taskExpected='677CB9884B3ADC18A65005D37A55784164821F484F970339CD15297105686664'
if(Get-Process -Name TidesOfNumenera -ErrorAction SilentlyContinue){throw 'Game already running'}
if(Test-Path -LiteralPath $taskProbe){throw 'Existing probe must not be overwritten'}
if(Test-Path -LiteralPath (Join-Path $taskQa 'metrics.txt')){throw 'Use a fresh QA output directory'}
if((Get-FileHash -LiteralPath $taskDll).Hash -ne $taskExpected -or (Get-FileHash -LiteralPath $taskOriginal).Hash -ne $taskExpected){throw 'Unexpected source/backup hash'}
$taskStarted=Get-Date
$taskInstalled=$false
try {
    Copy-Item -LiteralPath (Join-Path $taskQa 'TutorialBestFitProbe.dll') -Destination $taskProbe
    $taskInstalled=$true
    Copy-Item -LiteralPath (Join-Path $taskQa 'Assembly-CSharp.qa.dll') -Destination $taskDll
    Start-Process -FilePath $taskExe -WorkingDirectory (Split-Path $taskExe -Parent) -WindowStyle Hidden
    Write-Output 'Running bounded real-prefab comparison, including original English'
    for($taskTick=0;$taskTick -lt 75;$taskTick++) {
        if(Test-Path -LiteralPath (Join-Path $taskQa 'done.txt')){Start-Sleep -Seconds 2;break}
        Start-Sleep -Seconds 2
    }
    if(Test-Path -LiteralPath (Join-Path $taskQa 'metrics.txt')){Get-Content -LiteralPath (Join-Path $taskQa 'metrics.txt')}
    if(-not(Test-Path -LiteralPath (Join-Path $taskQa 'done.txt'))){throw 'QA did not complete within bound'}
} finally {
    Get-Process -Name TidesOfNumenera -ErrorAction SilentlyContinue | Where-Object {$_.StartTime -ge $taskStarted -and $_.Path -eq $taskExe} | ForEach-Object {Stop-Process -Id $_.Id -ErrorAction SilentlyContinue; $_.WaitForExit()}
    Copy-Item -LiteralPath $taskOriginal -Destination $taskDll
    if($taskInstalled) {
        if((Get-FileHash -LiteralPath $taskProbe).Hash -ne (Get-FileHash -LiteralPath (Join-Path $taskQa 'TutorialBestFitProbe.dll')).Hash){throw 'Probe hash changed'}
        Remove-Item -LiteralPath $taskProbe
    }
    if((Get-FileHash -LiteralPath $taskDll).Hash -ne $taskExpected){throw 'Restoration failed'}
    Copy-Item -LiteralPath (Join-Path $taskGameRoot 'WIN\TidesOfNumenera_Data\output_log.txt') -Destination (Join-Path $taskQa 'output_log.txt')
    Write-Output 'Original program restored; temporary probe removed'
}
