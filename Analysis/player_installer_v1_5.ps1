param([ValidateSet('install','uninstall')][string]$Action,[switch]$NoLaunch)
$ErrorActionPreference='Stop'
try {
    $root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    function Within([string]$base,[string]$relative) {
        if ([IO.Path]::IsPathRooted($relative) -or $relative -match '(^|[/\\])\.\.([/\\]|$)|:') { throw '无效文件路径。' }
        $p=[IO.Path]::GetFullPath((Join-Path $base $relative))
        if (!$p.StartsWith($base.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) { throw '无效文件路径。' }
        return $p
    }
    function Digest($p) {
        if(Test-Path -LiteralPath $p -PathType Leaf) {
            $stream=[IO.File]::OpenRead($p);$algorithm=[Security.Cryptography.SHA256]::Create()
            try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
            finally { $stream.Dispose();$algorithm.Dispose() }
        };return $null
    }
    function SaveState($value) { $value|ConvertTo-Json -Depth 12|Set-Content -LiteralPath $statePath -Encoding UTF8 }
    function CopyChecked($source,$target,$hash) {
        $null=New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target)
        Copy-Item -LiteralPath $source -Destination $target -Force
        if ((Digest $target) -ne $hash) { throw '文件写入失败。' }
    }
    $config=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if ((Digest (Within $root $config.exe)) -ne $config.exe_sha256) { throw '请将补丁解压到受支持版本的游戏目录。' }
    if (@(Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($config.exe)) -ErrorAction SilentlyContinue).Count) { throw '请先退出游戏，再运行脚本。' }
    $stateDir=Within $root '.zfy-localization';$statePath=Within $stateDir 'state.json'
    $state=$null;if(Test-Path -LiteralPath $statePath) { $state=Get-Content -LiteralPath $statePath -Raw -Encoding UTF8|ConvertFrom-Json }
    $manifest=Get-Content -LiteralPath (Join-Path $root 'PATCH_MANIFEST.json') -Raw -Encoding UTF8|ConvertFrom-Json
    $legacyHashes=@{};foreach($known in $config.legacy) { $legacyHashes[($known.path+'|'+$known.sha256)]=$true }
    $originalPaths=@{};foreach($known in $config.originals) { $originalPaths[$known.path]=$true }
    if ($Action -eq 'install') {
        if($state -and $state.status -notin @('installed','uninstalled')) { throw '上次安装未完成，请先运行卸载汉化。' }
        # Complete source and current-state preflight before changing the game.
        foreach($file in $manifest.files) {
            if((Digest (Within $root $file.archive_path)) -ne $file.sha256) { throw '补丁文件不完整，请重新解压。' }
        }
        if($state -and $state.status -eq 'installed') {
            foreach($r in $state.records) { if((Digest (Within $root $r.path)) -ne $r.installed) { throw '安装文件已改变，请先运行卸载汉化。' } }
            if((@($state.records.path|Sort-Object) -join '|') -ne (@($manifest.files.path|Sort-Object) -join '|')) { throw '升级路径发生变化，请先运行卸载汉化。' }
        } else {
            $null=New-Item -ItemType Directory -Force -Path $stateDir
            $records=@()
            foreach($file in $manifest.files) {
                $target=Within $root $file.path;$prior=Digest $target;$legacy=$legacyHashes.ContainsKey($file.path+'|'+$prior)
                $original=$prior
                if($legacy) { $original=$null } elseif($prior) { CopyChecked $target (Within $stateDir ('original/'+$file.path)) $prior }
                $restoreSteam=$legacy -and $originalPaths.ContainsKey($file.path)
                $records+=[pscustomobject]@{path=$file.path;original=$original;installed=$prior;previous=$prior;restore_steam=$restoreSteam}
            }
            $state=@{status='installing';records=$records};SaveState $state
        }
        # Persist ALL write intentions before the first write. Uninstall accepts
        # either the previous/original or intended bytes for every path, so a
        # partial install remains recoverable without rewriting the full journal
        # once per payload file (quadratic work on large game patches).
        $recordByPath=@{};foreach($r in $state.records) { $recordByPath[$r.path]=$r }
        foreach($file in $manifest.files) {
            $r=$recordByPath[$file.path];$r.previous=$r.installed;$r.installed=$file.sha256
        }
        $state.status='installing';SaveState $state
        foreach($file in $manifest.files) {
            CopyChecked (Within $root $file.archive_path) (Within $root $file.path) $file.sha256
        }
        $state.status='installed';SaveState $state
        Write-Host '汉化安装完成，可以启动游戏。'
    } else {
        if(!$state -or $state.status -eq 'uninstalled') {
            # Legacy root-extraction packages have no installer state.
            $records=@();foreach($file in $manifest.files) {
                $prior=Digest (Within $root $file.path);if(!$prior) { continue }
                $knownMatch=$legacyHashes.ContainsKey($file.path+'|'+$prior)
                if(!$knownMatch) { continue }
                $records+=@{path=$file.path;original=$null;installed=$prior;restore_steam=$originalPaths.ContainsKey($file.path)}
            }
            $state=@{status='installed';records=$records}
        }
        foreach($r in $state.records) {
            $current=Digest (Within $root $r.path)
            if($current -and $current -ne $r.installed -and $current -ne $r.original -and $current -ne $r.previous) { throw '文件已被其他程序修改，暂未卸载。' }
            if($r.original -and (Digest (Within $stateDir ('original/'+$r.path))) -ne $r.original) { throw '还原文件不完整。' }
        }
        $steam=$false
        foreach($r in $state.records) {
            $target=Within $root $r.path
            if($r.original) { CopyChecked (Within $stateDir ('original/'+$r.path)) $target $r.original }
            elseif($r.restore_steam) { $steam=$true }
            elseif(Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }
        }
        $null=New-Item -ItemType Directory -Force -Path $stateDir
        $state.status='uninstalled';SaveState $state
        if($steam) {
            if(!$config.steam_app_id -or "$($config.steam_app_id)" -notmatch '^\d+$') { throw '缺少游戏恢复信息。' }
            if(!$NoLaunch) { Start-Process ('steam://validate/'+$config.steam_app_id) -WindowStyle Hidden }
            Write-Host '汉化已停用，Steam 正在恢复游戏文件。'
        } else { Write-Host '汉化卸载完成。' }
        if($NoLaunch) { Write-Output ('STEAM_RESTORE='+$steam) }
    }
} catch { Write-Host $_.Exception.Message;exit 1 }
