# 研发可靠性修复与复核记录

日期：2026-10-21。范围：修复计划 Task 3；一名学生独立脑端，不以多学生部署为本次验收前提。没有访问真实 ASR/TTS/LLM、部署机器、麦克风或微信；未部署、提交或修改原审查源码副本。

## 修复结果

| 审查项 | 实现 | 可检验的结果 |
|---|---|---|
| ENG01，响应丢失后旧录音被用于下一题 | 每个脑端回复发出 `question_id`，录音必须同时带 `session_id`、`question_id`。Pi 在录音开始时固定题位，未确认请求保留原 ID，冻结后续队列 | 旧题新请求在 ASR 和进度写入之前得到 409；同一已完成事件的精确重传先返回缓存，不因题目已经推进而被误拒。组合 Pi/脑端/真实 SQLite 的丢回复回放只留下 apple 一条记录，没有 banana 错题记录 |
| ENG02，进度提交后下题失败，重判导致幂等冲突 | 新增 `turn_recovery.py`。回合前快照、首次已确认 IO 结果、发送前的进度写入意图、最终回复与状态原子保存。失败恢复快照并重放原结果；未确认写入使用原 key 和原 payload | 下题失败、进度响应丢失、脑端重启后的原请求重试均不重新判定已提交答案，也不重复增加证据。单词断点直到成功迁移并持久化结果之后才删除 |
| ENG03，畸形模型协议抛 500 而绕过回退 | 严格校验顶层对象、choices、choice、message 和 content；统一抛 `ProviderError(code='MalformedResponse')` | choices 为 null、空列表、元素 null、message null、顶层列表、content 非字符串均进入可控失败。真实 Public API + Providers + 测试 HTTP 传输验证了学生模型失败后回退平台模型并标记 fallback |
| ENG04，DNS 阻塞主事件循环并绕过总超时 | DNS 校验放入专用最多 4 个线程；总 deadline 同时覆盖 DNS 和完整 HTTP 响应 | 取消等待不会释放尚未完成的真实 DNS 工作槽；满容量直接报 ResolverBusy。慢 DNS 不阻塞旁路协程，且包含在调用总时限内。保留现有 HTTPS 公网地址检查和禁止跟随跳转 |
| ENG05，Vosk 并发冷启动重复加载 | 模型缓存增加锁内二次检查，识别器仍逐请求创建 | 4 个并发首次请求只加载一次模型；同一模型可以继续服务各自的识别器 |
| ENG07，旧桥相同文本被永久当作同一事件 | `/voice/push` 支持显式 request_id；缺省时每次到达产生新 ID | 两次相同“开始练习”启动不同会话；桥接器传同一事件 ID 时可精确重放 |
| v3 thinking、语速、控制口令 | thinking 按学生布尔设置透传；脑端按配置年级计算学段，忽略 Pi 自带的学段值；小学 −15%、初中 −8%、高中 0%，慢一点再减 10 个百分点；拆分 explain/howtosay | 覆盖两种 thinking 值、三学段普通/慢速的 Edge TTS wire rate、HTTP TTS speed；保留英文停止及精确中文常用别名，未加入模糊整句匹配 |
| v3 在线状态 | 脑端生命周期独立每 5 秒发送 `pi=False`；Pi 即使未开课仍发 tick，入口更新 `pi=True`；同类心跳 3 秒节流 | Pi 停止不能使仍运行的脑端被误判为离线；慢课堂请求持有回合锁时，脑端周期心跳仍继续 |
| 独立复核 F1，首次开课回复丢失时停止口令失效 | `Edge.starting` 识别排队或未确认的开课；入口允许此状态下的停止，同时合并重复开课唤醒 | 首次开课响应丢失、Pi 从 pending-start 恢复、停止响应再次丢失均可可靠结束；正常空闲语音仍不提交 |
| 独立复核 F2，结束点评合成或播放失败后无法重播 | Pi 独立保留最后一份结束回复；空闲 tick 不覆盖它；“再说一次”仅调用合成和播放，不发课堂回合 | 实际 Tutor 场景结束后 TTS 503 或播放失败，再经过空闲 tick，仍能重播原有 6 段回复；没有额外判题、进度或 played 通知。新开课、停止会清除缓存并取消排队或正在合成的旧点评 |
| 独立复核 F3，默认 INFO 日志长期记录完整对话 | 麦克风识别、课堂回复和普通聊天转交只记录长度、段数、状态与置信度；`--text` 显式输出到交互终端 | caplog 覆盖三处默认路径不含原文；文字调试仍可看见题目，日志中没有该题目正文 |

## 回合恢复的提交边界

恢复文件不是对远端数据库事务的模拟回滚。公共 SQLite 一旦写入成功，该证据就是已完成事实。脑端先持久化每项进度写入的参数和幂等 key，再调用公共服务；收到结果后持久化该结果，再进行下一项工作。恢复时重用已经完成的判断和写入结果，只有尚未确认的稳定意图会重新发送。数据库原有幂等语义继续负责重复 HTTP 传输的去重。

如果最后一项模型 HTTP 返回成功，但内容未通过 Tutor 的格式或语义校验，仅该末尾读取允许再次生成；它之前已经被后续 IO 接受的判断和写入都保留。回归覆盖了“首次判对并已写库，但下题 JSON 错误”的情况，最终只增加一次用词证据。

完成回复与恢复快照先落盘，再调用引擎的 `commit_resume_changes()`。引擎提供 JSON 安全快照、完整恢复和延迟断点操作；单调时钟恢复时重基准，停机不会消耗学生的练习时长。恢复日志 IO 顺序不一致时明确失败，不能默默换一套判断继续。

## 短期缓存与清理边界

