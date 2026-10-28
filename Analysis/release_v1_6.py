"""Invoke the official packager in-process to avoid Windows argument length limits."""
import argparse
import contextlib
import importlib.util
import json
from pathlib import Path
import sys


def main(dry_run):
    p=Path(__file__).resolve().parents[1]
    reports=p/'TranslateFiles/reports'
    metadata=json.loads((reports/'release_v1.6_metadata.json').read_text(encoding='utf-8'))
    payload=json.loads((reports/'release_v1.6_payload.json').read_text(encoding='utf-8'))
    script=p.parents[1]/'.agents/skills/game-release-patch/scripts/create_release_patch.py'
    spec=importlib.util.spec_from_file_location('official_release_packager',script)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cli=[str(script)]
    for key,value in metadata.items():
        cli.extend(['--'+key.replace('_','-'),value])
    if dry_run:
        cli.append('--dry-run')
    for item in payload['files']:
        cli.extend(['--include',str(p/item['source'])+'='+item['path']])
    # All original checks remain inside module.main(), including release-check.
    previous=sys.argv
    try:
        sys.argv=cli
        if dry_run:
            with (reports/'release_v1.6_dryrun.txt').open('w',encoding='utf-8') as log, contextlib.redirect_stdout(log):
                result=module.main()
            print('Official dry run passed; payload entries:',len(payload['files']))
            return result
        return module.main()
    finally:
        sys.argv=previous


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    raise SystemExit(main(args.dry_run))
