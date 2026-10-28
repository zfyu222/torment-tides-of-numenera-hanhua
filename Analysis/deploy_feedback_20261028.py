"""Build and install validated revision 11 text. No game launch or publication."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
WORK = PROJECT / 'repack/feedback_20261028'
PAYLOAD = WORK / 'localized/en'
REPORT = PROJECT / 'TranslateFiles/reports/deployment_feedback_20261028.json'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def validated():
    v = json.loads((PROJECT / 'TranslateFiles/reports/final_validation.json').read_text(encoding='utf-8'))
    candidate = json.loads((PROJECT / 'TranslateFiles/feedback_20261028/candidate_manifest.json').read_text(encoding='utf-8'))
    applied = json.loads((PROJECT / 'TranslateFiles/feedback_20261028/integration_applied.json').read_text(encoding='utf-8'))
    if v['status'] != 'passed' or v['revision'] != 11 or applied['status'] != 'integrated':
        raise ValueError('Missing validated formal revision 11')
    formal = PROJECT / (PROJECT.name + '_text_translated.csv')
    candidate_csv = PROJECT / 'TranslateFiles/feedback_20261028/torment-tides-of-numenera_text_translated_candidate.csv'
    if sha(formal) != v['translation_sha256'] or v['translation_sha256'] != applied['formal_translation_sha256']:
        raise ValueError('Formal translation changed')
    if sha(candidate_csv) != candidate['candidate_sha256'] or candidate['candidate_sha256'] != applied['candidate_sha256']:
        raise ValueError('Candidate translation changed')
    with formal.open(encoding='utf-8-sig', newline='') as a, candidate_csv.open(encoding='utf-8-sig', newline='') as b:
        if list(csv.reader(a)) != list(csv.reader(b)):
            raise ValueError('Formal CSV values differ from built candidate')
    v['candidate_sha256'] = candidate['candidate_sha256']
    return v


def build():
    repair_work = PROJECT / 'TranslateFiles/feedback_20261028'
    candidate = json.loads((repair_work / 'candidate_manifest.json').read_text(encoding='utf-8'))
    baseline = json.loads((repair_work / 'baseline.json').read_text(encoding='utf-8'))
    csv = repair_work / 'torment-tides-of-numenera_text_translated_candidate.csv'
    if candidate['status'] != 'incremental_candidate_validated' or sha(csv) != candidate['candidate_sha256']:
        raise ValueError('Missing validated candidate for offline build')
    if sha(PROJECT / baseline['source_file']) != baseline['source_sha256']:
        raise ValueError('Candidate source changed')
    if PAYLOAD.exists():
        raise ValueError('Existing locale payload retained; verify it rather than overwrite')
    original = WORK / 'original'
    original.mkdir(parents=True, exist_ok=False)
    archive = PROJECT / 'backups/localized_en_original_20260819_085840.zip'
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            destination = (original / info.filename).resolve()
            if not destination.is_relative_to(original.resolve()):
                raise ValueError('Invalid backup path')
        z.extractall(original)
    run = subprocess.run([sys.executable, str(PROJECT / 'repack_stringtables.py'),
        str(PROJECT / (PROJECT.name + '_text.csv')), str(csv),
        str(original / 'en'), str(PAYLOAD)], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if run.returncode:
        raise RuntimeError(run.stdout.decode(errors='replace') + run.stderr.decode(errors='replace'))
    files = sorted(p for p in PAYLOAD.rglob('*') if p.is_file())
    if len(files) != 2251 or len(list(PAYLOAD.rglob('*.stringtable'))) != 2250:
        raise ValueError('Incomplete locale output')
    manifest = dict(translation_sha256=candidate['candidate_sha256'], original_backup_sha256=sha(archive),
        status='offline_candidate_build_requires_formal_export_before_install',
        files={p.relative_to(PAYLOAD).as_posix(): sha(p) for p in files})
    (WORK / 'build_binding.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return {'status': 'locale_built', 'files': len(files)}


def install():
    v = validated()
    binding = json.loads((WORK / 'build_binding.json').read_text(encoding='utf-8'))
    if binding['translation_sha256'] != v['candidate_sha256']:
        raise ValueError('Locale bound to different translation')
    check = subprocess.run(['powershell', '-NoProfile', '-Command',
        'if (Get-Process -Name TidesOfNumenera -ErrorAction SilentlyContinue) { exit 3 }'],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if check.returncode:
        raise ValueError('Game is running; stop before installation')
    game = (PROJECT / 'Game').resolve()
    target = (game / 'WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en').resolve()
    if not target.is_relative_to(game):
        raise ValueError('Invalid locale target')
    old = json.loads((PROJECT / 'TranslateFiles/reports/deployment_feedback_20261026.json').read_text(encoding='utf-8'))
    changed = []
    for rel, digest in binding['files'].items():
        destination = (target / rel).resolve()
        if not destination.is_relative_to(target):
            raise ValueError('Invalid locale path')
        if sha(PAYLOAD / rel) != digest:
            raise ValueError('Payload changed: ' + rel)
        current = sha(destination)
        if current != old['file_sha256'][rel]:
            raise ValueError('Installed baseline changed: ' + rel)
        if current != digest:
            changed.append(rel)
    backup = PROJECT / ('backups/localized_en_before_feedback_20261028_' + v['translation_sha256'][:12] + '.zip')
    with zipfile.ZipFile(backup, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for rel in changed:
            z.write(target / rel, 'en/' + rel)
    with zipfile.ZipFile(backup) as z:
        for rel in changed:
            if hashlib.sha256(z.read('en/' + rel)).hexdigest() != old['file_sha256'][rel]:
                raise ValueError('Backup digest mismatch')
    try:
        for rel in changed:
            shutil.copy2(PAYLOAD / rel, target / rel)
        for rel, digest in binding['files'].items():
            if sha(target / rel) != digest:
                raise ValueError('Installed digest mismatch: ' + rel)
    except Exception:
        with zipfile.ZipFile(backup) as z:
            for rel in changed:
                (target / rel).write_bytes(z.read('en/' + rel))
        raise
    report = dict(status='deployed_files_verified', translation_sha256=v['translation_sha256'],
        built_from_candidate_sha256=v['candidate_sha256'], formal_csv_values_equal_built_candidate=True,
        changed_files=len(changed), verified_files=len(binding['files']), backup=str(backup),
        payload_directory=str(PAYLOAD), game_locale_directory=str(target), file_sha256=binding['files'],
        game_started=False, in_game_validation='pending_user_test', published=False)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {k: report[k] for k in ('status', 'changed_files', 'verified_files', 'in_game_validation')}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['build', 'install'])
    print(json.dumps(build() if p.parse_args().command == 'build' else install(), ensure_ascii=True))
