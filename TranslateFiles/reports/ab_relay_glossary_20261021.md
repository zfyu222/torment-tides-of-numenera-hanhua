# 术语审校双通道 A/B（acy7 中转站 vs DeepSeek 官方）

日期：2026-10-21T16:44:22+0800

## 配置
- `acy7`：`https://acy7.com/v1` / `deepseek-v4.1-flash` / 思考=True / 流式=True
- `deepseek`：`https://api.deepseek.com` / `deepseek-chat` / 思考=True / 流式=True

## 方法与口径

- 输入：直接复用项目里已发出的真实 `input.md` 术语审校任务包，两通道字节相同，未做任何改写；未写入项目数据库，未占用任务、租约或尝试次数，未改动正式译稿。
- 判定：完全复用生产验收链路（`parse_response` → `canonical_api_result` → `submit_in_transaction` 的 glossary_review 检查），首个回复不通过即记为首轮返工。
- 质量：把每个术语的最终译名（含 edits 补丁）与项目已验收的正式结果逐条对照，统计一致率并列出差异。

## 结果

| 通道 | 首轮通过 | 平均耗时(s) | 输入Token | 输出Token | 与正式译名一致 |
|------|----------|-------------|-----------|-----------|----------------|
| acy7 | 5/8 | 52.3 | 57071 | 60503 | 37/40 |
| deepseek | 4/8 | 45.5 | 57071 | 69736 | 34/37 |

## 逐批结果

| 批次 | 条目 | acy7 | deepseek |
|------|------|------|----------|
| `00001-eaf0daf2-s2eaa0a99` | 1 | 通过 | 通过 |
| `00068-4e9e19e8-sceaf9711` | 3 | 通过 | 返工：entry_review: Glossary review requires c |
| `00174-dfb23e2c` | 12 | 通过 | 通过 |
| `00237-5b5a1bd7` | 12 | 通过 | 通过 |
| `00001-eaf0daf2-s4cc44f89` | 1 | 返工：entry_review: Glossary review requires c | 返工：transport_binding: Unknown or read-only  |
| `00094-a5240955-s0df7953d` | 1 | 返工：transport_binding: Unknown or read-only  | 返工：entry_review: Glossary review requires c |
| `00199-91c3a060` | 12 | 返工：transport_binding: Review check pair req | 返工：transport_binding: Review check pair req |
| `00265-e57ff43a` | 12 | 通过 | 通过 |

## 返工原因

**acy7**
- `00001-eaf0daf2-s4cc44f89`：entry_review: Glossary review requires cited source context and specific reason; ref=characters:7; available_evidence_rows=[270, 595, 1013, 1093, 1094, 1528, 2614, 7506]; invalid_or_unprovided_rows=[1211, 1215, 5184, 9737, 12006, 22612, 38672, 54374, 57702]; excerpt_matches_cited_rows=[1094]; reason_missing=False. source_excerpt must be one exact contiguous excerpt from a cited, provided source; do not join par
- `00094-a5240955-s0df7953d`：transport_binding: Unknown or read-only glossary entry reference 'e2'; assigned: ['e1']
- `00199-91c3a060`：transport_binding: Review check pair requires exactly [status, evidence]: checks

**deepseek**
- `00068-4e9e19e8-sceaf9711`：entry_review: Glossary review requires cited source context and specific reason; ref=terms:58; available_evidence_rows=[1119, 2761, 6783, 13382, 62669, 62693]; invalid_or_unprovided_rows=[]; excerpt_matches_cited_rows=[]; reason_missing=False. source_excerpt must be one exact contiguous excerpt from a cited, provided source; do not join paraphrases or insert ellipses.
- `00001-eaf0daf2-s4cc44f89`：transport_binding: Unknown or read-only glossary entry reference 'e2'; assigned: ['e1']
- `00094-a5240955-s0df7953d`：entry_review: Glossary review requires cited source context and specific reason; ref=terms:319; available_evidence_rows=[4664, 6630, 6725, 13585]; invalid_or_unprovided_rows=[3473]; excerpt_matches_cited_rows=[4664]; reason_missing=False. source_excerpt must be one exact contiguous excerpt from a cited, provided source; do not join paraphrases or insert ellipses.
- `00199-91c3a060`：transport_binding: Review check pair requires exactly [status, evidence]: source

## 译名差异（相对项目已验收结果）

**deepseek / `00237-5b5a1bd7`**
- `terms:2954`：正式“散播恐慌” → 本通道“散播沮丧”

**acy7 / `00265-e57ff43a`**
- `terms:3467`：正式“工头的孩子们” → 本通道“工头之子”
- `terms:3474`：正式“泰比尔的斗篷” → 本通道“泰比尔斗篷”
- `terms:3477`：正式“卡莉丝蒂吉的连衣裙” → 本通道“卡莉丝缇吉的连衣裙”

**deepseek / `00265-e57ff43a`**
- `terms:3467`：正式“工头的孩子们” → 本通道“工头之子”
- `terms:3474`：正式“泰比尔的斗篷” → 本通道“泰比尔斗篷”

