"""Publish only the locally verified ZIP; preserve all earlier GitHub releases."""
import hashlib
import json
from pathlib import Path
import subprocess

P = Path(__file__).resolve().parents[1]
REPO = 'zfyu222/torment-tides-of-numenera-hanhua'


def gh(*args):
    return subprocess.check_output(['gh', *args], cwd=P, text=True, encoding='utf-8')


def main():
    report = json.loads((P/'TranslateFiles/reports/release_v1.5_preparation.json').read_text(encoding='utf-8'))
    assert report['status'] == 'package_verified_pending_publication'
    archive = P/'Dispatch'/report['archive']
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == report['sha256']
    head = subprocess.check_output(['git','rev-parse','HEAD'], cwd=P, text=True).strip()
    assert subprocess.check_output(['git','rev-parse','origin/main'],cwd=P,text=True).strip() == head
    title = '《Torment: Tides of Numenera》子非鱼AI汉化补丁 v1.5'
    # Drafts need not have a live tag yet; find by tag_name in the authenticated
    # list rather than the published-tag endpoint. Resume only this exact draft.
    drafts = [r for r in json.loads(gh('api','repos/'+REPO+'/releases')) if r['tag_name'] == 'v1.5']
    if not drafts:
        gh('release','create','v1.5', str(archive)+'#'+archive.name,
            '--repo',REPO,'--target',head,'--title',title,'--notes-file',str(P/'Dispatch/v1.5_发布说明.md'),'--draft')
        drafts = [r for r in json.loads(gh('api','repos/'+REPO+'/releases')) if r['tag_name'] == 'v1.5']
    assert len(drafts) == 1
    data = drafts[0]
    assert data['draft'] and len(data['assets']) == 1 and data['assets'][0]['size'] == report['size']
    assert data['target_commitish'] == head
    gh('release','edit','v1.5','--repo',REPO,'--draft=false','--latest')
    print('https://github.com/'+REPO+'/releases/tag/v1.5')


if __name__ == '__main__':
    main()
