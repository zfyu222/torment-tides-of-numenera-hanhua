# Torment 图片文字分支

已获用户授权启用（2026-10-27）。常规文本 CSV 和翻译数据库不在本分支的初始化范围。

1. `tools/TextureExport` 通过 UABEA 的 AssetsTools.NET 和 AssetRipper 的 Unity 5.x Crunch 解压逐文件读取游戏 Texture2D。来源、Path ID、尺寸、纹理格式、流偏移及资源文件哈希随PNG保留，不写游戏文件。只读导出结果见 `extraction_20261027.json`。
2. `tools/calibrate.py` 生成分层校准联系表供当前对话 Agent 实际看图。字体图集是分散字形，按视觉复核保留原样，不把它们标成“确认无字”或完整词句。
3. `tools/prepare_scan.py` 绑定完成的导出，保留8张字体图集的排除理由，以硬链接建立其余图片的独立只读输入。共用 `Tools/image_text/cli.py inventory` 按可见像素去重，重复来源全保留。`policy_20261027.json` 的文件名线索只增加复核优先级，不认定存在文字；未校准的字体族保持unknown。
   初始扫描中又发现8个SDF字体图集，逐张看图确认后以 `tools/scope_font_atlases.py` 从完整父清单建立哈希绑定子范围：父清单、原扫描保留；同像素、同模型配置的有效缓存复用；共用扫描器仍在使用前校验像素。对应 `font_scope_20261027.json`，不要把排除的字形图集标记为无字或可翻译正文。
4. 共用三级流程：全量GPU medium OCR退出后，Qwen只看难例和分层抽查，再由当前对话 Agent 实际看图裁决和验收。正式图片原文和mapping须通过共同导出门槛，不能把检测高分、模型一致、无字预测或候选队列当成视觉确认。
5. 图片原文进入 `TranslateFiles/image-text/` 隔离子工程，按已选择的 API 路线和配置优先级完成正式翻译与审校。正式译文及哈希验证通过前不绘制或安装中文贴图。构建资源后另做视觉检查及Unity引擎适配；不自动发布补丁。

两个独立标题图的Unity资源副本回填试验见 `engine_smoke_report_20261027.json`。之后对图集2167及两个独立标题图做同批原图回填试验，整张图集回读像素一致，其余资源对象逐字节不变，见 `engine_atlas_smoke_report_20261027.json`。它们不能当成译文回填或实机通过；正式修改图集仍须验证标题以外的像素和切片。

## 复现资源导出

在工作区根目录运行，`<新导出目录>`必须不存在；不要覆盖已有快照：

```powershell
dotnet build Projects/torment-tides-of-numenera/ImageText/tools/TextureExport/TextureExport.csproj -c Release -p:UabeaDir=D:/StaticHanHua/Tools/UABEA/UABEAvalonia/bin/Release/net8.0 -p:RipperDir=D:/StaticHanHua/Tools/AssetRipper-CLI/artifacts/bin/AssetRipper.Tools.ExportRunner/Release/net10.0
dotnet Projects/torment-tides-of-numenera/ImageText/tools/TextureExport/bin/Release/net10.0/TextureExport.dll Projects/torment-tides-of-numenera/Game/WIN/TidesOfNumenera_Data <新导出目录> Tools/UABEA/UABEAvalonia/bin/Release/net8.0/classdata.tpk
```

大图、输入快照、缓存、模型回复和编译产物不入库。`extraction_20261027.json`及项目README记录实际阶段，不把资源导出视为图片汉化完成；后续查看工作目录中的真实扫描、裁决与正式输出。
