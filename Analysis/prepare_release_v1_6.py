"""Bind current revision11 payload and explicit release authorization, without runtime claims."""
import copy
import json
from pathlib import Path
import zipfile
from prepare_release_v1_5 import P, Workflow, sha, write


def main():
    reports = P / 'TranslateFiles/reports'
    validation = json.loads((reports/'final_validation.json').read_text(encoding='utf-8'))
    assert validation['revision'] == 11 and validation['status'] == 'passed'
    assert sha(P/'torment-tides-of-numenera_text_translated.csv') == validation['translation_sha256']
    locale = P/'repack/feedback_20261028/localized/en'
    prefix = 'WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en/'
    files = [dict(source=f.relative_to(P).as_posix(), path=prefix+f.relative_to(locale).as_posix(), sha256=sha(f))
        for f in sorted(locale.rglob('*.stringtable'))]
    dllpath = 'WIN/TidesOfNumenera_Data/Managed/Assembly-CSharp.dll'
    dll = P/'repack/cjk_crop_20261028'/dllpath
    files.append(dict(source=dll.relative_to(P).as_posix(), path=dllpath, sha256=sha(dll)))
    crop = json.loads((reports/'cjk_crop_patch_20261028.json').read_text(encoding='utf-8'))
    assert len(files) == 2251 and files[-1]['sha256'] == crop['patched_sha256']
    assert all(sha(P/'Game'/f['path']) == f['sha256'] for f in files)
    write(reports/'release_v1.6_payload.json', dict(files=files))
    authorization = dict(authorization='explicit_user_release', in_game_validation='pending',
        accept_pending_runtime=True,
        user_statement='目前是这些问题都修复了吗，只剩下我测试吗，如果是这样，那么直接发布吧',
        verified_scope='Revision11 full text gates, source binding, offline managed crop checks and installed payload hashes passed. No game launched; no new runtime checks claimed.',
        translation_sha256=validation['translation_sha256'])
    evidence = reports/'release_v1.6_authorization.json'
    write(evidence, authorization)
    flow = Workflow(P)
    try:
        prior = flow.release_check()
    except ValueError as e:
        prior = dict(status='requires_runtime_or_explicit_authorization', reason=str(e))
    write(reports/'release_v1.6_gate_before_authorization.json', prior)
    report = {**authorization, 'game_version':'Steam v1.1.0', 'platform':'Steam（Windows）',
        'payload_files':[dict(path=f['source'], game_path=f['path'], sha256=f['sha256']) for f in files],
        'evidence_files':[dict(path=evidence.relative_to(P).as_posix(), sha256=sha(evidence))]}
    write(reports/'release_v1.6_acceptance_receipt.json', flow.record_release_acceptance(report))
    write(reports/'release_v1.6_quality_gate.json', flow.release_check())
    config = json.loads((P/'Dispatch/v1.5_installer_config.json').read_text(encoding='utf-8'))
    originals = {f['path']:f['sha256'] for f in config['originals']}
    assert set(originals) == {f['path'] for f in files}
    legacy = {(f['path'],f['sha256']) for f in config['legacy']}
    for archive in sorted((P/'Dispatch').glob('*.zip')):
        with zipfile.ZipFile(archive) as z:
            manifest = json.loads(z.read('PATCH_MANIFEST.json'))
        legacy.update((f['path'],f['sha256']) for f in manifest['files'] if f['path'] in originals and f['sha256'] != originals[f['path']])
    legacy.update((f['path'],f['sha256']) for f in files if f['sha256'] != originals[f['path']])
    config['legacy'] = [dict(path=p,sha256=h) for p,h in sorted(legacy)]
    assert sha(P/'Game'/config['exe']) == config['exe_sha256']
    installer = P/'Dispatch/v1.6_installer_config.json'; write(installer,config)
    metadata = json.loads((reports/'release_v1.5_metadata.json').read_text(encoding='utf-8'))
    metadata.update(version='1.6', title='《Torment: Tides of Numenera》子非鱼AI汉化补丁 v1.6',
        release_date='2026-10-28', installer_config=str(installer),
        introduction='为Steam Windows版制作的简体中文完整汉化补丁，包含历次修正、教程字号及物品描述显示修复。',
        changes='修复物品描述出现颜色标签代码的问题；补齐取卵等对话中的英文残留及成功、失败提示；统一镜像术语为“二重身”、生物名称为“斯提查”；改善生硬对白及相关名称，共修正445条文本。')
    metadata.update(json.loads((P/'Dispatch/release_links.json').read_text(encoding='utf-8')))
    write(reports/'release_v1.6_metadata.json',metadata)
    (P/'Analysis/release_v1_6.py').write_text((P/'Analysis/release_v1_5.py').read_text(encoding='utf-8').replace('v1.5','v1.6'),encoding='utf-8')
    print(json.dumps(dict(payload_files=len(files), release_authorization='explicit_user_release', in_game_validation='pending')))


if __name__ == '__main__': main()
