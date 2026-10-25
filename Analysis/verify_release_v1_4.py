"""Validate the v1.4 ZIP, staged payload, XML and extracted installation paths."""
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = Path(__file__).resolve().parents[1]
    archive = p / 'Dispatch/torment-tides-of-numenera_子非鱼汉化1.4.zip'
    stage = p / 'Dispatch/Files'
    target = p / 'backups/release_verify_v1_4'
    target.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        if z.testzip(): raise ValueError('Invalid ZIP CRC')
        names = z.namelist()
        if len(names) != len(set(names)): raise ValueError('Duplicate ZIP entry')
        for name in names:
            rel = PurePosixPath(name)
            if rel.is_absolute() or '..' in rel.parts or not (target / name).resolve().is_relative_to(target.resolve()):
                raise ValueError('Unsafe archive path')
        manifest = json.loads(z.read('PATCH_MANIFEST.json'))
        payload = {f['path']: f for f in manifest['files']}
        if len(payload) != 2251 or set(names) != set(payload) | {'PATCH_MANIFEST.json','SHA256SUMS.txt','补丁说明.txt'}:
            raise ValueError('Unexpected archive content')
        sums = dict(line.split('  ', 1)[::-1] for line in z.read('SHA256SUMS.txt').decode('utf-8').splitlines())
        if set(sums) != set(payload): raise ValueError('Checksum coverage mismatch')
        for name, record in payload.items():
            data = z.read(name)
            if digest(data) != record['sha256'] or sums[name] != record['sha256'] or len(data) != record['size']:
                raise ValueError('ZIP content hash mismatch')
            if digest((stage / name).read_bytes()) != record['sha256'] or digest((p / 'Game' / name).read_bytes()) != record['sha256']:
                raise ValueError('Staged or installed payload differs')
            if name.endswith('.stringtable'): ET.fromstring(data)
        raw = z.read('补丁说明.txt')
        if not raw.startswith(b'\xef\xbb\xbf'): raise ValueError('Guide has no BOM')
        guide = raw.decode('utf-8-sig')
        if not all('v'+v in guide for v in ['1.0','1.1','1.2','1.3','1.4']):
            raise ValueError('Historical changelog missing')
        if '订阅' not in guide or '旧版' not in guide: raise ValueError('Missing update instructions')
        z.extractall(target)
    for name, record in payload.items():
        if digest((target / name).read_bytes()) != record['sha256']: raise ValueError('Extraction mismatch')
    report = {'status':'package_verified_pending_publication','archive':archive.name,'size':archive.stat().st_size,
              'sha256':digest(archive.read_bytes()),'archive_entries':len(names),'payload_files':len(payload),
              'manifest_and_checksums':'passed','installed_and_staged_hashes':'passed','xml_files_parsed':2250,
              'historical_changelog':'v1.0 through v1.4 preserved', 'published':False,
              'in_game_scope':'startup/menu/options; dialogue/quest/tutorial not additionally retested',
              'user_confirmation':'没问题，直接发布'}
    (p/'TranslateFiles/reports/release_v1.4_preparation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (p/'Dispatch/v1.4_补丁说明预览.txt').write_bytes(raw)
    print(json.dumps(report,ensure_ascii=True))


if __name__ == '__main__': main()
