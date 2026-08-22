"""Package the verified localized stringtable tree with the standard release tool."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import zipfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parent
TEXT_ROOT = PROJECT / "repack" / "localized" / "en_20260822" / "text"
DESTINATION_ROOT = "WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en/text"
RELEASE_SCRIPT = Path(
    r"D:\StaticHanHua\.agents\skills\game-release-patch\scripts\create_release_patch.py"
)


def ensure_changelog(archive_path: Path) -> None:
    """Seed the legacy v1.0 archive history in the new v1.1 release guide."""
    with tempfile.NamedTemporaryFile(delete=False, dir=archive_path.parent, suffix=".zip") as handle:
        temporary_path = Path(handle.name)
    try:
        with zipfile.ZipFile(archive_path, "r") as source, zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as target:
            for entry in source.infolist():
                content = source.read(entry.filename)
                if entry.filename == "补丁说明.txt":
                    guide = content.decode("utf-8-sig")
                    normalized = guide.replace("\r\n", "\n")
                    normalized = normalized.replace(
                        "更新日志\n- v1.1（2026-08-22）：",
                        "更新日志\n- v1.0（2026-08-20）：首次发布。\n- v1.1（2026-08-22）：",
                        1,
                    )
                    content = normalized.encode("utf-8-sig")
                target.writestr(entry, content)
        temporary_path.replace(archive_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    files = sorted(TEXT_ROOT.rglob("*.stringtable"))
    if len(files) != 2250:
        raise RuntimeError(f"Expected 2250 stringtable files, found {len(files)}")

    argv = [
        str(RELEASE_SCRIPT),
        "--project", str(PROJECT),
        "--game-name", "torment-tides-of-numenera",
        "--version", "1.1",
        "--title", "《Torment: Tides of Numenera》子非鱼AI汉化补丁 v1.1",
        "--introduction", "为 Steam Windows 版《Torment: Tides of Numenera》制作的简体中文 AI 汉化补丁。",
        "--coverage", "主线剧情、对话、任务、系统提示与常用 UI 文本，共 2,250 个字符串表。",
        "--game-version", "Steam v1.1.0",
        "--platform", "Steam（Windows）",
        "--release-date", "2026-08-22",
        "--install", "退出游戏后，将压缩包内的 WIN 文件夹复制到游戏根目录并选择合并/覆盖；建议先备份 WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en/text/ 目录。无需安装 Mod 加载器。",
        "--uninstall", "用安装前备份恢复 WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en/text/ 目录；没有备份时，在 Steam 客户端执行“验证游戏文件完整性”恢复英文原版。",
        "--verification", "已在 Steam Windows v1.1.0 实测启动、主菜单、性别选择与首段剧情，中文显示正常。",
        "--known-issues", "标题 Logo 仍为英文；本补丁为 AI 辅助汉化，尚未逐条人工润色，少量超长文本可能需要后续优化。",
        "--changes", "根据术语表完成全量重新翻译与术语校准，修复运行时标签和文本布局。",
    ]
    if "--dry-run" in sys.argv[1:]:
        argv.append("--dry-run")
    if "--force" in sys.argv[1:]:
        argv.append("--force")
    for file in files:
        source = file.relative_to(PROJECT).as_posix()
        destination = f"{DESTINATION_ROOT}/{file.relative_to(TEXT_ROOT).as_posix()}"
        argv.extend(["--include", f"{source}={destination}"])

    spec = importlib.util.spec_from_file_location("release_patch", RELEASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the release patch tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old_argv = sys.argv
    try:
        sys.argv = argv
        result = module.main()
    finally:
        sys.argv = old_argv
    if result == 0 and "--dry-run" not in old_argv[1:]:
        ensure_changelog(PROJECT / "Dispatch" / "torment-tides-of-numenera_子非鱼汉化1.1.zip")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
