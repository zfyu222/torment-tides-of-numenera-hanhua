"""Deploy only this validated locale payload, backing up every changed file."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    project = Path(__file__).resolve().parents[1]
    work = project / 'repack/user_terms_20261023'
    payload = work / 'localized/en'
    game = (project / 'Game').resolve()
    target = (game / 'WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en').resolve()
    if not target.is_dir() or not target.is_relative_to(game):
        raise ValueError('Unexpected game locale target')
    validation = json.loads((project / 'TranslateFiles/reports/final_validation.json').read_text(encoding='utf-8'))
    csv_path = project / 'torment-tides-of-numenera_text_translated.csv'
    if validation['status'] != 'passed' or sha(csv_path) != validation['translation_sha256']:
        raise ValueError('Formal translation is not the validated export')
    check = subprocess.run(['powershell', '-NoProfile', '-Command',
        'if (Get-Process -Name TidesOfNumenera -ErrorAction SilentlyContinue) { exit 3 }'],
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), capture_output=True)
    if check.returncode:
        raise ValueError('Close the game before deploying the locale')
    assembly = game / 'WIN/TidesOfNumenera_Data/Managed/Assembly-CSharp.dll'
    expected_assembly = 'fdc889090036407c7625cb847e2ebc9827cd6bbe47ae6e50ac2461cf00056b88'
    if sha(assembly) != expected_assembly:
        raise ValueError('Unexpected installed tutorial assembly')
    files = sorted(p for p in payload.rglob('*') if p.is_file())
    if len(files) != 2251 or len(list(payload.rglob('*.stringtable'))) != 2250:
        raise ValueError('Incomplete locale payload')
    changed, added, hashes = [], [], {}
    for source in files:
        rel = source.relative_to(payload)
        destination = target / rel
        if not destination.resolve().is_relative_to(target):
            raise ValueError('Locale path leaves target')
        hashes[rel.as_posix()] = sha(source)
        if not destination.exists():
            added.append(rel)
        elif sha(destination) != hashes[rel.as_posix()]:
            changed.append(rel)
    backup = project / ('backups/localized_en_before_user_terms_' + validation['translation_sha256'][:12] + '.zip')
    if changed:
        with zipfile.ZipFile(backup, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for rel in changed:
                archive.write(target / rel, 'en/' + rel.as_posix())
        with zipfile.ZipFile(backup) as archive:
            if archive.testzip() is not None:
                raise ValueError('Backup archive verification failed')
    for rel in changed + added:
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(payload / rel, destination)
    for rel, expected in hashes.items():
        if sha(target / rel) != expected:
            raise ValueError('Installed file differs: ' + rel)
    if sha(assembly) != expected_assembly:
        raise ValueError('Tutorial assembly changed during locale deployment')
    report = {'preserved_tutorial_assembly_sha256': expected_assembly, 'status': 'deployed_files_verified', 'translation_sha256': validation['translation_sha256'],
              'payload_directory': str(payload), 'game_locale_directory': str(target),
              'verified_files': len(files), 'changed_files': len(changed),
              'added_files': [rel.as_posix() for rel in added],
              'backup': str(backup) if changed else None, 'file_sha256': hashes,
              'in_game_validation': 'pending; file verification is not visual verification'}
    out = project / 'TranslateFiles/reports/deployment_user_terms_20261023.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'verified_files', 'changed_files', 'backup', 'in_game_validation')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
