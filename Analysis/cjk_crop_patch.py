"""Version-bound offline build/test and reversible installation; never starts game."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
ANALYSIS = PROJECT / 'Analysis'
WORK = ANALYSIS / 'cjk_crop_20261028'
INPUT_HASH = 'fdc889090036407c7625cb847e2ebc9827cd6bbe47ae6e50ac2461cf00056b88'
CSC = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
TARGET_REL = Path('WIN/TidesOfNumenera_Data/Managed/Assembly-CSharp.dll')
PAYLOAD = PROJECT / 'repack/cjk_crop_20261028' / TARGET_REL
REPORT = PROJECT / 'TranslateFiles/reports/cjk_crop_patch_20261028.json'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(args, cwd):
    result = subprocess.run([str(x) for x in args], cwd=cwd, capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW)
    output = result.stdout.decode('utf-8', errors='replace') + result.stderr.decode('utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(output)
    return output.strip()


def target():
    game = (PROJECT / 'Game').resolve()
    path = (game / TARGET_REL).resolve()
    if not path.is_relative_to(game):
        raise ValueError('Unexpected game path')
    return path


def build():
    current = target()
    if sha(current) != INPUT_HASH:
        raise ValueError('Installed assembly differs from supported tutorial-patched version')
    WORK.mkdir(parents=True, exist_ok=True)
    shutil.copy2(current, WORK / 'input.dll')
    shutil.copy2(PROJECT.parents[1] / 'Tools/XUnity.AutoTranslator/libs/MonoMod/Mono.Cecil.dll', WORK / 'Mono.Cecil.dll')
    commands = [
        ['/target:library', '/out:cjk_crop_20261028\\helper.dll', 'CjkRichTextCrop.cs'],
        ['/r:cjk_crop_20261028\\Mono.Cecil.dll', '/out:cjk_crop_20261028\\PatchCjkCrop.exe', 'PatchCjkCrop.cs'],
        ['/r:cjk_crop_20261028\\Mono.Cecil.dll', '/out:cjk_crop_20261028\\VerifyCjkCrop.exe', 'VerifyCjkCrop.cs'],
    ]
    for args in commands:
        run([CSC, '/nologo', *args], ANALYSIS)
    run([WORK / 'PatchCjkCrop.exe', 'input.dll', 'helper.dll', 'output.dll', current.parent], WORK)
    with (PROJECT / (PROJECT.name + '_text_translated.csv')).open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    (WORK / 'item.txt').write_text(rows[63857][0], encoding='utf-8')
    verification = run([WORK / 'VerifyCjkCrop.exe', 'input.dll', 'output.dll', 'item.txt'], WORK)
    PAYLOAD.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(WORK / 'output.dll', PAYLOAD)
    report = dict(status='offline_verified_ready', original_sha256=INPUT_HASH, patched_sha256=sha(PAYLOAD),
        payload=str(PAYLOAD.relative_to(PROJECT)), verification=verification.splitlines(),
        source_sha256={name: sha(ANALYSIS / name) for name in
            ('CjkRichTextCrop.cs', 'PatchCjkCrop.cs', 'VerifyCjkCrop.cs', 'cjk_crop_patch.py')},
        evidence='Existing source-bound item translation plus synthetic valid prerequisite markup reproduces the cut-tag class of failure offline; not an in-game capture.',
        changed_existing_methods=['InXile.Strings.StringCropper.CropString'],
        new_runtime_dependencies=False, tutorial_patch_preserved=True, game_started=False,
        in_game_check='pending_user_test')
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report['status']


def install():
    check = subprocess.run(['powershell', '-NoProfile', '-Command',
        'if (Get-Process -Name TidesOfNumenera -ErrorAction SilentlyContinue) { exit 3 }'],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if check.returncode:
        raise ValueError('Game is running; stop before installation')
    report = json.loads(REPORT.read_text(encoding='utf-8'))
    current = target()
    if sha(current) == report['patched_sha256']:
        return 'already_installed_verified'
    if sha(current) != INPUT_HASH or sha(PAYLOAD) != report['patched_sha256']:
        raise ValueError('Input or payload checksum changed')
    if report['status'] != 'offline_verified_ready':
        raise ValueError('Missing offline verification')
    for name, digest in report['source_sha256'].items():
        if sha(ANALYSIS / name) != digest:
            raise ValueError('Build source changed: ' + name)
    backup = PROJECT / 'backups/cjk_crop_20261028/Assembly-CSharp.dll'
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        if sha(backup) != INPUT_HASH:
            raise ValueError('Unexpected prior backup')
    else:
        with backup.open('xb') as f:
            f.write(current.read_bytes())
    try:
        shutil.copy2(PAYLOAD, current)
        if sha(current) != report['patched_sha256']:
            raise ValueError('Installed checksum mismatch')
    except Exception:
        shutil.copy2(backup, current)
        raise
    report.update(status='installed_hash_verified_game_check_pending', installed=str(current), backup=str(backup))
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report['status']


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['build', 'install'])
    print(build() if p.parse_args().command == 'build' else install())
