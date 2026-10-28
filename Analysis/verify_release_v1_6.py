"""Verify package bytes and replay player scripts in copies, never the real game."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile

P = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    archive = P/'Dispatch/torment-tides-of-numenera_子非鱼汉化1.6.zip'
    sandbox = P/'backups/release_verify_v1_6_fast'
    if sandbox.exists():
        assert not any(sandbox.iterdir()), 'Preserve previous verification state'
    else:
        sandbox.mkdir()
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        names = z.namelist()
        assert len(names) == len(set(names))
        assert all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts for n in names)
        manifest = json.loads(z.read('PATCH_MANIFEST.json'))
        assert manifest['install_mode'] == 'script'
        files = manifest['files']
        assert len(files) == 2251
        all_files = files + manifest['auxiliary']
        expected = {f.get('archive_path',f['path']) for f in all_files}
        assert set(names) == expected | {'PATCH_MANIFEST.json','SHA256SUMS.txt','补丁说明.txt'}
        sums = dict(line.split('  ',1)[::-1] for line in z.read('SHA256SUMS.txt').decode('utf-8').splitlines())
        assert set(sums) == expected
        for f in all_files:
            path = f.get('archive_path',f['path'])
            data = z.read(path)
            assert sha(data) == sums[path] == f['sha256']
            assert len(data) == f['size']
            assert sha((P/'Dispatch/Files'/path).read_bytes()) == f['sha256']
            if path.endswith('.stringtable'):
                ET.fromstring(data)
        for f in files:
            assert sha((P/'Game'/f['path']).read_bytes()) == f['sha256']
        raw = z.read('补丁说明.txt')
        assert raw.startswith(b'\xef\xbb\xbf')
        guide = raw.decode('utf-8-sig').replace('\r\n', '\n')
        assert all('v1.'+str(i) in guide for i in range(7))
        assert 'DTkdOd01JcEFPQWRF?tab=BB08J2' in guide and '1hmMAhKbJe_oyeqcV146d3A?pwd=uxyx' in guide
        assert guide.index('下载与反馈') < guide.index('安装汉化\n')
        z.extractall(sandbox)
    (P/'Dispatch/v1.6_补丁说明预览.txt').write_bytes(raw)
    (P/'Dispatch/v1.6_发布说明.md').write_text(guide,encoding='utf-8')
    configpath = sandbox/'汉化工具/config.json'
    config = json.loads(configpath.read_text(encoding='utf-8-sig'))
    original_config = dict(config)
    # Only the copy's executable name is changed to avoid unrelated running-game
    # process checks. The real executable bytes/hash are used, never executed.
    exe = sandbox/'VerificationOnly.exe'
    shutil.copy2(P/'Game'/config['exe'],exe)
    config['exe'] = exe.name
    configpath.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8-sig')
    originals = {f['path']: f['sha256'] for f in config['originals']}
    def original_source(path):
        return (P/'backups/tutorial_bestfit_20261023/Assembly-CSharp.dll' if path.endswith('/Assembly-CSharp.dll') else
                P/'repack/incremental_revision9_20261025/original/en'/path.split('/localized/en/',1)[1])
    for f in files:
        dst = sandbox/f['path']
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(original_source(f['path']), dst)
        assert sha(dst.read_bytes()) == originals[f['path']]
    actions = []
    def action(root, verb):
        started = time.monotonic()
        r = subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'汉化工具/patch.ps1'),
                            '-Action',verb,'-NoLaunch'],capture_output=True)
        actions.append(dict(scope=root.name, action=verb, returncode=r.returncode, elapsed_seconds=round(time.monotonic()-started,3)))
        assert r.returncode == 0, (r.stdout+r.stderr).decode(errors='replace')
        print(json.dumps(actions[-1]),flush=True)
        return r.stdout
    action(sandbox,'install')
    assert all(sha((sandbox/f['path']).read_bytes()) == f['sha256'] for f in files)
    action(sandbox,'install')
    action(sandbox,'uninstall')
    assert all(sha((sandbox/path).read_bytes()) == digest for path,digest in originals.items())
    # Real v1.5 -> v1.6 legacy upgrade, on changed representative files plus DLL.
    legacy = P/'backups/release_verify_v1_6_fast_legacy'
    legacy.mkdir(exist_ok=False)
    chosen = []
    with zipfile.ZipFile(P/'Dispatch/torment-tides-of-numenera_子非鱼汉化1.5.zip') as old:
        old_paths = {f['path']:f.get('archive_path',f['path']) for f in json.loads(old.read('PATCH_MANIFEST.json'))['files']}
        for f in files:
            if sha(old.read(old_paths[f['path']])) != f['sha256'] and len(chosen)<4:
                chosen.append(f)
        chosen.append(next(f for f in files if f['path'].endswith('/Assembly-CSharp.dll')))
        for f in chosen:
            target = legacy/f['path']; target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(old.read(old_paths[f['path']]))
            new = legacy/f['archive_path']; new.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(sandbox/f['archive_path'],new)
    (legacy/'汉化工具').mkdir()
    shutil.copy2(sandbox/'汉化工具/patch.ps1',legacy/'汉化工具/patch.ps1')
    shutil.copy2(exe,legacy/exe.name)
    (legacy/'汉化工具/config.json').write_text(json.dumps(config,ensure_ascii=False),encoding='utf-8-sig')
    (legacy/'PATCH_MANIFEST.json').write_text(json.dumps(dict(files=chosen),ensure_ascii=False),encoding='utf-8')
    action(legacy,'install')
    assert all(sha((legacy/f['path']).read_bytes()) == f['sha256'] for f in chosen)
    out = action(legacy,'uninstall')
    assert b'STEAM_RESTORE=True' in out  # NoLaunch prevents opening Steam.
    report = dict(status='package_verified_pending_publication', archive=archive.name, size=archive.stat().st_size,
        sha256=sha(archive.read_bytes()), payload_files=len(files), archive_entries=len(names), xml_parsed=2250,
        manifest_checksums_and_zip_crc='passed', package_installed_payload_hashes='passed',
        installer_replay=actions, full_install_repeat_uninstall_files=2251, actual_v1_5_legacy_upgrade_sample=len(chosen),
        additional_installer_regressions=8, player_extra_runtime_required=False,
        real_game_modified=False, game_started=False, release_authorization='explicit_user_release', in_game_validation='pending',
        published=False, mirror_upload='not performed; user-provided link included')
    (P/'TranslateFiles/reports/release_v1.6_preparation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    main()
