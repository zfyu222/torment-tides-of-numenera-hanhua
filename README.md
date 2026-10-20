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
| 翻译 | AINiee；`analyze_placeholders.py` / 项目收紧规则复检 | AINiee 7.2.4 dev / Python 3.12.10 |
| 回填 | `repack_stringtables.py` 直接替换 StreamingAssets XML 字符串表 | Python 3.12.10 |
| 发布 | `game-release-patch`；百度网盘本地上传 MCP | Python 3.12.10 |

## 文本提取
- 文本位置：`Game/WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en/text/**/*.stringtable`
- 工具/命令：递归读取 2,250 个 `.stringtable` XML 文件，提取每个 `Entry` 的非空 `DefaultText` 与 `FemaleText`，按原文去重后写入标准单列 CSV；使用 Python 标准库 `csv` 与 `xml.etree.ElementTree` 交叉回读校验。
- 步骤：扫描英文 `conversations`、`game`、`quests` 三类字符串表；提取 89,239 个非空字段（其中 `DefaultText` 88,084 个、`FemaleText` 1,155 个）；按精确文本去重并将 CRLF/LF 视作同一文本，输出 70,163 条唯一原文到 `torment-tides-of-numenera_text.csv`。
- 提取文本数量：70,163 条唯一文本；文件大小 8,978,336 字节；SHA-256：`BD3B7F02212489417247EB0956C771AE2D52471C5999E6AEFF6F588618B8F416`。
- 注意事项：输出为 UTF-8（无 BOM）标准单列 CSV、无表头。含逗号、双引号或内嵌换行的文本使用 CSV 引号转义；原文内的段落换行得到保留。安装包还含 `de/es/fr/it/pl/ru` 本地化目录，但本次只提取英语源文。资源内含少量测试/调试字符串，留待翻译阶段通过排除表处理。

