"""Build and deploy the verified revision 12 language resources."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from deploy_feedback_20261028 import sha

PROJECT = Path(__file__).resolve().parents[1]
REPORTS = PROJECT / 'TranslateFiles/reports'
WORK = PROJECT / 'repack/polish_r12'
LOCALE = Path('WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en')
DISPLAY_FIX = Path('WIN/TidesOfNumenera_Data/Managed/Assembly-CSharp.dll')
PAYLOAD = WORK / 'localized/en'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def file_hashes(directory):
    return {file.relative_to(directory).as_posix(): sha(file)
            for file in sorted(directory.rglob('*')) if file.is_file()}


def validated_export():
    validation = read(REPORTS / 'final_validation.json')
    source = PROJECT / (PROJECT.name + '_text.csv')
    translation = PROJECT / (PROJECT.name + '_text_translated.csv')
    if (validation['status'] != 'passed' or validation['revision'] != 12
            or validation['records'] != 70163
            or sha(translation) != validation['translation_sha256']
            or sha(source) != validation['source_sha256']):
        raise ValueError('Revision 12 formal export and its matching validation are required')
    return validation, source, translation


def build():
    validation, source, translation = validated_export()
    binding_path = WORK / 'build_binding.json'
    if binding_path.exists():
        binding = read(binding_path)
        if (binding['translation_sha256'] != validation['translation_sha256']
                or binding['files'] != file_hashes(PAYLOAD)):
            raise ValueError('Previously built payload no longer matches the formal export')
        return binding
    original = PROJECT / 'repack/feedback_20261028/original/en'
    WORK.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='build-', dir=WORK) as scratch:
        stage = Path(scratch).resolve()
        if stage.parent != WORK.resolve():
            raise ValueError('Unexpected build staging location')
        result = subprocess.check_output([sys.executable, str(PROJECT / 'repack_stringtables.py'),
                                          str(source), str(translation), str(original), str(stage / 'en')],
                                         encoding='utf-8')
        details = json.loads(result)
        files = file_hashes(stage / 'en')
        if len(files) != 2251 or details['files'] != 2250 or details['verified_nonempty_fields'] != 89239:
            raise ValueError('Incomplete stringtable output')
        if sha(translation) != validation['translation_sha256']:
            raise ValueError('Formal translation changed during build')
        if PAYLOAD.exists():
            if file_hashes(PAYLOAD) != files:
                raise ValueError('Existing unbound payload differs from the rebuilt resources')
        else:
            PAYLOAD.parent.mkdir(parents=True, exist_ok=True)
            (stage / 'en').rename(PAYLOAD)
    binding = {'status': 'locale_built', 'translation_sha256': validation['translation_sha256'],
               'source_sha256': validation['source_sha256'], 'files': files,
               'tree_sha256': details['tree_sha256'], 'verified_nonempty_fields': 89239}
    write(binding_path, binding)
    return binding


def replace_bytes(path, data):
    with tempfile.NamedTemporaryFile(prefix='.shh-', dir=path.parent, delete=False) as handle:
        scratch = Path(handle.name)
        handle.write(data)
    try:
        scratch.replace(path)
    finally:
        scratch.unlink(missing_ok=True)


def install():
    binding = build()
    game = (PROJECT / 'Game').resolve(strict=True)
    target = (game / LOCALE).resolve(strict=True)
    baseline = read(PROJECT / 'Analysis/silver_occurrence_20261029.json')['file_sha256']
    files = binding['files']
    crop = read(REPORTS / 'cjk_crop_patch_20261028.json')
    if (not target.is_relative_to(game) or set(files) != set(baseline)
            or sha(game / DISPLAY_FIX) != crop['patched_sha256']
            or sha(PROJECT / 'repack/cjk_crop_20261028' / DISPLAY_FIX) != crop['patched_sha256']):
        raise ValueError('Local installation differs from the verified baseline')
    check = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                            'if (Get-Process -Name TidesOfNumenera -ErrorAction SilentlyContinue) { exit 3 }'],
                           capture_output=True)
    if check.returncode:
        raise ValueError('Close the game before installing the language resources')
    current = file_hashes(target)
    changed = [rel for rel, digest in files.items() if baseline[rel] != digest]
    if set(files) != set(current) or any(current[rel] not in (baseline[rel], files[rel]) for rel in files):
        raise ValueError('An installed language file differs from both known versions')
    destinations = {rel: (target / rel).resolve(strict=True) for rel in changed}
    if any(not destination.is_relative_to(target) for destination in destinations.values()):
        raise ValueError('A locale file redirects outside the game locale')
    backup = PROJECT / ('backups/localized_en_before_polish_r12_' + binding['translation_sha256'][:12] + '.zip')
    if not backup.exists():
        if current != baseline:
            raise ValueError('An earlier update is present without its verified rollback archive')
        with zipfile.ZipFile(backup, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for rel in changed:
                archive.write(target / rel, rel)
    with zipfile.ZipFile(backup) as archive:
        if (set(archive.namelist()) != set(changed)
                or any(hashlib.sha256(archive.read(rel)).hexdigest() != baseline[rel] for rel in changed)):
            raise ValueError('Rollback archive differs from the installed baseline')
        try:
            for rel, destination in destinations.items():
                if current[rel] != files[rel]:
                    replace_bytes(destination, (PAYLOAD / rel).read_bytes())
            if file_hashes(target) != files:
                raise ValueError('Installed language files differ from the release payload')
        except BaseException:
            for rel, destination in destinations.items():
                replace_bytes(destination, archive.read(rel))
            raise
    result = {**binding, 'status': 'deployed_files_verified', 'backup': str(backup),
              'changed_files': len(changed), 'payload_directory': str(PAYLOAD),
              'game_locale_directory': str(target), 'display_fix_sha256': crop['patched_sha256'],
              'in_game_validation': 'pending'}
    write(REPORTS / 'deployment_polish_r12.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('build', 'install'))
    arguments = parser.parse_args()
    report = build() if arguments.action == 'build' else install()
    print(json.dumps({key: value for key, value in report.items() if key != 'files'}, ensure_ascii=True))
