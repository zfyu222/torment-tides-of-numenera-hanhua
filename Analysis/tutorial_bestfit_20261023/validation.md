# 教程中文自动缩字修复（2026-10-23）

最终采用程序显示修复，正式 CSV、措辞、字符串表资源均未改动；临时的资源换行版已按哈希恢复。补丁副本在 `repack/tutorial_bestfit_20261023/WIN/TidesOfNumenera_Data/Managed/Assembly-CSharp.dll`，原版程序集在 `backups/tutorial_bestfit_20261023/Assembly-CSharp.dll`。

## 实测

使用游戏原生 TutorialMessageWindow，临时从启动阶段调用，1920×1080；不操作存档。原英文 ID1403：字号22、7行、正文高338；当前中文：BestFit=true 时字号7、正文高48；中文修复：BestFit=false，实际样式字号44、6行、正文高290。图标较多的 ID1433 同样正常显示。这里的字号/尺寸是控件局部单位，不是屏幕像素。

同版预制体没有 ScrollRect。原英文会自然撑高，未出现滚动条；当前中文的自动缩字与高度布局相互作用导致极小字。关闭中文教程自动缩字，保留自动换行并允许纵向布局伸展后，已有 ContentSizeFitter 就能获得足够的正文高度。无需新增滚动组件。

目视检查 chinese_baseline.png、chinese_fixed.png、skills_fixed.png，整段文本、图标及底部按钮均在窗口内，无可见缺字或裁切。自动断行仍可能把标点留在行首，这是引擎现有中文断行效果，本次没有改译文去调整标点或拆句。

## 修改范围与恢复

Cecil 构建器只在 MessageWindow.SetMessage 两个重载开头加入检查：必须为 TutorialMessageWindow 实例且正文包含 CJK，才关闭 Text.resizeTextForBestFit，并将纵向溢出设为 Overflow。教程本来就有 VerticalLayoutGroup/ContentSizeFitter 自动高度布局。全部45,469个方法逐一核对：只有这两个入口增加17条IL指令，原指令和分支目标保留，无新增程序集依赖；英文新窗口和其他 UI 不走修改分支。

原 DLL SHA-256：677cb9884b3adc18a65005d37a55784164821f484f970339cd15297105686664。
最终补丁 SHA-256：fdc889090036407c7625cb847e2ebc9827cd6bbe47ae6e50ac2461cf00056b88。
安装/恢复脚本：`Analysis/deploy_tutorial_bestfit.py install|restore`，要求游戏退出、源版本匹配、备份通过验证。恢复命令使用项目 Python 解释器运行此脚本的 restore 操作。

## 验证边界

截图来自带临时启动入口的受控实机测试，最终安装的干净程序集不含测试入口或测试DLL。比较了真实预制体和原文字段，但没有走完整物品栏剧情触发流程，也没有执行存读档、物理手柄及多分辨率回归；不把此次测试当成全游戏验收或发布许可。测试入口的第一轮未正确注销临时窗口，导致测试堆栈异常；改为游戏原生 Hide 后第二轮四组测试完成。测试进程退出时曾发生清理竞态，已人工按哈希恢复原版并移除测试DLL，清理脚本也已修正，之后才安装不含测试入口的最终补丁。

程序补丁只处理显示逻辑，主要剩余风险为未测分辨率下窗口越界、其他极端长教程的布局问题；仍保留一键恢复。后续发布需将此 DLL 与文字载荷一并测试、打包。既有 v1.1 ZIP 未更新。