## 翻译
- 2026-10-21 自定义 API 进度与阻断：首轮术语提取运行约82.7分钟，604次请求接收453个批次，当前任务总数1,285，另有806个待执行任务、26个待处理交接；尚未完成全文提取，未进入术语冻结或150条试译。151次失败尝试中有133次模型结果拒收，包含来源证据不匹配（拒收文件统计72份）、输出截断及JSON不完整等，不能一概视为接口超时；所有失败均未作为合格结果放行。随后接口对所选模型返回 `HTTP400: No available relay channel for current group and model`，单次最小连接诊断亦复现，等待用户恢复原通道或指定其他接口/模型，未擅自切换。已报告用量为8,010,797 Token，另18次请求未返回用量；这不是费用估算。程序已暂停、运行器已退出，成功任务、原始回复与会话映射留在本机供恢复，未重置尝试预算。摘要：`TranslateFiles/reports/api_retranslation_checkpoint_20261021.json`。旧正式CSV哈希保持不变，游戏仍使用原修复版。
- 2026-10-20 启动自定义 API 全量重译准备：用户选择自定义 API 路线，沿用本机已配置的 `deepseek-v4.1-flash` 接口；密钥仅留本机公共配置，不入项目或 Git。现有修复版正式 CSV 已备份至 `TranslateFiles/backups/ainiee_before_custom_20261020/`，本轮通过完整验收前不覆盖它或游戏资源。新建自定义流程状态，共70,163条源文；从原英文备份绑定89,239处字段引用、43个资源分组，不根据CSV相邻位置推断剧情。配置为 `TranslateFiles/config/workflow.json`，准备脚本为 `TranslateFiles/prepare_api_retranslation.py`。重新核实50种代码中可证的字面运行时标记，限定方括号和尖括号保护规则；普通括号内自然语言不整体禁翻，历史缓存排除状态不导入。先全文术语提取、语义审校和冻结，再随机150条试译校准；已知漏翻及解释混入问题另作专项检查。当前尚未完成新译。
- 2026-10-20 截图反馈修复：沿用 AINiee 译稿，人工补译 29 条正式文本，包括 `x1131_falling` 的超级大陆叙述、开场民兵叙述、两段身体记忆及被尖括号禁翻规则误保留的心灵对白。另为教程 GUI ID `1399`、`1423`、`1425` 加入显示换行，保留鼠标/手柄标记；这是有意的排版例外，不要用旧版换行恢复脚本撤销。修改表为 `TranslateFiles/config/screenshot_fixes_20261020.json`，逐条原文/修改前后及检查记录为 `TranslateFiles/reports/screenshot_fixes_20261020.json`。全量回读 70,163 条，恰有 32 条修改、70,131 条保持不变，无空译文；运行时标记保持一致。译文 SHA-256：`2541E64264D271E5D46B22A6C6C4F133C13382C5FDFA1F22AABE8C9562FD65E8`。本次未运行全文重译或全文语义复审。
- 状态：AINiee 全量翻译与译后修复已完成，产物为 `torment-tides-of-numenera_text_translated.csv`。
- 词典：`TranslateDoc.md` 提供首轮术语建议；“变易之神”“遗弃者”“辛币”等暂定译名需在全量翻译前确认并保持一致。
- 占位符/禁翻表：已生成 `placeholder_report.md` 与 `ainiee_exclusion_list.json`。保护方括号运行时标记、数字/命名花括号、实际 `<quad>` / `<a>` 渲染标签、printf 格式符以及字面 `\n` / `\t`。宽泛尖括号规则已人工收紧，确保 `<No,>`、`<Out!>` 等玩家可见心灵对白仍会翻译。
- 策略：使用 AINiee 全量翻译；译后对英文残留反查原始字符串表和游戏自带德/法/西/波/俄本地化，保留调试节点、编辑占位、虚构语言与赞助者姓名，人工补译 31 条正式心灵对白、剧情文本和物品说明。
- 校验状态：70,163 条逻辑记录全部对齐，无空译文；67,828 条已翻译或发生本地化改动，2,335 条原样保留（运行时标记、调试/编辑占位、专名、虚构语言等）。原始通用校验器会把玩家可见的自然方括号/尖括号文本误判为变量，因此在执行其自动修复后恢复了校验前备份，并按本项目人工收紧规则复检。实际运行时方括号标记、数字/命名花括号、`<quad>` / `<a>` 标签、printf 格式符、字面转义及每条真实换行结构均一致；另修复 1 条提前闭合的 `[/Color]` 标签。项目专用复检退出码为 0。
- 2026-08-22 重新翻译与术语校准：导入用户完成的全量重译稿后，70,163 条记录全部对齐且无空译文，68,374 条与原文不同；译文 SHA-256：`9113E17BBC059DDDD86F1EB34E9BEC6F1051C6BD5C80BC1CDB5719F478202B55`。复检仅恢复上一已验证版本的换行和字面 `\n` 布局，不改动措辞；修复 4 处可确证的机器标记问题（`FettleIcon`、颜色关闭标签和两个 `{01}` / `{02}` 编号）。颜色/图标/全局变量、`<quad>` / `<a>`、数字花括号、美元变量和唯一的 `%%` 格式符均逐项匹配。通用校验器的其余 949 条方括号报告为玩家可见技能判定、编辑说明或自然语言方括号文本的既有误判。

