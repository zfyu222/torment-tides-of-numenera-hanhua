# 术语审校已完成部分的质量检查

- 已完成任务：1092
- 覆盖条目：12336（characters/terms/non_translate）
- 使用独立校验器重新验收：**全部通过**
- 译名修订：703 处；无实质变化/仅改分类等：208 处
- 隔离待定（quarantine）：196 处；新增条目（additions）：6 处
- 已确认 audit findings：680
- 四维证据单元格共 49344 个，其中过短（<12 字）928 个（1.9%）
- 理由文本重复组：721 组

## 重复最多的审校理由（前 5）

- ×12：结论：保留原文不译，归入 non_translate 正确；'Ability' 在此为占位名组成部分，不按 psychic ability 套译。
- ×12：核对为 non_translate 表中的能力编号占位或内部标识，应保持原文；不建立译名，也不套用 e13 的“灵能”。
- ×12：该条为占位式能力标识，不构成可译界面文本；维持 non_translate 分类，不生成译名。
- ×12：确认该条为 abilities.stringtable 的编号占位文本，non_translate 分类正确；保留原文，不建立可译术语。
- ×12：确认为内部键名，应保留原文且不进入译名表；分类正确。

## 译名修订样例

- `characters:42`：伊尼费尔 → **伊尼菲尔**（66649 的 near/dear/fear/sincere 押韵表明 Inifere 末音近 fear；18093、20355 等直接对话亦用“伊尼菲尔”。统一为“伊尼菲尔”，不）
- `characters:62`：监工伊恩 → **监督者伊恩**（将 Overseer Yeen 统一为“监督者伊恩”，避免“监工”被理解为工头，也不采用“伊恩总督”；与同一人物既有译名保持一致。）
- `characters:95`：卡莉丝提吉 → **卡莉丝蒂吉们**（按 e4 的标准名“卡莉丝蒂吉”统一词干，并按 Callisteges 的复数语境加“们”；候选“卡莉丝提吉/卡利斯特吉们”分别存在词干或音译不一致。）
- `characters:96`：退役上尉兰昌·提比尔 → **退役上尉兰昌·泰比尔**（e5 已定 Tybir 为“泰比尔”，本条应统一为“退役上尉兰昌·泰比尔”，保留军衔与退役身份。）
- `characters:116`：玛德莉娅 → **玛德莉亚**（与 related_terms 中 e14“Madelia Glittering/玛德莉亚·格利特林”的名部统一，避免同一人物两种写法。）
- `characters:147`：第一弃子 → **第一弃民**（统一 First Castoff 为“第一弃民”，与 Last Castoff=“最后的弃民”的 castoff 对应；“弃子”等候选不采用为标准名。）
- `characters:163`：富尔瑟姆的信使 → **富尔索姆的信使**（Fulsome 在 e4 统一为“富尔索姆”，messenger 应保持同一核心名；原“富尔瑟姆”不一致。）
- `characters:167`：因比图 → **伊姆比图**（Imbitu 按 Im-bu-tu 音节规范对译为「伊姆比图」，暂定译名「因比图」丢失 -m 尾音；与男性角色提案批次统一，弃用「因比图」。）
- `characters:175`：跛脚工头 → **跛足工头**（Crippled Foreman 是同一角色的描述性称号；按跨批提示统一为“跛足工头”，避免与 Under-Foreman 的“地下工头”混同。）
- `characters:177`：下层工头 → **地下工头**（Under-Foreman 为具体构造体称号，不取“副工头/下层工头”的等级误读；与 e5 的 the Under-Foreman 统一为“地下工头”。）

## 条目审校样例（原文 → 采用译名）

- `characters:13`：**Aligern** → **阿利格恩**
  - 理由：Aligern 为男性角色名，出现于对话称呼、叙述与角色标签；标准译名确定为“阿利格恩”。候选中的“阿利根”“阿里格恩”“艾利格恩”“阿里根”“阿利杰恩”均为音译分歧，无证据显示多义，不分别保留；10958 中的 {ALIGERN} 为占位标签，不据此另立角色名译法。
- `characters:7`：**Changing God** → **变易之神**
  - 理由：确认 e1 的 Changing God 为同一神祇专名，标准译名定为“变易之神”；characters 表及男性分类与原文称谓和上下文相符，跨批变体仅作只读一致性核对。
- `characters:15`：**Specter** → **幽魂**
  - 理由：Specter 指变易之神相关的幽灵式男性角色；保留“幽魂”作为标准角色名，分类 characters 合理；The Specter 同指共用译名，f1 不构成冲突。无需编辑。
- `characters:16`：**Sorrow** → **悲伤**
  - 理由：确认 Sorrow 为追猎者 The Sorrow 的省略冠词专名变体，沿用标准译名“悲伤”；表 characters 与性别“其他”适合该无明确性别角色，未见需编辑项。
- `characters:9`：**First** → **第一者**
  - 理由：确认“First/the First”均指变易之神的第一位弃民，保留头衔译名“第一者”；该角色为女性，归入 characters 而非组织。
- `characters:3`：**The First** → **第一者**
  - 理由：确认 The First 为女性角色专名，统一译作“第一者”；分类为 characters/女性，无需改动。
- `characters:14`：**Callistege** → **卡莉丝蒂吉**
  - 理由：Callistege 为女性角色名；确认统一译作“卡莉丝蒂吉”，不采用“卡莉丝特姬”“卡丽丝忒姬”等异体。
- `characters:17`：**The Specter** → **幽魂**
  - 理由：确认 The Specter 与只读关联项 e4 的 Specter 为同一角色名，仅冠词/大小写差异；保留“幽魂”、table=characters、gender=男性。

## 隔离项样例

- `characters:304`：your father 是对话中对 Changing God 的普通称谓，不是独立角色名；保留为 characters 条目会错误收录普通短语。
- `non_translate:43`：玩家可见技能判定标签被误归 non_translate；应移出非译表并译作 [听觉感知]，与 Aural Perception=听觉感知 的术语一致。
- `non_translate:103`：混合条目：方括号内为可显示叙事，需翻译；仅 {SCRIPT: Hit all mobs except user with DIsmay Fettle} 应保留原文。整条列在 non_translate 会漏译叙事，建议拆分后再入库；脚本内 
- `non_translate:289`：该条被整体归入 non_translate，但星号内为可译普通词 feeling；需移出非翻译项并按“*感觉*”处理，当前条目不宜作为非翻译项保留。
- `non_translate:316`：双冒号动作拟声可能作为叙述显示，non_translate 分类疑似错误；需人工复核并改列对白或叙述表，保留 :: 标记翻译其内容。
