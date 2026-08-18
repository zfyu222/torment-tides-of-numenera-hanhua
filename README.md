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
| 翻译 |  |  |
| 回填 |  |  |

## 文本提取
- 文本位置：`Game/WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en/text/**/*.stringtable`
- 工具/命令：递归读取 2,250 个 `.stringtable` XML 文件，提取每个 `Entry` 的非空 `DefaultText` 与 `FemaleText`，按原文去重后写入标准单列 CSV；使用 Python 标准库 `csv` 与 `xml.etree.ElementTree` 交叉回读校验。
- 步骤：扫描英文 `conversations`、`game`、`quests` 三类字符串表；提取 89,239 个非空字段（其中 `DefaultText` 88,084 个、`FemaleText` 1,155 个）；按精确文本去重并将 CRLF/LF 视作同一文本，输出 70,163 条唯一原文到 `torment-tides-of-numenera_text.csv`。
- 提取文本数量：70,163 条唯一文本；文件大小 8,978,336 字节；SHA-256：`BD3B7F02212489417247EB0956C771AE2D52471C5999E6AEFF6F588618B8F416`。
- 注意事项：输出为 UTF-8（无 BOM）标准单列 CSV、无表头。含逗号、双引号或内嵌换行的文本使用 CSV 引号转义；原文内的段落换行得到保留。安装包还含 `de/es/fr/it/pl/ru` 本地化目录，但本次只提取英语源文。资源内含少量测试/调试字符串，留待翻译阶段通过排除表处理。

## 翻译
- 词典：
- 策略：

## 回填
- 工具/命令：
- 步骤：
- 验证方法：

## 已知问题

## 版本记录
- 2026-08-18 - 初始化汉化项目工作区（start-translate skill）
- 2026-08-18 - 补充 Steam 基本资料、本地 Unity Mono 技术线索与文本提取候选位置
- 2026-08-18 - 从英文 `.stringtable` 提取并校验 70,163 条唯一原文