## 回填
- 2026-10-20 截图修复已部署：使用同一回填脚本，从原英文备份生成 `repack/fixes_20261020/localized/en/`，2,250 个字符串表、89,239 个非空字段均成功映射，84,361 个字段发生改动；输出树 SHA-256：`B2444575E01B0E2838EEDBB5C6CBB103FAB5540EC03158EA80B4D946FA319021`。与上次安装相比仅 7 个字符串表变化；部署后 2,251 个文件逐一 SHA-256 一致，详见 `TranslateFiles/reports/deployment_20261020.json`。修改前 CSV 和上述 7 个文件保存在 `backups/screenshot_fixes_20261020/`，同步更新项目现有 `repack/localized/en/`。
- 本次 UI 实测：通过临时诊断入口调用游戏自身 `TutorialMessageWindow`，在同一分辨率下对比原译文和换行后译文。努力教程实际 Best Fit 字号 14→22，物品栏教程 11→22，均显示为三行且按钮完整。修复通过字符串表换行实现，无需替换字体或安装插件。测试后原 `Assembly-CSharp.dll` 已恢复、诊断 DLL 已移除；诊断原理及边界见 `Analysis/screenshot_fix_validation_20261020.md`。手柄文本及其余 29 条补译已完成数据校验，未逐场景实机触发；其他界面的字号仍需按具体场景反馈。
- 工具/命令：`python repack_stringtables.py torment-tides-of-numenera_text.csv torment-tides-of-numenera_text_translated.csv <原英文目录> repack/localized/en`
- 策略：游戏直接从 `StreamingAssets/data/localized/<语言>/text/**/*.stringtable` 读取文本。为避免修改语言枚举代码，生成完整中文覆盖包并覆盖现有 `en` 语言槽；`language.xml` 保持 English 标识，因此游戏选用英语时直接加载中文。
- 生成结果：2,250 个字符串表、89,239 个非空字段全部映射；83,363 个字段发生本地化改动，83,310 个字段含中日韩统一表意文字；输出树 SHA-256：`85F75C575774528EFF3E5DE5F484DECA9353BBB2C591B51881C17D2C2B7B6A3D`。
- 修改文件：`Game/WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en/` 下的 2,250 个 `.stringtable`；部署后与 `repack/localized/en/` 的 2,251 个文件逐一 SHA-256 一致。
- 原版备份：`backups/localized_en_original_20260819_085840.zip`（2,250 个字符串表，压缩包 5,328,111 字节，已验证目录清单）。恢复时解压其中 `en/` 覆盖游戏的同名目录即可。
- 验证方法：实际启动 `TidesOfNumenera.exe`，依次检查启动、主菜单、加载提示、性别选择与首段新游戏剧情。
- 验证结果：通过。游戏正常启动且无崩溃；上述界面均加载中文；中文字体完整，无方框、乱码或明显缺字；首段剧情段落换行和“继续”按钮显示正常。
- 2026-08-22 回填：从原版英文备份重建 2,250 个字符串表，89,239 个非空字段全部映射，84,331 个字段发生本地化改动，84,284 个字段含中日韩统一表意文字；输出树 SHA-256：`DF7B5023612437701628F8F5850AC53969C5294EA63EB58BE616986C6D4333C2`。部署前备份为 `backups/localized_en_pre_v1.1_20260822.zip`；部署后 2,251 个文件逐一 SHA-256 一致。已在 Steam Windows v1.1.0 实测启动、主菜单、性别选择与首段剧情，中文字体、换行和“继续”按钮均正常。

## 对外发布

