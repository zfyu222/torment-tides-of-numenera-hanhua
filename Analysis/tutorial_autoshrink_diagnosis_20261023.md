# 2026-10-23 新截图：教程正文缩字诊断

- 截图对应 `ttongui.stringtable` ID 1403（秘器及秘器上限），不是之前调整的 1399/1423/1425。ID1403 已完整翻译，但中文长段仍被压入很矮的正文区域。
- 原版英文也包含同样的两段内容（以字面 `\n\n` 分段），没有独立的英文教程窗口。`TutorialManager.CypherInventoryMessage` 使用 ID1403，最终走同一 `DoShowTutorial` → `TutorialMessageWindow` → `MessageWindow.SetMessage`。
- 已有同版本反编译：MessageWindow.SetMessage 只设置正文和按钮文字，不按中文另建控件。HyperText.GetGenerationSettings 将 resizeTextForBestFit/min/max、换行和溢出设置交给 Unity TextGenerator；preferredHeight 也通过 TextGenerator 计算。ForceSize 存在按目标文字 preferredHeight 调整 RectTransform 高度的通用逻辑，但未重新读取该 prefab 的组件绑定，不能据此断言本次就是 ForceSize。
- 历史实测（2026-10-20，同 DLL 哈希）：教程正文配置字号46，BestFit=true、Wrap，正文宽1468；单行正文高24时实际字号11，插入显示换行后高146、字号22。此为历史同类控件证据，不是 ID1403 本次的动态测量。
- 当前推断：正文高度分配/自动缩字与连续中文断行相互作用，长中文未撑开足够高度，Best Fit 继续缩小字体；标题和按钮独立，故仍正常。尚未同场景实测英文，不能声称英文实际字号或完全无此问题。截图和历史证据不足以把根因归结为整个面板的 scale。

## 解决方向

优先针对教程正文公共控件修复：以明确的可读字号计算固定宽度下的真实换行高度，再扩展正文和外框；限制窗口在屏幕可用区域内，极长教程增加滚动或分页。需要覆盖鼠标与手柄输入、教程偏移坐标，以及多种分辨率。只关自动缩字或抬最低字号会有裁切/越界风险；只放大整个窗口会连按钮一起变大。逐条加换行只是临时文本排版办法，不能覆盖后续所有教程。

## 边界

本次仅诊断并提出公共布局修复方案。游戏当前运行中，未替换游戏文件、未关闭游戏、未修改存档；新方案尚未实现或实机验证。新 REA inspect_managed_members 对7430656字节同哈希程序集返回 metadata representation 64MiB budget限制（ev_276a6421e45178c7329cafbd7ef592d4cc99aadd6fc9abad0a23c4ac795175d5），本次以既有同哈希反编译和历史证据作静态核对，不将失败查询当作新方法体证据。
