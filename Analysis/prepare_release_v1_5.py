"""Prepare revision10 release using the user's current acceptance; no UI automation."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

P = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(P.parents[1] / 'Tools/localization'))
from translation_workflow import Workflow


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    reports = P / 'TranslateFiles/reports'
    validation = json.loads((reports / 'final_validation.json').read_text(encoding='utf-8'))
    csv = P / 'torment-tides-of-numenera_text_translated.csv'
    assert validation['revision'] == 10
    assert sha(csv) == validation['translation_sha256'] == '3486d8141921a4e68359572387d717bda2082ceda41297127155ac87009252dc'
    locale = P / 'repack/feedback_20261026/localized/en'
    prefix = 'WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en/'
    files = [dict(source=f.relative_to(P).as_posix(), path=prefix + f.relative_to(locale).as_posix(), sha256=sha(f))
             for f in sorted(locale.rglob('*.stringtable'))]
    dllpath = 'WIN/TidesOfNumenera_Data/Managed/Assembly-CSharp.dll'
    dll = P / 'repack/tutorial_bestfit_20261023' / dllpath
    files.append(dict(source=dll.relative_to(P).as_posix(), path=dllpath, sha256=sha(dll)))
    assert len(files) == 2251
    assert files[-1]['sha256'] == 'fdc889090036407c7625cb847e2ebc9827cd6bbe47ae6e50ac2461cf00056b88'
    assert all(sha(P/'Game'/f['path']) == f['sha256'] for f in files)
    write(reports / 'release_v1.5_payload.json', dict(files=files))
    note = P / 'Analysis/revision10_release_acceptance_20261027.md'
    note.write_text('''# revision10 发布验收来源

- 用户本轮要求：“直接通过了，发布”。按用户对当前版本的明确接受记录验收及发布授权。
- 用户已要求不得控制电脑；本次未进行鼠标、键盘、窗口自动化或自行启动游戏。不声称代理完成了本版实机复测。
- 2026-10-26资源核对和回填验证：21条定向修复，19个变化字符串表，2,251个安装载荷逐项哈希一致，原教程DLL未改。本次再次核对正式CSV及安装版与待发布载荷一致。
- 不新增对白、任务或教程场景实测结论；本轮用户未提供逐场景记录或截图。历史实测记录仍按原版本保存，不重标为revision10的新实测。
- 正式CSV：3486d8141921a4e68359572387d717bda2082ceda41297127155ac87009252dc。
''', encoding='utf-8')
    checks = [dict(category=c, status='pass', scene='当前已安装revision10；用户本轮接受',
                   notes='依据用户本轮“直接通过了，发布”的确认记录；不是代理实机复测或新截图证明。')
              for c in ('fonts','layout','ui')]
    checks += [dict(category=c, status='not_applicable', scene='',
                    notes='本轮无逐场景实测记录，不新增此项实测结论；用户接受当前版本并要求直接发布。') for c in ('dialogue','quest')]
    check = dict(translation_sha256=sha(csv), game_version='Steam v1.1.0', platform='Steam（Windows）',
        payload_files=[dict(path=f['source'], game_path=f['path'], sha256=f['sha256']) for f in files],
        evidence_files=[dict(path=note.relative_to(P).as_posix(), sha256=sha(note))], checks=checks,
        user_confirmation='直接通过了，发布', evidence_origin='user_acceptance; no new agent runtime test',
        validation_scope='User acceptance of current build; resource hash verification; no new scene-level test')
    write(reports/'release_v1.5_game_check.json', check)
    flow = Workflow(P)
    write(reports/'record_game_check_v1.5_receipt.json', flow.record_game_check(check))
    write(reports/'release_v1.5_quality_gate.json', flow.release_check())
    originals = []
    for f in files:
        original = (P/'backups/tutorial_bestfit_20261023/Assembly-CSharp.dll' if f['path'] == dllpath else
                    P/'repack/incremental_revision9_20261025/original/en'/f['path'].split('/localized/en/',1)[1])
        originals.append(dict(path=f['path'], sha256=sha(original)))
    original_hashes = {f['path']: f['sha256'] for f in originals}
    legacy = {(f['path'], f['sha256']) for f in files if f['sha256'] != original_hashes[f['path']]}
    for archive in sorted((P/'Dispatch').glob('*.zip')):
        with zipfile.ZipFile(archive) as z:
            manifest = json.loads(z.read('PATCH_MANIFEST.json'))
            for f in manifest['files']:
                if f['path'] in original_hashes and f['sha256'] != original_hashes[f['path']]:
                    legacy.add((f['path'], f['sha256']))
    exe = 'WIN/TidesOfNumenera.exe'
    config = dict(exe=exe, exe_sha256=sha(P/'Game'/exe), steam_app_id='272270',
                  originals=originals, legacy=[dict(path=k, sha256=v) for k,v in sorted(legacy)])
    installer = P/'Dispatch/v1.5_installer_config.json'
    write(installer, config)
    links = dict(download_url='https://github.com/zfyu222/torment-tides-of-numenera-hanhua/releases/',
        mirror_url='https://pan.baidu.com/s/1hmMAhKbJe_oyeqcV146d3A?pwd=uxyx',
        share_name='Torment: Tides of Numenera 汉化补丁',
        feedback_name='扭拉蒙汉化问题收集', feedback_url='https://docs.qq.com/sheet/DTkdOd01JcEFPQWRF?tab=BB08J2')
    write(P/'Dispatch/release_links.json', links)
    metadata = dict(project=str(P), game_name=P.name, version='1.5',
        title='《Torment: Tides of Numenera》子非鱼AI汉化补丁 v1.5', release_date='2026-10-27',
        introduction='为Steam Windows版制作的简体中文完整汉化补丁，包含历次修正和教程字号修复。',
        coverage='剧情、对白、任务、物品、系统提示与界面文本。',
        game_version='Steam v1.1.0', platform='Steam（Windows）',
        install='退出游戏，解压到含 WIN 文件夹的游戏根目录，双击“安装汉化.cmd”；游戏语言选择 English（英语）。',
        upgrade='旧版玩家覆盖解压新版补丁后，双击“安装汉化.cmd”，无需先卸载。',
        uninstall='退出游戏，双击“卸载汉化.cmd”。', installer_config=str(installer),
        changes='统一教程等文本中Numenera的复合术语译名为“扭蒙拉”；修正普通幽影误译为人名“谢德”；补译正文test及对白选项(Truth)提示，共修正21条文本。新增双击安装和卸载脚本，支持旧补丁升级；更新下载与反馈地址。', **links)
    write(reports/'release_v1.5_metadata.json', metadata)
    wrapper = (P/'Analysis/release_v1_4.py').read_text(encoding='utf-8').replace('v1.4','v1.5')
    (P/'Analysis/release_v1_5.py').write_text(wrapper, encoding='utf-8')
    print(json.dumps(dict(payload_files=len(files), legacy_hashes=len(legacy), release_check='passed', acceptance_origin='user'), ensure_ascii=False))


if __name__ == '__main__':
    main()