- 补丁：`Dispatch/torment-tides-of-numenera_子非鱼汉化1.1.zip`
- 标题：`《Torment: Tides of Numenera》子非鱼AI汉化补丁 v1.1`
- 支持版本/平台：Steam v1.1.0（Windows）。
- 内容：按游戏根目录路径提供 `WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en/text/` 下的 2,250 个已汉化 `.stringtable` 文件；不含游戏本体、原始资源、CSV 或开发文件。
- 安装：退出游戏后，将压缩包中的 `WIN` 文件夹复制到游戏根目录并选择合并/覆盖。安装前请备份 `WIN/TidesOfNumenera_Data/StreamingAssets/data/localized/en/text/`；无需 Mod 加载器。
- 卸载：恢复安装前备份；没有备份时，在 Steam 客户端执行“验证游戏文件完整性”。
- 本地校验：2026-08-22 生成 v1.1 ZIP（6,692,330 字节，SHA-256：`DA35BCB9B1E5CCC5BA0D3DEA7D5671818B0BA038C9B9A64DA17E0C0E20216641`），共 2,253 个条目（2,250 个载荷文件及根目录的 `补丁说明.txt`、`PATCH_MANIFEST.json`、`SHA256SUMS.txt`）；全部载荷 SHA-256 与清单一致，说明文件为 UTF-8 BOM，且不含可执行文件。载荷先复制至 `Dispatch/Files/` 并按游戏根目录路径压缩。
- 验证：已在 Steam Windows v1.1.0 实测启动、主菜单、性别选择与首段剧情，中文显示正常。
- 更新日志：v1.1 根据术语表完成全量重新翻译与术语校准，修复运行时标签和文本布局；说明书保留 `v1.0：首次发布` 记录。
- 百度网盘：`/Hanhua/torment-tides-of-numenera/torment-tides-of-numenera_子非鱼汉化1.1.zip`（上传成功，fs_id：`456699135704108`）；按发布规则已删除同目录旧版 v1.0 ZIP，未影响其他文件。
- 已知问题：标题 Logo 仍为英文；本补丁为 AI 辅助汉化，尚未逐条人工润色，少量超长文本可能需要后续优化。

## 已知问题

- 2026-10-20 扩大审计又确认3条待修复问题：第21317条正式对白仍为英文，第10679、17527条混入模型翻译解释。缓存证明存在“已润色但照抄英文”和“自然语言被排除”的不同成因。详见 `TranslateFiles/reports/leakage_diagnosis_20261020.md`；1,052条英文筛选候选不是漏翻总数，仍需分类审查。

- 当前方案占用英语语言槽，游戏内不再提供原英文文本；需要英文时从上述 ZIP 恢复。
- Steam“验证游戏文件完整性”或游戏更新可能还原英文字符串表；发生后重新运行回填脚本并部署覆盖包即可。
- 译文由 AINiee 批量生成，专名与文风可能存在少量不一致；已完成结构、占位符和首屏实机验证，但未逐条人工润色全部 70,163 条。
- 2026-10-20 修复后仍有 1,760 条与源文相同，包含运行时标记、编辑/调试占位、虚构语言、赞助者姓名等；不能把“与源文相同”一概视为无需翻译。长英文初筛见 `TranslateFiles/reports/unchanged_english_candidates.json`（修复前快照，含本次已修复项）；未对全部剧情开展逐条实机巡检，不保证全游戏无漏翻。
- 标题 Logo 属于图片资源，仍显示英文，不影响菜单和正文汉化。

## 版本记录
- 2026-10-20 - 根据截图补译 29 条文本、修复 3 条教程说明的自动缩字，部署并完成教程弹窗实机对比；此次为本地修复，既有 v1.1 发布 ZIP 未更新
- 2026-08-18 - 初始化汉化项目工作区（start-translate skill）
- 2026-08-18 - 补充 Steam 基本资料、本地 Unity Mono 技术线索与文本提取候选位置
- 2026-08-18 - 从英文 `.stringtable` 提取并校验 70,163 条唯一原文
- 2026-08-18 - 完成 AINiee 翻译准备、占位符人工复核与术语建议
- 2026-08-19 - 完成 70,163 条译文校验，补译正式英文残留并修复颜色标签
- 2026-08-19 - 生成并部署中文字符串表覆盖包；完成主菜单、加载、角色选择与首段剧情实机验证
- 2026-08-19 - 生成并校验 v1.0 对外补丁，上传至百度网盘
- 2026-08-20 - 重排补丁说明书为玩家阅读版，重新校验并覆盖更新 v1.0 发布文件
- 2026-08-22 - 从术语校准译文重建并部署中文字符串表，完成主菜单与首段剧情实机验证
- 2026-08-22 - 生成并校验 v1.1 对外补丁，替换百度网盘中的旧版 v1.0 发布文件
- 2026-08-22 - 导入术语校准后的全量译文，完成格式与运行时标记复检
