# 原版文本问题记录

已对照 `backups/localized_en_original_20260819_085840.zip` 核实。以下是原始资源自身的问题，不据猜测补写剧情或数值。

| 原始资源 | 原文问题 | 本次处理 |
|---|---|---|
| `a_sagus/a2201_jernaugh.stringtable` ID 91 | `Who wo after all my expenses are paid` 是不完整句子 | 删除无意义英文残片 `wo`，用“谁……”保留截断，翻译其余可确定内容，不猜补缺失句子 |
| `c_bloom/c4221_second_patrol_01.stringtable` ID 4 | 先称同伴已死，紧接着说不知他还能撑多久 | 保留原句信息；没有足够剧情证据将“死去”擅改成“濒死” |
| `si_meres/mere_ri1_endlessbattlemere.stringtable` ID 45 | `East` 后出现 `! point`，疑似标点/数字笔误 | 保留感叹号，不擅自猜成数字 1 |
| `x_labyrinth/x1131_large_door.stringtable` ID 48 | `It does move, not even a little bit.` 前后矛盾 | 按明确的 `not even a little bit` 和用力拉仍未动的叙述译为完全未动，保留末尾空格 |

另外，ID 108 的女性分支残留 `help him, guide him`、ID 221 的女性分支末段残留 `brother`，已对照同 ID 男女变体并按女性分支修正；实际修改和审校归属见 `direct_three_semantic_fixes_20261023.json`。

人名复合词/简称异写已定向统一：Orth 简称与全名“奥思·方”保持一致，Rhin 的相关装备名统一“莱茵”，Neng 的地点/属性名称沿用人物主译“能”。冻结术语表未全局改写，具体记录保留有依据的语境例外与修订历史。
