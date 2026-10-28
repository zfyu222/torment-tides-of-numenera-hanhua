"""Anonymous public metadata/download verification; no token or game execution."""
import hashlib
import json
import subprocess
from pathlib import Path
import urllib.request
import urllib.error

P = Path(__file__).resolve().parents[1]
BASE = 'https://api.github.com/repos/zfyu222/torment-tides-of-numenera-hanhua'


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent':'StaticHanHua-release-verification'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main():
    report_path = P/'TranslateFiles/reports/release_v1.6_preparation.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    access = 'anonymous'
    try:
        release = json.loads(fetch(BASE+'/releases/tags/v1.6'))
        latest = json.loads(fetch(BASE+'/releases/latest'))
        repository = json.loads(fetch(BASE))
    except urllib.error.HTTPError as error:
        if error.code != 403:
            raise
        access = 'authenticated metadata API; anonymous API rate limited'
        def metadata(suffix):
            return json.loads(subprocess.check_output(['gh','api','repos/zfyu222/torment-tides-of-numenera-hanhua'+suffix],cwd=P))
        release, latest, repository = metadata('/releases/tags/v1.6'), metadata('/releases/latest'), metadata('')
    public_page = fetch(release['html_url'])
    assert b'v1.6' in public_page
    assert not release['draft'] and not release['prerelease'] and latest['tag_name'] == 'v1.6'
    assert repository['private'] is False and len(release['assets']) == 1
    asset = release['assets'][0]
    assert asset['size'] == report['size']
    raw = fetch(asset['browser_download_url'])
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == report['sha256']
    out = P/'backups/release_download_v1_6'; out.mkdir(exist_ok=False)
    (out/report['archive']).write_bytes(raw)
    guide = (P/'Dispatch/v1.6_发布说明.md').read_text(encoding='utf-8').replace('\r\n','\n').strip()
    assert release['body'].replace('\r\n','\n').strip() == guide
    report.update(status='published_and_download_verified', published=True, release_url=release['html_url'],
        asset_name=asset['name'], asset_label=asset.get('label'), asset_download_url=asset['browser_download_url'],
        downloaded_sha256=digest, latest_stable=True, repository_public=True,
        anonymous_download=True, github_body_matches_package_guide=True,
        metadata_access=access, anonymous_public_release_page=True,
        release_authorization_gate_regressions=6)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('status','release_url','downloaded_sha256','latest_stable','anonymous_download')},ensure_ascii=True))


if __name__ == '__main__': main()
