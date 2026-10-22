# v0.3.2 工程复核与修复证据

日期：2026-10-21。基线：v0.3.1，Git `98eaddd3c4a35ab23a5e02ba373f05f0c2d645c9`。

本次按实际请求路径复核脑端、公共服务、供应商适配和 Pi 恢复流程。前三项以及独立复核补充的升级问题，都先写回归并观察失败，再做定向修复。数据库结构和原机器人服务保持兼容；恢复日志 `FORMAT_VERSION` 不变，pending 新增 `executor_version` 元数据。

## 1. 已确认的问题

| 问题 | 修复前的可重复证据 | 修复与修复后证据 |
|---|---|---|
| 自带模型域名检查后再次解析，可尝试连接内网地址 | `Providers.chat → HTTPX → HTTPCore → AnyIO` 路径中，第一次 DNS 返回 `8.8.8.8`，第二次返回 `127.0.0.1`；仅在最终 TCP 打开处拦截，实测目标为 `127.0.0.1`，测试失败 | 在原有有界 DNS 工作池中同时返回规范地址和全部验证通过的 IP，HTTP 连接固定使用这些 IP。回归要求仅解析一次，实际连接目标非空且恰为 `8.8.8.8` |
| 损坏 WAV 被记为未确认回合，永久输入错误被当成暂时服务故障 | 脑端先调用 `recovery.begin`，随后 ASR 的 WAV 校验失败；基线响应 `503`，而期望是可丢弃的 `422` | 在回放命中与旧题检查后、创建待确认日志前校验 WAV。坏输入返回 `422`，不创建 pending；Pi 释放该请求、明确提示重新回答，原题保持可用 |
| 默认 Pi 错误日志泄露完整题目话术 | `BrainRequestError.detail.current.segments` 含完整当前题目，`LOG.error('%s', exc)` 将其原样写入日志；私密示例文本出现在捕获日志中 | 异常字符串仅保留 HTTP 状态；详细对象继续用于同步题位。测试同时断言恢复得到完整当前题目、日志不含该话术 |

录音修复还覆盖实际 `route → Edge.submit/process → brain` 链路：坏录音后两端均无 pending、题号不变；随后录制有效短 WAV，正常进入 recall，数据库的有效回答计数恰为 1。旧题拒绝和永久拒绝后的提示不再说“正在确认，请等待”。

## 2. 网络安全修复边界

`english_class/providers.py` 保留原始域名的 Host 与 TLS SNI，继续使用 `check_hostname=True`、`CERT_REQUIRED` 的 SSL 上下文，没有设置 `verify=False`。测试读取真实 HTTPX/HTTPCore 生成的请求字节和 TLS 参数，覆盖：

- 标准 HTTPS 端口和自定义 `8443` 端口。
- IPv6 地址的 Host 方括号与 TLS 主机名。
- 第一个已验证地址连接失败后尝试第二个地址；所有尝试共享同一总截止时间。
- DNS 同时返回公网和内网地址时，在连接前整体拒绝。
- 自带模型忽略环境代理，防止代理再次解析未经约束的目标。
- 平台模型继续支持管理员配置的环境代理。

部署影响：**家长自带模型必须可从公共服务直连公网 HTTPS，并提供可验证的 TLS 证书。** 自带模型不使用 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 等环境代理；可信平台配置保持原有行为。

所有 DNS、安全连接与 TLS 参数测试均使用测试目录内的受控解析器／网络流。没有建立外网连接，没有使用真实密钥，也没有把这些断言称为真实供应商或证书端到端验收。

## 3. 独立复核 F032-1：升级时的未确认回合

独立审查用真实 v0.3.1 引擎与恢复日志复现：旧版已经写入最后一个 recall 的学习进度，随后生成下一句对话失败；升级后提示词改变，恢复日志的严格 IO 指纹与新版执行不一致，原请求反复得到 503，无法自动走出旧回合。

新增 `tests/fixtures/v031_pending_turn.json` 由实际基线的 `brain_api.py`、`engine.py` 和 `turn_recovery.py` 运行生成，只使用测试词库、SQLite 和测试供应商。测试包直接读取该固定夹具并重设时间，不依赖交付 ZIP 带有 Git 历史。修复前新增 API 回归为 **8 失败、1 兼容用例通过**。

定向处理策略：

