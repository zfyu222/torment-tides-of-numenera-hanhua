"""Bind the installed revision9 payload and honestly scoped runtime evidence."""
import hashlib
import json
from pathlib import Path


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    p = Path(__file__).resolve().parents[1]
    reports = p / 'TranslateFiles/reports'
    validation = json.loads((reports / 'final_validation.json').read_text(encoding='utf-8'))
    if validation['revision'] != 9 or validation['translation_sha256'] != sha(p / 'torment-tides-of-numenera_text_translated.csv'):
        raise ValueError('Not the validated revision9 export')
    locale = p / 'repack/incremental_revision9_20261025/localized/en'
    files = [{'source': f.relative_to(p).as_posix(),
              'path': 'WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en/' + f.relative_to(locale).as_posix(),
              'sha256': sha(f)} for f in sorted(locale.rglob('*.stringtable'))]
    dll = p / 'repack/tutorial_bestfit_20261023/WIN/TidesOfNumenera_Data/Managed/Assembly-CSharp.dll'
    files.append({'source': dll.relative_to(p).as_posix(),
                  'path': 'WIN/TidesOfNumenera_Data/Managed/Assembly-CSharp.dll', 'sha256': sha(dll)})
    if len(files) != 2251:
        raise ValueError('Incomplete release payload')
    for f in files:
        if sha(p / 'Game' / f['path']) != f['sha256']:
            raise ValueError('Installed and release payload differ: ' + f['path'])
    write(reports / 'release_v1.4_payload.json', {'files': files})
    runtime = p / 'Analysis/revision9_runtime_20261025'
    runtime.mkdir(parents=True, exist_ok=True)
    note = runtime / 'verification.md'
    note.write_text('''# revision9 当前载荷实机记录

- 版本：Steam Windows v1.1.0；正式译文哈希：074e4cdee16947f1fe5b4bcd3669f6ce1d91fa2027d4cd6055a0b351166c67b6。
- 代理用已安装文件实际启动游戏，确认主菜单及选项页中文可读、按钮与文本无可见遮挡，未见缺字；截图为本版 main_menu.png、options.png。
- 在尝试继续载入存档时，计算机工具报 foreground window did not report a process id；未把该操作当作载入成功或崩溃证明，用户随后中断测试。
- 用户本轮原话：“没问题，直接发布”。按用户指示，本次实机检查范围为启动、主菜单、选项的冒烟检查；不继续执行对白/任务/教程专项实测，不声称逐场景通关。
- 日志中两个 test_crisis_objectives 测试任务字符串表缺失，原英文备份同样没有这两个文件；保留原状，不补写测试资源。
- 所有2250个字符串表和教程修复DLL均逐项绑定项目副本、安装目的路径和SHA-256，当前安装版与待发布载荷一致。教程DLL哈希与已发布v1.3相同。
''', encoding='utf-8')
    evidence = [note, runtime / 'main_menu.png', runtime / 'options.png']
    checks = [
        {'category': 'fonts', 'status': 'pass', 'scene': 'Steam v1.1.0 主菜单与选项页', 'notes': '代理实际观察中文及标点可读，无可见缺字；只覆盖截图场景。'},
        {'category': 'layout', 'status': 'pass', 'scene': 'Steam v1.1.0 主菜单与选项页', 'notes': '代理实际观察按钮和文字布局完整，无可见遮挡；未追加其他分辨率或教程专项检查。'},
        {'category': 'ui', 'status': 'pass', 'scene': '主菜单打开选项后取消返回', 'notes': '代理实际操作选项入口及取消返回，对应中文按钮可用。'},
        {'category': 'dialogue', 'status': 'not_applicable', 'scene': '', 'notes': '用户要求“没问题，直接发布”，本次实机冒烟范围未包含对白专项测试；不据此承诺对白全无问题，文本独立审校证据另行保留。'},
        {'category': 'quest', 'status': 'not_applicable', 'scene': '', 'notes': '用户要求直接发布，本次实机冒烟未执行任务推进或日志专项检查；不声称逐剧情通关。'}]
    write(reports / 'release_v1.4_game_check.json', {
        'translation_sha256': validation['translation_sha256'], 'game_version': 'Steam v1.1.0', 'platform': 'Steam（Windows）',
        'payload_files': [{'path': f['source'], 'game_path': f['path'], 'sha256': f['sha256']} for f in files],
        'evidence_files': [{'path': f.relative_to(p).as_posix(), 'sha256': sha(f)} for f in evidence],
        'checks': checks, 'user_confirmation': '没问题，直接发布', 'validation_scope': 'startup/menu/options smoke test; dialogue/quest/tutorial not retested'})
    metadata = json.loads((reports / 'release_v1.3_metadata.json').read_text(encoding='utf-8'))
    metadata.update(version='1.4', title='《Torment: Tides of Numenera》子非鱼AI汉化补丁 v1.4', release_date='2026-10-25',
        introduction='为Steam Windows版制作的简体中文汉化补丁。本版调整术语收录与遵守等级，并对受影响文本独立重译和审校，改善普通词被固定译名套用的问题。保留既有教程字号修复。',
        install=metadata['install']+' 已安装v1.0至v1.3的玩家同样直接覆盖，无需先卸载；本包为完整补丁，新玩家无需先装旧版。',
        verification='70,163条正式文本通过结构、占位符、术语与质量闭环校验；2,250个字符串表全部XML可解析，89,239个非空字段零缺失映射。启动、主菜单及选项中文显示和操作已实际检查，用户确认当前版“没问题，直接发布”。本次实机冒烟未追加对白、任务、教程专项及完整通关测试。发布载荷与安装版SHA-256逐一一致。',
        known_issues='AI辅助汉化仍可能存在词义、措辞、专名或遗漏问题，请适当降低预期；本次仅完成启动及菜单/选项实机冒烟，未逐场景通关，也未追加对白/任务/教程专项、物理手柄及多分辨率回归。标题Logo保持英文，中文自动断行可能将标点留在行首。仅支持Steam v1.1.0 Windows，更新或验证文件完整性后可能需重装。反馈：https://github.com/zfyu222/torment-tides-of-numenera-hanhua/issues；补丁后续可能会更新，建议关注或订阅 https://github.com/zfyu222/torment-tides-of-numenera-hanhua/releases 。',
        changes='复核5,579项术语，移出992项普通词并区分必须遵守与参考译名；对25,134条增量范围完成独立审校，实际更新22,688条译文，范围外45,029条保持不变。修正人物特质Hardened的生硬用词、user等日常词套用固定译名的问题，修复隐藏性别标记形成的空括号，以及两处分支中stubbled scalp的词义；保留扭蒙拉、绑定物品译名和既有教程字号修复。')
    write(reports / 'release_v1.4_metadata.json', metadata)
    wrapper = (p / 'Analysis/release_v1_3.py').read_text(encoding='utf-8').replace('v1.3', 'v1.4')
    (p / 'Analysis/release_v1_4.py').write_text(wrapper, encoding='utf-8')
    print(json.dumps({'payload_files': len(files), 'installed_hashes_match': True, 'game_check': 'release_v1.4_game_check.json'}))


if __name__ == '__main__':
    main()
