# 磨耳朵素材：交付、生成与复验

## 交付内容

`data/listening/curated.json` 包含 **45 篇分级原创文稿**：1–9 年级每级 3 篇短文、2 段对话。每篇有稳定 `id`、年级、类型、标题、完整英文文稿和相对音频路径。它们是独立的听力练习素材，不是教材原文，也不替代原 WordMaster 单词库。

交付 MP3 位于 `data/listening/g1/` 至 `g9/`，清单为 `data/listening/index.json`。每条清单还包含 ffprobe 实测的 `duration_seconds`、文件 `sha256`、真实合成引擎及语速处理记录。公共服务读取这一清单；带家长凭证的列表返回 `audio_url`，音频下载同样验权。听力播放不会写入单词学习进度。

当前交付语音使用 **Piper TTS 1.3.0，en_US-ljspeech-medium** 本地模型真实生成，经过 ffmpeg 编码为单声道 22.05 kHz / 64 kbps MP3。1–3、4–6、7–9 年级目标语速分别为每分钟 110、125、140 词。调整使用 `atempo` 改变实际语音速度，未添加静音、循环重复片段或测试替代音频。对话文稿保留说话人名称，朗读前去除行首名称；本版所有角色使用同一种英语音色。

初次生成后，独立校验曾检出两条音频与清单摘要不符；发布前以恢复模式重新生成这两条，并重新核对全量素材。交付结论以 `docs/verification/product-fixes.md` 和最终验证日志为准。

## 只读复验

需要 Python 3.11+、ffprobe；不需要联网、Edge TTS 或 Piper 模型：

```bash
python scripts/make_listening.py --verify-only
```

命令检查以下条件，任一失败返回非零状态，并给出条目 ID：

- 九个年级均至少 5 条，短文和对话各至少 2 条；ID 不重复，文件路径不得越界。
- 清单与原稿一一对应，年级、类型、标题、全文和文件名一致。
- 文件存在且 SHA256 与清单一致；ffprobe 识别为 MP3。
- 每条真实时长为 **60–180 秒**；实测与清单记录相差不超过 0.1 秒。
- 有真实语音引擎生成记录。

复验不会修改 MP3、原稿、清单或目录权限。它能证明文件完整性与编码/时长合同，不能代替逐条听感评审或微信真机音频测试。

## 使用 Edge TTS 重新生成

Edge 是脚本默认引擎，需要可连接其公开语音服务；正常请求无需用户 API Key。先安装 `edge-tts`，以及系统 ffmpeg/ffprobe：

```bash
python -m pip install edge-tts
python scripts/make_listening.py --output /新的素材目录 --limit 1
python scripts/make_listening.py --output /新的素材目录
python scripts/make_listening.py --output /新的素材目录 --verify-only
```

可用 `--voice en-US-JennyNeural` 明确指定英语音色。先生成 1 条验证真实网络和听感，再取消 `--limit` 生成全部。`--limit` 只限制生成条数，完整复验仍要求全部原稿对应音频。

本次环境的 Edge 首次请求遇到 DNS 解析失败；代理出口随后仍返回 WebSocket 403。生成器没有把这些失败伪装成成功，也没有在生产逻辑中静默替换引擎。交付音频明确选择了下面的离线 Piper 路径。

## 使用本地 Piper 生成

需要自己已下载、已核对许可的 Piper `.onnx` 模型和同目录的 `.onnx.json` 配置。本脚本不自动下载模型，不修改源模型权限，也不把模型打入交付 ZIP。

```bash
python -m pip install piper-tts==1.3.0
python scripts/make_listening.py \
  --backend piper \
  --piper-model /模型目录/en_US-ljspeech-medium.onnx \
  --output /新的素材目录 \
  --limit 1
```

样本确认后移除 `--limit 1`，执行同一命令即可补齐其他条目。生成器限制 ONNX Runtime 为两个计算线程，并禁用其遥测事件。Piper 依赖和语音模型仅用于离线素材制作，家长端播放时不需要加载模型。

脚本按年级使用 1.30 / 1.18 / 1.05 的 `length_scale`；之后根据原稿词数和 ffprobe 实测长度计算 `atempo`。只允许 0.5–2.0 倍调速，目标时长留在 63–175 秒范围内，最终编码仍须通过 60–180 秒门禁。若文稿过短、过长或所需调速不合理，条目会失败，请调整文稿或音色，而非补静音。

## 断点恢复与失败处理

每条成功后原子更新 `index.json`。下一次运行只复用完整原稿一致、SHA256 一致、真实编码/时长均合格的已有素材。复用可以跨语音引擎；更换参数后若明确想重新制作，添加 `--force`。默认不会为了更换默认引擎而反复重做已验证音频。

```bash
# 恢复中断或失败的生成；已有合格素材复用
python scripts/make_listening.py --backend piper --piper-model /模型目录/en_US-ljspeech-medium.onnx

# 明确重做前 1 条；建议先在新输出目录试听
python scripts/make_listening.py --backend edge --output /试听目录 --limit 1 --force
```

`failures.json` 列出失败 ID、错误类型与安全提示，包含生成数、复用数和完整性标记。网络/引擎失败不会生成替代 MP3，不会被写成“暂无素材”的成功状态；脚本存在失败时返回 1，输入/整体校验错误返回 2。日志不输出密钥或原始提供商认证 URL。

输出目录使用 `.build.lock` 防止并发写同一清单。异常退出留下锁时，先确认已无生成进程，再删除这个遗留锁后恢复。临时文件写在输出目录内，完成后原子替换；没有通过校验的条目不会作为新资产发布。不要同时运行两个生成器去写同一个素材目录。

## 前端验收

在微信开发者工具和真机还应逐项检查：

1. 九个年级都有 5 条；“全部 / 短文 / 对话”点击不报错且筛选正确。
2. 时长显示为 `分:秒`，全文与所选音频对应；播放、暂停、拖动、上一条、下一条可用。
3. 下载期间离开页面，下载被取消，稍后不发出声音；快速选两条只播放最后选择。
4. 401、404、503、断网分别显示可见错误，成功空列表才显示“没有素材”，年级和类型筛选始终可用。
5. 配置 HTTPS request 和 downloadFile 合法域名；音频凭证通过请求头提交，不放在 URL 中。

Node 自动化已运行真实页面 JS 的上述事件和乱序回调，但不会执行微信原生音频组件。
