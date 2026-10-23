"""Install/restore the verified, version-bound tutorial-only managed patch."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ORIGINAL='677cb9884b3adc18a65005d37a55784164821f484f970339cd15297105686664'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(action):
    p=Path(__file__).resolve().parents[1]
    game=(p/'Game').resolve()
    target=(game/'WIN/TidesOfNumenera_Data/Managed/Assembly-CSharp.dll').resolve()
    if not target.is_relative_to(game):
        raise ValueError('Unexpected assembly path')
    check=subprocess.run(['powershell','-NoProfile','-Command',
        'if (Get-Process -Name TidesOfNumenera -ErrorAction SilentlyContinue) { exit 3 }'],
        capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if check.returncode:
        raise ValueError('Save and exit the game before changing the assembly')
    report_path=p/'TranslateFiles/reports/tutorial_bestfit_patch_20261023.json'
    report=json.loads(report_path.read_text(encoding='utf-8'))
    output=p/'repack/tutorial_bestfit_20261023/WIN/TidesOfNumenera_Data/Managed/Assembly-CSharp.dll'
    backup=p/'backups/tutorial_bestfit_20261023/Assembly-CSharp.dll'
    if action=='install':
        if sha(target)!=ORIGINAL or sha(output)!=report['patched_sha256']:
            raise ValueError('Unsupported or changed input/payload')
        if report['runtime_comparison']!='passed_real_prefab_at_1920x1080':
            raise ValueError('Runtime comparison not approved')
        validation=json.loads((p/'TranslateFiles/reports/final_validation.json').read_text(encoding='utf-8'))
        if sha(p/'torment-tides-of-numenera_text_translated.csv')!=validation['translation_sha256']:
            raise ValueError('Formal translation changed')
        if (target.parent/'TutorialBestFitProbe.dll').exists():
            raise ValueError('Temporary QA probe still installed')
        backup.parent.mkdir(parents=True,exist_ok=True)
        with backup.open('xb') as f:
            f.write(target.read_bytes())
        if sha(backup)!=ORIGINAL:
            raise ValueError('Backup verification failed')
        try:
            shutil.copy2(output,target)
            if sha(target)!=report['patched_sha256']:
                raise ValueError('Installed checksum mismatch')
        except Exception:
            shutil.copy2(backup,target)
            raise
        report.update(status='installed_verified',installed=str(target),backup=str(backup))
    else:
        if sha(target)!=report['patched_sha256'] or sha(backup)!=ORIGINAL:
            raise ValueError('Unexpected current assembly or backup; refusing restore')
        shutil.copy2(backup,target)
        if sha(target)!=ORIGINAL:
            raise ValueError('Restore checksum mismatch')
        report['status']='restored_original'
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(report['status'])


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('install','restore'))
    main(parser.parse_args().action)
