# Torment: Tides of Numenera AINiee 翻译操作指南

> 本文档用于将 `torment-tides-of-numenera_text.csv` 从英语翻译为简体中文。源文件含大量多行剧情文本和运行时标记，务必完成下列防护设置后再开始翻译。

## 一、源文件与目标

- 原文文件：`torment-tides-of-numenera_text.csv`
- 文本数量：70,163 条逻辑记录（103,608 个物理行）
- 源语言：英语
- 目标语言：简体中文
- 目标文件名：`torment-tides-of-numenera_text_translated.csv`
- 格式：UTF-8、无表头、标准单列 CSV；多行字段必须继续使用 CSV 引号转义

不要使用“按物理行逐行处理”的普通文本工具拆分本文件，否则多段落文本会错位。

## 二、翻译前必做：占位符防护

检测与人工复核结果详见 `placeholder_report.md`：

| 类型 | 出现次数 | 示例 |
|------|---------:|------|
| 方括号运行时标记/编辑标记 | 3,796 | `[Global: TimeSpent]` `[Color: Damage]` `[/Color]` `[Damage]` |
| 数字格式化占位符 | 434 | `{0}` `{1}` `{1:0.00}` |
| 命名花括号标记 | 945 | `{MONEY}` `{LOOT}` `{pause}` `{female}` |
| 实际尖括号渲染标签 | 74 | `<quad class="action">` `<a name="test">` `</a>` |
| printf 格式符 | 1 | `%%` |
| 字面转义序列 | 738 | `\n` `\t` |

注意：`<No,>`、`<Out!>`、`<What do you want?>` 等尖括号文本是玩家可见的心灵对白，需要翻译，不能使用宽泛的 `<...>` 禁翻规则。

### 第 1 步：导入禁翻表

1. 启动 AINiee：

   ```powershell
   cd D:\StaticHanHua\Tools\AINiee
   .\venv\Scripts\python.exe AiNiee.py
   ```

2. 打开左侧导航“禁翻表”，打开顶部开关。
3. 点击“导入”，选择本项目的 `ainiee_exclusion_list.json`。
4. 点击工具栏“保存”。

导入后应看到以下规则：

| 备注 | 正则 |
|------|------|
| 方括号标记 | `\[[^\[\]\n]{1,60}\]` |
| .NET/格式化占位符 | `\{\d+(:[^{}\n]*)?\}` |
| 花括号命名变量/演出提示 | `\{[A-Za-z_][A-Za-z0-9_]*(?:=[^{}\n]+)?\}` |
| 实际尖括号渲染标签 | `(?:<quad\s+class="[A-Za-z0-9_-]+">\|</?a(?:\s+name="[^"]+")?>)` |
| printf 格式符 | `%(?:\d+\$)?[0-9.+#-]*[sdfoxXeEfgGcr%]` |
| 字面转义序列 | `\\[nrt]` |

### 第 2 步：开启自动处理文本代码段

进入“翻译设置”，打开“自动处理文本代码段”。该功能会在译前把禁翻表命中的内容临时替换为 `[P0]`、`[P1]`，译后再还原，是防止变量和标签损坏的必要设置。

### 第 3 步：配置术语表

以下为首轮建议，正式开跑前可按你的译名偏好调整：

| 原文 | 建议译文 | 备注 |
|------|----------|------|
| Numenera | 努曼内拉 | 世界观名称 |
| Ninth World | 第九世界 | 世界名称 |
| Changing God | 变易之神 | 核心角色称号，暂定 |
| Castoff | 遗弃者 | 核心身份称谓，暂定 |
| the Sorrow / Sorrow | 悲伤 | 追猎者名称，作专名时统一 |
| Tide / Tides | 潮汐 | 核心设定 |
| Crisis | 危机 | 战斗/场景系统术语 |
| Effort | 努力 | 规则系统术语 |
| Might | 力量 | 属性名 |
| Speed | 速度 | 属性名 |
| Intellect | 智力 | 属性名 |
| shins | 辛币 | 货币名，暂定 |

“变易之神”“遗弃者”“辛币”为项目暂定译名。应在全文翻译前确定，一旦采用便不要中途改名。

### 第 4 步：附加提示词

在提示词设置中追加以下内容：

```text
这是叙事型科幻奇幻 CRPG《Torment: Tides of Numenera》的游戏文本。请翻译为自然、凝练、具有文学感的简体中文，并保持人物口吻与上下文一致。所有方括号标记、数字或命名花括号变量、printf 格式符、字面转义序列以及真正的渲染标签必须原样保留，不得增删、翻译或转换全半角。尖括号包裹的心灵对白（例如 <No,>、<Out!>）属于玩家可见文本，必须翻译其内部文字并保留尖括号。保留星号强调、段落结构和原有标点语义。不要解释，不要添加原文没有的内容。

###以textarea标签输出译文
<textarea>
1.{target_language}文本
</textarea>
```

## 三、在 AINiee 中翻译

1. 在“接口管理”中添加并激活 API；可使用 DeepSeek 等适合长篇游戏文本的模型。
2. 将 `torment-tides-of-numenera_text.csv` 拖入输入区域。
3. 设置源语言“英语”、目标语言“简体中文”。
4. 确认禁翻表和“自动处理文本代码段”均已开启。
5. 建议先翻译 100～300 条进行试跑，检查术语、尖括号心灵对白和多段落 CSV 是否正确，再开始全量任务。
6. 完成后将结果保存为 `torment-tides-of-numenera_text_translated.csv`，放回本项目根目录。

## 四、翻译完成后的校验

将译文文件放入项目目录后运行：

```powershell
python "D:\StaticHanHua\.agents\skills\game-translate\scripts\validate_translation.py" "D:\StaticHanHua\Projects\torment-tides-of-numenera\torment-tides-of-numenera_text.csv" "D:\StaticHanHua\Projects\torment-tides-of-numenera\torment-tides-of-numenera_text_translated.csv" --fix --fix-newlines
```

校验内容包括：逻辑记录数、单列 CSV 结构、受保护标记的多重集合、括号与冒号全角化、变量名以及字面 `\n` 是否被变成真实换行。

- 退出码为 0：可以进入回填阶段。
- 生成 `need_retranslate.csv`：只重翻其中记录，合并后重新运行校验。
- 大量占位符错误：先检查禁翻表是否导入并保存，以及“自动处理文本代码段”是否开启，再重新批量翻译。

## 五、常见问题

| 症状 | 原因 | 处理 |
|------|------|------|
| `[Global: ...]` 或 `[Color: ...]` 被改写 | 禁翻表或自动代码段未启用 | 重新导入禁翻表、保存并开启自动处理 |
| `<No,>` 等仍为英文 | 错用了宽泛 `<...>` 禁翻规则 | 删除宽泛规则，重新导入本项目 JSON |
| `【...】`、全角冒号出现在变量中 | 模型全角化 | 重新翻译相关记录并运行校验 |
| 译文记录数不等于 70,163 | 多行 CSV 被按物理行拆分 | 使用 AINiee 直接读取原始 CSV，不要预拆行 |
| 字面 `\n` 变成真实换行 | 模型改写转义序列 | 使用校验命令的 `--fix-newlines` 处理 |
