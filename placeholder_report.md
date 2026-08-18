# 占位符分析报告

- 文件：`torment-tides-of-numenera_text.csv`
- 逻辑行：70163，物理行：103608

> ⚠ 本文件含 `{...}` 句型花括号（玩家选项文本，需翻译）。单词型 `{name}` 匹配已降级为人工确认，未自动加入禁翻表。

## square_bracket — 3796 次出现
- 方括号标记（变量占位符/BBCode/富文本标签，如 [Player:Name] [i] [color="red"]）
- 建议禁翻正则：`\[[^\[\]\n]{1,60}\]`
- 高频样本：
  - `[/Color]` ×322
  - `[A]` ×154
  - `[DEBUG]` ×127
  - `[Color: TooltipFormatting]` ×82
  - `[Attack]` ×63
  - `[Fettles]` ×57
  - `[B]` ×50
  - `[Damage]` ×48
  - `[Color: PositiveModifier]` ×48
  - `[FettleIcon: Debuff]` ×39
  - `[Actor Name]` ×31
  - `[FettleEffectsBasic]` ×29

## curly_format — 434 次出现
- .NET/格式化占位符（如 {0} {1:0.00}）
- 建议禁翻正则：`\{\d+(:[^{}\n]*)?\}`
- 高频样本：
  - `` ×434

## curly_named — 945 次出现 ⚠ 需人工确认
- 花括号命名变量（如 {name} {color=#ff0000} {w=wt1}）
- 本文件存在句型花括号选项文本，以下匹配**很可能是需翻译的选项**，确认是变量后才可加入禁翻表：
- 高频样本：
  - `` ×943
  - `=1` ×2

## angle_tag — 186 次出现
- 尖括号标签（HTML/XML/Unity 富文本，如 <b> </color> <Tag:1>）
- 建议禁翻正则：`</?[A-Za-z][^<>\n]{0,50}>`
- 高频样本：
  - `<quad class="action">` ×10
  - `<quad class="armor">` ×8
  - `<No,>` ×6
  - `<quad class="move">` ×6
  - `<quad class="resistance">` ×5
  - `<quad class="willpower">` ×4
  - `<quad class="mightpool">` ×4
  - `<quad class="speedpool">` ×4
  - `</a>` ×3
  - `<quad class="intellectpool">` ×3
  - `<quad class="evasion">` ×3
  - `<quad class="skillempty">` ×3

## printf — 1 次出现
- printf 格式化符（如 %s %d %.1f %1$s %%）
- 建议禁翻正则：`%(?:\d+\$)?[0-9.+#-]*[sdfoxXeEfgGcr%]`
- 高频样本：
  - `%%` ×1

## escape_seq — 738 次出现
- 字面转义序列（\n \r \t，两个字符，非真实换行）
- 建议禁翻正则：`\\[nrt]`
- 高频样本：
  - `\n` ×727
  - `\t` ×11

## 人工复核结论

- 方括号共 3,796 次。`[Color: ...]`、`[/Color]`、`[Global: ...]`、`[Control: ...]`、`[Damage]`、`[Fettles]` 等会被运行时解析或替换；对照游戏自带德/法/西/波/俄字符串表后可见这些标记在官方译文中原样保留。因此保留方括号禁翻规则。语料中同时包含 `[DEBUG]`、`[Attack]` 和自然语言方括号编辑占位，主要来自遗留测试/编辑文本，翻译阶段不改写其括号内容。
- 数字花括号 434 次（如 `{0}`）均作为格式化参数保护。
- 命名花括号 945 次（如 `{MONEY}`、`{LOOT}`、`{pause}`、`{female}`）是事件、演出或模板标记，已人工加入禁翻表。带空格的整句花括号注释不使用通用规则保护，避免误伤可能需要翻译的可见文本。
- 自动生成的宽泛尖括号规则会误匹配 `<No,>`、`<Out!>`、`<What do you want?>` 等玩家可见的心灵对白。禁翻表已收紧为仅保护实际渲染标签：`<quad class="...">` 与 `<a name="...">` / `</a>`，共 74 次；其他尖括号内英文应正常翻译并保留尖括号。
- `%%` 仅出现 1 次，按 printf 字面百分号保护；字面 `\n` / `\t` 共 738 次，必须原样保留。
