# 翻译操作记录

- 工作流：custom
- 自定义执行后端：api
- 原文：项目根目录 `torment-tides-of-numenera_text.csv`
- 正式译文：项目根目录 `torment-tides-of-numenera_text_translated.csv`
- 中间产物：`TranslateFiles/`

由 game-translate 技能调用流程程序；正文前完成全文术语整理及冻结。
试译：固定随机样本 → pilot_translate → pilot-report → 主 AI pilot-decide；按需 pilot-retry。
试译用于校准流程和风格，不要求逐句零错误；正式译文仍须完整独立审校和导出验收。

## 2026-10-21 交接

- 所选API：本机公共配置中的 `deepseek-v4.1-flash`，密钥不入库。
- 术语提取已接收453个批次，尚未完成；没有新正式译文或试译质量结论。
- 当前接口返回“该分组与模型无可用转发通道”，需恢复通道或由用户指定替代服务/模型。保留已完成产物，不重启全文、不手工补造术语结果。
- 另有术语引用不匹配、推理文字占满输出或回复截断等失败，恢复服务后应先处理现存交接和已有尝试上限，不能单纯重新发送全部任务。
- 正式使用 `config/workflow.json` 内保护规则；`placeholder_report.md` 为初始化的宽泛候选扫描，不能直接把其所有方括号/尖括号候选当禁翻项。可见的心灵对白、自然括号文本必须正常处理。
- 当前游戏与项目根目录正式译文保持上次修复版，待新译完成完整验收后才替换。