- 新 pending 保存 `executor_version`。没有版本或版本不匹配的 pending 使用升级结束流程，不放松原请求及原 IO 指纹校验。
- 原编号、原内容重试时，先逐条确认尚未 `done` 的 record，以保存的原 args、kwargs、幂等键调用公共服务。每条确认结果单独原子落盘；已经 done 的 record 不再发送。不调用模型或 ASR，不重新判题。
- 记录确认暂时失败时保留 pending 和剩余意图；重启后仍可继续。公共库已提交但响应丢失的写入使用原键去重，不能重复增加计数。
- 显式 stop 是取消：不等待不可达的未确认写入，允许放弃这些意图，已经确认的 SQLite 记录保留。它和原编号正常结算都返回明确的升级结束提示，不宣称完成整节课或补写掌握状态。
- 一次原子提交保存原请求的结束回复；显式 stop 另保存它自己的编号，二者各自返回正确 request_id 和相同新题号。缓存提交失败时旧 pending 仍在，旧续学文件也保留。提交后才实际清理续学断点，并清空活动 history。
- 清理旧续学文件暂时失败时，完成回复仍可重放，但新 start 先重试清理；清理仍失败则拒绝新开课，避免旧问题复活。
- 门禁与 Tutor 使用同一文字控制解析和可靠性门槛：`action=answer` 的可靠“开始今天的英语练习”及 `/voice/push` 也不能绕过清理，可靠“结束练习”可关闭旧 pending。低于 0.65 的置信度或 unclear 不触发这些控制；原始请求正文和指纹不变。
- 升级结束检测发生在新的 WAV 校验之前，因此旧版已经留下的损坏录音 pending 也能关闭。旧版已完成缓存原样重放；没有 pending 的旧状态仍按正常迁移继续。

中文辅助关闭时给出英文升级说明。其他请求编号仍返回 409，同一编号不同内容也仍冲突。独立复验补充发现文字／旧桥接门禁遗漏，相应三条路径再次观察到修复前失败后闭环修复。`tests/test_v032_upgrade.py` 现有 **11 条**回归覆盖上述边界；既有同版恢复测试继续通过。

## 4. 文件变化

- `english_class/brain_api.py`：持久化回合之前验证 WAV，永久输入错误返回 422。
- `pi/english_voice.py`：隐藏异常正文，保留恢复 detail；区分等待确认、旧题和可重新回答的拒绝提示。
- `english_class/providers.py`：受同一工作池和总超时约束的地址验证与连接固定；保留 Host、SNI、证书验证及经过验证的多地址回退。
- `english_class/public_api.py`：FastAPI 元数据、health、capabilities 都引用包内 `__version__`。
- `english_class/turn_recovery.py`、`english_class/brain_api.py`：新增 pending 版本标记、升级结算与明确结束、双编号原子缓存和续学清理顺序保护。
- `tests/test_v032_engineering.py`：10 条新增工程回归（含参数化用例）。
- `tests/test_v032_upgrade.py`、`tests/fixtures/v031_pending_turn.json`：11 条真实旧版日志升级 API 回归及自包含夹具。
- `tests/test_engine.py`、`tests/test_v3_reliability.py`：旧的音频协议替身改为有效短 WAV，原有题位、重放、进度与停止断言保留。
- `tests/test_providers.py`、`tests/test_v3_reliability.py`：原先只替换 URL 检查的测试改为返回受控 IP；自带模型身份由原始 Host 判断，保持原有异常回退和 thinking 测试目的。

## 5. 验证命令与结果

在项目根目录，使用 `/workspace/scratch/d3b03e9e7aea/eng_audit/venv/bin/python`：

```bash
python -m pytest -q tests/test_v032_engineering.py tests/test_providers.py tests/test_v3_reliability.py tests/test_core.py --tb=short
# 135 passed, 1 warning in 3.35s

python -m pytest -q --tb=short
# 309 passed, 1 warning in 10.32s

# F032-1 修复后的升级、工程及既有可靠性验证：
python -m pytest -q tests/test_v032_upgrade.py tests/test_v032_engineering.py tests/test_v3_reliability.py --tb=short
# 69 passed, 1 warning in 1.90s
```

309 条完整 Python 结果是首轮审查时点的集成快照，早于 F032-1 追加修复；升级修复及文字控制入口修复后完成 69 条定向验证，由最终统一门禁重新验证整个交付版本。唯一警告为既有 Starlette 对 AnyIO `BlockingPortal` 别名的弃用提示。

未验证真实儿童语音识别、Pi 耳麦与回声、微信手机端渲染、供应商账号连通和生产负载。本报告不把本地回归等同于这些目标环境验收，也不声称对全部异常输入做了穷尽证明。
