# torment-tides-of-numenera 汉化项目

> 本文件由 `start-translate` skill 自动生成，请补充游戏信息与汉化方案。

## 游戏信息
- 原名：Torment: Tides of Numenera
- 中文名：折磨：努曼内拉之潮（暂译）
- 开发商：inXile Entertainment
- 发行平台：Steam（Windows；商店页亦列出 macOS、SteamOS + Linux）
- 引擎：Unity 5.4.1p3（Mono；版本取自 `globalgamemanagers` 文件头）
- 原语言：英语（Steam 同时提供法语、德语、西班牙语、波兰语、俄语）

## 游戏简介

本作是《异域镇魂曲》的精神续作，属于单人等距视角、以叙事与抉择为核心的 CRPG，背景设定在 Monte Cook 创作的努曼内拉“第九世界”。玩家扮演从轨道坠落、曾被“变易之神”占据躯体的新意识，需要躲避名为“悲伤”的古老追猎者，并回答“一个生命有何意义”。资料来源：[Steam 商店页](https://store.steampowered.com/app/272270/Torment_Tides_of_Numenera/)。

## 汉化目标
- 范围：英文字符串表中的剧情、对话、任务、系统与 UI 文本
- 目标语言：简体中文

## 技术栈
| 环节 | 工具 | 版本 |
|------|------|------|
| 提取 | PowerShell `.NET XmlDocument` + 标准 CSV 写入；Python `csv` / `ElementTree` 完整性校验 | PowerShell 7.6.4 / Python 3.12.10 |
| 翻译 | AINiee（待用户在 GUI 执行）；`analyze_placeholders.py` / `validate_translation.py` | 工作区当前版本 / Python 3.12.10 |
| 回填 |  |  |

## 文本提取
- 文本位置：`Game/WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en/text/**/*.stringtable`
- 工具/命令：递归读取 2,250 个 `.stringtable` XML 文件，提取每个 `Entry` 的非空 `DefaultText` 与 `FemaleText`，按原文去重后写入标准单列 CSV；使用 Python 标准库 `csv` 与 `xml.etree.ElementTree` 交叉回读校验。
- 步骤：扫描英文 `conversations`、`game`、`quests` 三类字符串表；提取 89,239 个非空字段（其中 `DefaultText` 88,084 个、`FemaleText` 1,155 个）；按精确文本去重并将 CRLF/LF 视作同一文本，输出 70,163 条唯一原文到 `torment-tides-of-numenera_text.csv`。
- 提取文本数量：70,163 条唯一文本；文件大小 8,978,336 字节；SHA-256：`BD3B7F02212489417247EB0956C771AE2D52471C5999E6AEFF6F588618B8F416`。
- 注意事项：输出为 UTF-8（无 BOM）标准单列 CSV、无表头。含逗号、双引号或内嵌换行的文本使用 CSV 引号转义；原文内的段落换行得到保留。安装包还含 `de/es/fr/it/pl/ru` 本地化目录，但本次只提取英语源文。资源内含少量测试/调试字符串，留待翻译阶段通过排除表处理。

## 翻译
- 状态：AINiee 全量翻译与译后修复已完成，产物为 `torment-tides-of-numenera_text_translated.csv`。
- 词典：`TranslateDoc.md` 提供首轮术语建议；“变易之神”“遗弃者”“辛币”等暂定译名需在全量翻译前确认并保持一致。
- 占位符/禁翻表：已生成 `placeholder_report.md` 与 `ainiee_exclusion_list.json`。保护方括号运行时标记、数字/命名花括号、实际 `<quad>` / `<a>` 渲染标签、printf 格式符以及字面 `\n` / `\t`。宽泛尖括号规则已人工收紧，确保 `<No,>`、`<Out!>` 等玩家可见心灵对白仍会翻译。
- 策略：使用 AINiee 全量翻译；译后对英文残留反查原始字符串表和游戏自带德/法/西/波/俄本地化，保留调试节点、编辑占位、虚构语言与赞助者姓名，人工补译 31 条正式心灵对白、剧情文本和物品说明。
- 校验状态：70,163 条逻辑记录全部对齐，无空译文；67,828 条已翻译或发生本地化改动，2,335 条原样保留（运行时标记、调试/编辑占位、专名、虚构语言等）。原始通用校验器会把玩家可见的自然方括号/尖括号文本误判为变量，因此在执行其自动修复后恢复了校验前备份，并按本项目人工收紧规则复检。实际运行时方括号标记、数字/命名花括号、`<quad>` / `<a>` 标签、printf 格式符、字面转义及每条真实换行结构均一致；另修复 1 条提前闭合的 `[/Color]` 标签。项目专用复检退出码为 0。

## 回填
- 工具/命令：
- 步骤：
- 验证方法：

## 已知问题

## 版本记录
- 2026-08-18 - 初始化汉化项目工作区（start-translate skill）
- 2026-08-18 - 补充 Steam 基本资料、本地 Unity Mono 技术线索与文本提取候选位置
- 2026-08-18 - 从英文 `.stringtable` 提取并校验 70,163 条唯一原文
- 2026-08-18 - 完成 AINiee 翻译准备、占位符人工复核与术语建议
- 2026-08-19 - 完成 70,163 条译文校验，补译正式英文残留并修复颜色标签