- 脑端文件位于 `RESUME_STATE_PATH` 同目录的 `turn-recovery.json`；默认安装采用 systemd 的状态目录。文件 0600、目录 0700，临时文件同样 0600，完成 fsync 后原子替换。
- 脑端只保留一个未确认回合、最近最多 128 个完成回复及当前恢复快照，有效期 6 小时。缓存可能包含当前判断所需的短期文本、已识别文字和待重放的回复；不包含 provider 凭证或原始音频。结束后的持久化 Tutor 快照会清空嵌套 `state.history`；短期完成回复仍按上述 TTL 保留，不能把这说成所有文本即时消失。
- 运行中的后台维护和新请求入口都会清理到期状态，不依赖进程重启。到期会保留已有词汇进度，并恢复到空闲；有需要时保存原词汇断点。原词汇续学断点仍采用引擎既有的 7 天有效期。
- Pi 使用 `EDGE_PENDING_PATH`，或 `STATE_DIRECTORY/pending-turn.json`。为跨进程恢复一次未确认上传，文件临时包含该次音频的 base64、事件 ID、题位和最后确认的显示状态；这是编码而非加密。文件 0600、目录 0700，完成确认、明确结束或到期后清除音频。文件只匹配当前脑端地址和凭证的摘要，不保存凭证明文。
- Pi 失败后先确认原事件，再放行后续回答；确认为新题后丢弃旧题排队录音。明确停止可以取消尚未确认的后续处理，已经提交的进度保留。开始、停止、暂停、继续是会话控制，不携带过期题目限制；答案和题目相关帮助仍带题位。
- Pi 的结束点评重播只保留一份内存中的 `segments`、语速和阶段，不另存磁盘。它可以保留到下一次开课、明确停止或进程退出；空闲 tick 不清除它。进程退出后不承诺继续重播结束点评。默认生产日志不写转写、题目、点评或普通聊天原文；显式 `--text` 调试会向使用者的终端展示回复。
- 未配置可写状态路径的手动调试只具备内存恢复，不能保证进程重启后恢复。正式安装的脑端和 Pi 必须保留各自的 StateDirectory，不能把这个部署条件省略。

## 回归证据

所有新增外部服务替身只在 `tests/` 中；生产模块没有内置成功示例或假判断。测试运行命令：

```sh
python -m pytest tests/test_v3_reliability.py tests/test_providers.py tests/test_engine.py tests/test_http_integration.py -q --tb=short
bash scripts/test_all.sh
```

首次红测 `engineering-red.log`：28 个预期失败、39 个通过，覆盖原审查故障和缺失的 v3 透传。随后的自审先复现再修复：结束快照清历史层级和运行中 TTL（`engineering-edge-cases-red.log`）；慢回合期间周期心跳被清理锁阻塞（`engineering-heartbeat-red.log`）；丢失已完成响应后停止被旧题位拒绝（`engineering-stop-red.log`）；三条精确中文帮助别名（`engineering-control-alias-red.log`）；排队停止被暂停替换后阻断恢复（`engineering-queue-red.log`）。

第一轮专属套为 **131 passed**，见 `engineering-green.log`。它同时包含实际本地 HTTP 上的 brain/public/provider 三服务回放、真实 SQLite 以及 ffmpeg 解码；provider HTTP 是测试替身，不是真实供应商验收。

第一次全量 `test_all` 的中间结果为 253 通过、3 失败，保存在 `engineering-suite-attempt-1.log`。其中两个是正在迁移的旧 `test_tools` 六页合并入口与 howtosay 断言；另一个是新增强化断言误用了字段名 `answer_valid_count`，已改回公共模型既有的 `valid_count`，不是产品数据结构变更。共享任务合并后的当轮完整 `bash scripts/test_all.sh` 返回 **exit 0：264 个 Python 测试、43 个 Node 测试全部通过，无 skip**，并完成 Python 编译、小程序 JavaScript 语法和 shell 语法检查，见 `engineering-suite.log`。

独立代码审查提出的 F1 已先红再修：`engineering-review-route-red.log` 为 5 失败、3 通过，之后 `engineering-review-route-green.log` 为 61 通过；独立审查员另行执行 8 个 route 回归确认关闭。F2/F3 的 10 个专项在 `engineering-final-feedback-privacy-red.log` 全部因预期问题失败，修复后 `engineering-final-feedback-privacy-green.log` 为 10 通过。专项包含真实 Tutor 场景收尾、Pi `process → idle tick → route → process` 全路径，TTS 与音频播放明确使用测试替身。

末轮定向命令 `python -m pytest tests/test_v3_reliability.py tests/test_tools.py -q --tb=short` 为 **71 passed**，见 `engineering-review-targeted-green.log`。这轮没有修改或跳过旧测试。独立审查员重新阅读代码并单独执行 F1/F2/F3 的 18 项测试，全部通过，三项均已关闭；最终全库门禁由主任务在产品修复合并后统一执行，避免把上述阶段性数量误称为最终交付总数。

测试依赖仍有一条 Starlette 对 AnyIO `BlockingPortal` 别名的上游弃用警告；未通过修改或跳过测试掩盖。Task 3 所有修改文件已通过 `git diff --check`。

## 仍需现场验收

尚未验证真实腾讯/兼容 ASR、云端模型、Edge/兼容 TTS 凭证及网络的可用性，也未验证真实 Vosk 模型的内存、树莓派录放音、儿童发音或微信真机。自动化只验证协议、调用边界、失败恢复和本地串联，不能证明 v3 的 8 秒响应或 15 秒开课目标。DNS 总超时能停止等待，但不能中断操作系统中正在运行的解析；后台占用受最多 4 个工作限制，待解析真正结束才释放。部署仍须同步更新 brain 和 Pi，旧音频客户端不携带题位会得到 422。
