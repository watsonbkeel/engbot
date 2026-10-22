# 数据来源与部署

本次修复包已导入用户提供的原 WordMaster_SZ `utils/fullDictionary.js.bak`，保存为 `fullDictionary.js` 和结构化 `dictionary.json`。共有 3,919 条、24 个年级学期组合，其中小学 733 条；原编号、词义及年级范围保留。

来源、Git blob 与 SHA256 见 `dictionary-source.json`。当前原文件 Git blob 为 `ea9b65ea1c1ae6e4b871bbd27f8d46796097d8cc`，与仓库锁定文件一致。

后续换成自己的新版原词库：

```bash
python3 scripts/prepare_sources.py --dictionary /本地/utils/fullDictionary.js
```

导入器只解析数据，不执行 JavaScript，不把测试词表作为正式数据。原词库没有教材单元字段，正整数 unit 仅代表原顺序每 10 词一组。

`listening/` 是独立听力素材。来源、生成方法、音频清单及完整性检查见 `docs/LISTENING.md`。播放素材不调用实时模型，不写口语掌握记录。
