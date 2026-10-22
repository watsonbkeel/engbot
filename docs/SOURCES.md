# 来源与依赖说明

本包新增源码为英语课程扩展；没有将原仓库内容伪装成已经重写或已部署。修复包已从用户提供的 Eng.zip 导入原词库；仍提供后续重新导入和锁定原仓库下载工具。

- aibot：`https://github.com/watsonbkeel/aibot`，锁定 `cd5b34c446d5134c6346f290f7513380edba84a5`。复用身体／脑端架构、中文唤醒习惯、USB设备基线与Edge/Piper路径的设计；新插件独立运行，另提供旧文本桥兼容工具。
- WordMaster_SZ：`https://github.com/watsonbkeel/WordMaster_SZ`，锁定 `4701d5bc72097c8851b180bf6025fb8b9db12ae4`。唯一正式词库来源为其`utils/fullDictionary.js`或用户提供的本地同类文件；不编造教材单元。
- 原词库Git blob：`ea9b65ea1c1ae6e4b871bbd27f8d46796097d8cc`。联网导入验证此值，本地导入记录实际值。
- DeepSeek请求格式：`https://api-docs.deepseek.com/api/create-chat-completion/` 与 `https://api-docs.deepseek.com/guides/thinking_mode/`。运行时模型 ID 以你实际接口为准；平台关闭思考，自带模型按保存的 thinking 显式发送。
- Vosk模型：`https://alphacephei.com/vosk/models`。模型权重需另下，遵守各模型自己的许可证；默认英文small-en-us-0.15、中文small-cn-0.22。
- 微信网络接口参考：`https://developers.weixin.qq.com/miniprogram/dev/framework/ability/network.html`。真实AppID、成员权限和手机网络在你的账号中验证；本环境未运行微信开发者工具。

上游下载后的LICENSE文件应随原项目副本保留。小程序合并工具会保留原工程的LICENSE；本包LICENSE仅覆盖本次新增源码。第三方依赖和模型遵从各自许可证。

## 本次预生成听力

45 篇听力文字为本项目新写的分级故事／对话，不是 WordMaster 教材词库，也不冒充教材配套音频。原稿和文件摘要见 `data/listening/curated.json`、`index.json`。

实际音频使用 Piper 1.3.0 与 `en_US-ljspeech-medium` 离线生成，再按学段调整语速、编码 MP3；构建来源和摘要见 `data/listening/build-provenance.json`。模型本身不随 ZIP 分发，重新生成时由使用者准备。

- Piper 项目：[OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl)。
- 音色说明：[en_US-ljspeech-medium MODEL_CARD](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/medium/MODEL_CARD)。
- 数据来源：[LJ Speech Dataset](https://keithito.com/LJ-Speech-Dataset/)，发布页标注为 public domain。

Edge TTS 生成路径也保留在工具中，但本次构建环境的 Edge WebSocket 握手失败；交付音频没有伪标为 Edge 生成。无静音填充或重复片段凑时长。
