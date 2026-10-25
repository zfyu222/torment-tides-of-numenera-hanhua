"""Verify public latest release metadata and anonymously downloaded asset bytes."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request


def gh_json(*args):
    return json.loads(subprocess.check_output(['gh',*args],text=True,encoding='utf-8'))


def main():
    p=Path(__file__).resolve().parents[1];repo='zfyu222/torment-tides-of-numenera-hanhua'
    metadata=gh_json('api','repos/'+repo)
    release=gh_json('api','repos/'+repo+'/releases/tags/v1.4')
    latest=gh_json('api','repos/'+repo+'/releases/latest')
    if metadata['private'] or release['draft'] or release['prerelease'] or latest['tag_name']!='v1.4':
        raise ValueError('Release is not public latest stable')
    report_path=p/'TranslateFiles/reports/release_v1.4_preparation.json'
    report=json.loads(report_path.read_text(encoding='utf-8'))
    assets=[a for a in release['assets']if a['size']==report['size']and a['name'].endswith('.zip')]
    if len(assets)!=1: raise ValueError('Expected one matching ZIP asset')
    asset=assets[0]
    request=urllib.request.Request(asset['browser_download_url'],headers={'User-Agent':'Localization-release-verification'})
    with urllib.request.urlopen(request,timeout=60)as response:
        if response.status!=200: raise ValueError('Public download failed')
        data=response.read()
    digest=hashlib.sha256(data).hexdigest()
    if digest!=report['sha256']: raise ValueError('Published asset differs from local ZIP')
    folder=p/'backups/release_download_v1_4';folder.mkdir(exist_ok=False)
    (folder/asset['name']).write_bytes(data)
    report.update(status='published_and_download_verified',published=True,release_url=release['html_url'],
                  asset_name=asset['name'],asset_label=asset.get('label'),asset_download_url=asset['browser_download_url'],
                  downloaded_sha256=digest,latest_stable=True,repository_public=True)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k]for k in ['status','release_url','asset_name','sha256','downloaded_sha256','latest_stable']},ensure_ascii=True))


if __name__=='__main__':main()
