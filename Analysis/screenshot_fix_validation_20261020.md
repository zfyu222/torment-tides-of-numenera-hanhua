# 2026-10-20 截图反馈定向修复

## 结论

原译稿中的长中文段落在教程正文控件中被压缩。给同一正文加入适当换行后，控件获得更高的正文区域，并提高自动适配字号。正式修复仅修改 CSV 与 XML 字符串表。

| 样本 | 原控件高度 | 修复后高度 | 原实际字号 | 修复后字号 | 行数 |
|---|---:|---:|---:|---:|---|
| 努力，GUI 1399 | 64 | 146 | 14 | 22 | 2→3 |
| 物品栏装备，GUI 1425 | 24 | 146 | 11 | 22 | 1→3 |

同次实机测试，3840×2160 桌面，全屏游戏。上述为游戏控件的局部尺寸和 `TextGenerator.fontSizeUsedForBestFit`，不是截图缩放后的屏幕像素。正文为 `Candlelight.UI.HyperText`，配置字号46、Best Fit=true、horizontalOverflow=Wrap，正文宽度1468。原文和修复文本均在同一游戏教程 prefab 中显示，目视确认文字、鼠标图标、继续按钮完整，未出现相互遮挡。

## 方法与证据

- 从游戏当前 `Assembly-CSharp.dll` 复制分析输入，SHA-256：`677CB9884B3ADC18A65005D37A55784164821F484F970339CD15297105686664`。
- REA `inspect_managed_members` 读取托管成员与调用证据，evidence ID：`ev_a57b44315191e37e360f0c71709752c63e4144a0610827ae4aafd50fb4ea7f4d`；使用其托管静态分析功能，此步骤没有原生地址补丁。
- dnSpy.Console 反编译 `TutorialManager.DoShowTutorial`、`MessageWindow.SetMessage` 和 `HyperText.GetGenerationSettings`，确认真实教程入口与字体生成设置。源码输出及输入副本仅留本地，不入库。
- `TutorialLayoutProbe.cs` 是临时实机测试组件；`ProbeHook.cs` 用 Mono.Cecil 在分析副本的主菜单 Start 中加入测试入口。依次展示修复前后两条教程，并读取原游戏控件指标；没有改写字体设置或模拟渲染。测试标题用于区分样本，正式游戏不包含这些标题。
- 测试结束关闭游戏，恢复输入 DLL，校验其哈希一致，并删除游戏目录中的 `TutorialLayoutProbe.dll`。部署报告确认 `managed_dll_restored=true`、`probe_removed=true`。
- 正式 CSV 差异仅32条，29条补译、3条显示换行。7个字符串表更新；2,251个本地化文件逐个比对项目输出。

## 验证边界

- 已实测上述两条教程的实际 prefab 和渲染结果；测试入口从主菜单调用，没有复现库存或努力任务的剧情触发过程，也没有操作或覆盖玩家存档。
- 手柄说明 GUI 1423 使用相同换行修正，但没有接入手柄实测。
- 截图中英文段落已在正式 CSV 和 `x1131_falling.stringtable` 中补译并核对；未重新走完该剧情选择支线。其余补译同样完成文本与回填校验，未逐条实机触发。
- 本次只定向修复反馈及确认的正式英文残留；测试节点、编辑占位、虚构语言和名单保留，不把机械扫描作为全文语义或实机验收。
- 未生成或发布新版 ZIP；`Dispatch` 下 v1.1 仍是旧发布产物。
