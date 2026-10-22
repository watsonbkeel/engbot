# v0.3.4 运行时边界复核：HTTP 连接、ASR 与异常

日期：2026-10-21。复核基线：`b0a85e54c3b3815306b717fcaaa4980a5b433ce9`（v0.3.3）。本报告对应 Mac 审查的 P1-4、P1-5、P1-6 及 P2-3 日志范围；仅进行了本地源码、测试和回环 HTTP 验证，没有访问或部署线上服务。

## 1. 审查结论

| 审查项 | 结论 | 基线实况与本次处理 |
|---|---|---|
| P1-4：PublicClient 每请求新建 AsyncClient | 成立，属于连接复用和资源效率问题 | 基线每请求确实创建新池，但 `async with` 会正常关闭，不能据此认定已有连接泄漏。改为每个学生客户端在服务事件循环中延迟创建一个连接池，由脑端 lifespan 关闭。 |
| P1-5：内部 ASR 仅检查字节数，没有音频格式和时长防线 | 部分成立 | “全链路缺少格式、采样率、时长校验”不成立：脑端和真实 provider 都调用 `validate_wav`。确实存在畸形 RIFF chunk 解析成 500 的漏口，以及本地识别缺少等待时限和全进程共享容量的问题。 |
| P1-6：外依赖异常可能直接成为 500／泄漏内部信息 | 部分成立 | 已知 HTTP、超时、坏模型响应、Vosk、Edge TTS、ffmpeg 故障已有 ProviderError。复现了 InvalidURL、畸形 WAV RuntimeError、PublicClient 非对象 JSON 错误正文三个漏口。基线 API 默认返回 `Internal Server Error`，本次未复现堆栈或密钥从这些 500 响应泄漏。 |
| P2-3：关键请求缺少统一日志 | 部分成立 | 基线不是没有日志：ASR 成功／降级已有 backend、provider、fallback、code、request_id、ms、unclear，脑端有 class_request/asr_request 关联；均不记录原始音频、识别文本或凭证。缺少失败分支和跨 LLM／ASR／TTS／scene 的统一关联字段，由主任务的请求边界日志补齐，不重写既有安全诊断。 |

依据：[client.py](../../english_class/client.py)、[providers.py](../../english_class/providers.py)、[brain_api.py](../../english_class/brain_api.py)、[public_api.py](../../english_class/public_api.py)、[run.py](../../english_class/run.py)。

## 2. 修改前的可复现证据

### 2.1 连接复用

临时探针向测试 transport 并发发送 5 次 PublicClient 请求：创建 5 个 AsyncClient，结束时 5 个均已关闭。另用真实回环 HTTP 发起同一学生的 4 次顺序请求，服务器观察到 4 个不同客户端端口。前者证明没有该路径上的遗留连接，后者证明无法跨请求复用 TCP 连接。

### 2.2 WAV 容器错误

下面的 32 字节输入声明了一个超过父 RIFF 容器边界的 JUNK chunk：

```python
import struct
bad = (b'RIFF' + struct.pack('<I', 100) + b'WAVEJUNK'
       + struct.pack('<I', 0xffffffff) + b'\0' * 12)
```

Python 3.12 的 `wave._Chunk.seek` 对此抛出空 `RuntimeError`。原 `validate_wav` 仅归一 `wave.Error` 和 `EOFError`，因此 `/internal/asr` 和当前题位的 `/voice/audio` 都返回 500。脑端此时尚未创建 pending，也未调用 ASR；问题属于输入错误的错误映射，不是已写进度被污染。

对照探针：普通非 WAV 文件返回 422，31 秒的 16kHz PCM WAV 也返回 422。既有校验已要求单声道、16 位 PCM、16kHz、0.01—30 秒以及完整帧；本次复用该函数，仅补上 RIFF 解析器会抛出的 RuntimeError。

### 2.3 ASR 并发与本地等待

修改前的测试替身探针同时提交 40 个云 ASR 调用，40 个全部进入供应商调用。40 个本地调用中观察到 13 个默认 executor worker 已启动、40 个请求仍在等待；默认线程池的 worker 数限制并不限制提交队列。

云 ASR 已有覆盖完整响应的 `asyncio.wait_for(..., asr_timeout)`，默认 8 秒，也有本地降级与冷却期。脑端串行锁只限制单个学生的回合。Vosk 冷启动锁只防止同一模型重复加载。这些措施均不等于公共服务进程中所有学生共享的 ASR 容量限制；本地 Vosk 与降级路径此前没有等待时限。

### 2.4 异常类型漏口

给教师侧 LLM、HTTP ASR、HTTP TTS 的 base 配置测试值 `http://invalid:port`，三条路径都抛出 `httpx.InvalidURL`。此异常既不是 `httpx.HTTPError`，也不是 ValueError，因此绕过原有 ProviderError 归一逻辑。

PublicClient 收到状态 503、JSON 正文为 `[]` 或字符串时，原实现直接调用 `.get('detail')`，抛出 AttributeError。错误正文如果包含结构化验证详情，还会把输入字段直接字符串化转发。本次只传递服务有意给出的非空字符串 detail；其他形状使用固定可操作错误信息。

## 3. 修复设计及接口

### PublicClient 与脑端生命周期

- PublicClient 构造函数不创建网络资源。第一次请求在当前事件循环中创建一个专属 AsyncClient，后续请求复用。
- 新增 `await client.aclose()`。必须在创建连接池的事件循环中调用；重复关闭安全，关闭后可在新的生命周期和事件循环中重新使用同一个 PublicClient 实例。未关闭的池禁止跨事件循环复用，返回 ServiceError。
- `create_brain` 的 lifespan 在退出时先取消并等待心跳任务，再调用 IO 对象可选的 `aclose()`；启动失败也执行清理。不要求纯本地／测试 IO 实现网络关闭接口。
- 原请求超时保持 90 秒、连接超时保持 8 秒；每客户端最多 10 个连接，保留 5 个空闲连接，keep-alive 保留 30 秒。
- Authorization、student_id、音频 Content-Type 与幂等键仍按请求设置；不同学生持有不同池。没有增加自动 POST 重试，也没有改变恢复日志使用的幂等键。
- 脑端以外的独立调用者应在 `finally` 中 `await client.aclose()`。使用 ASGITransport 的测试须显式执行 lifespan 或关闭 IO。真实回环集成测试已经启用 lifespan，验证服务关停确实会关闭连接池。

### ASR 容量与时限

| 配置／常量 | 默认值 | 作用 |
|---|---:|---|
| `ASR_MAX_CONCURRENT` | 4 | 每个公共服务进程共享的 ASR 槽数。云识别和本地实际 worker 共用同一容量，跨 Providers 实例生效。 |
| `ASR_TIMEOUT` / `asr_timeout` | 8 秒 | 既有云识别整体时限，保持不变。 |
| `ASR_LOCAL_TIMEOUT` / `asr_local_timeout` | 30 秒 | 新增本地 Vosk 冷启动和识别等待时限，直接本地识别和云失败后的降级均使用。 |

没有空闲槽时立即抛 `ProviderError(code='Busy')`，API 返回 503，不排入无限等待队列。输入校验和静音门限仍先执行，不把坏录音或静音当成耗时识别任务。

本地识别使用独立的最多 4 worker executor；容量在提交前取得，只由 concurrent future 完成回调释放。请求超时或被取消不会终止 Python worker，也不会提前释放它的槽位。云调用退出后先释放自己的槽，再按现有策略进入本地降级，避免同时占两个槽。降级和冷却诊断字段保持原义。

云 8 秒后若需要本地降级，仍保留独立的本地 30 秒等待预算，不把总时限错误缩成 8 秒。公共路由另有总等待保护，由主任务集成；本报告不以路由取消替代 worker 生命周期限制。

### 异常契约

继续使用现有 ValueError、ServiceError 和 ProviderError，不引入另一套不兼容的异常体系。畸形 WAV 转为安全 ValueError，由既有 API 映射为 422；非法供应商 URL 转为不含实际地址或凭证的 `ProviderError(code='InvalidConfiguration')`；任意形状的 JSON 错误正文都归一为 ServiceError。

## 4. 验证记录

所有外部供应商替身均位于 tests；实际 HTTP 集成只使用本机回环地址。运行解释器为 `/workspace/scratch/d3b03e9e7aea/eng_audit/venv/bin/python`，Python 3.12。

| 阶段 | 命令范围 | 结果 |
|---|---|---|
| 修改前基线 | `tests/test_providers.py tests/test_v032_engineering.py tests/test_http_integration.py tests/test_core.py tests/test_v3_public.py` | 100 通过 |
| 新回归先失败 | `tests/test_runtime_boundaries.py` | 16 失败、4 通过；失败对应 WAV 500、URL 异常、错误正文、连接复用／关闭、共享容量和本地时限 |
| 首次相关集合 | 新回归及下列相邻测试 | 182 通过、1 失败：既有 `test_malformed_student_model_reaches_real_public_fallback` 未显式同意本轮新增的模型回退策略 |
| 修正旧测试前提后 | `tests/test_runtime_boundaries.py tests/test_providers.py tests/test_v032_engineering.py tests/test_http_integration.py tests/test_tools.py tests/test_v3_reliability.py tests/test_llm_optional_thinking.py` | 183 通过，0 失败 |

旧回退测试已显式保存 `allow_platform_fallback=True`，保留它原本验证“畸形学生模型经真实公共层回退”的目的。新增测试验证：真实 TCP 连接复用且不同学生凭证隔离；两个不同事件循环中的启动／关闭；心跳退出顺序；坏 RIFF 不创建 pending 且可重新录音；云 ASR 跨实例共享 4 槽；本地超时与取消后，实际 worker 未结束前禁止新增本地或云工作；完成后容量恢复；云超时仍有独立本地降级预算。

上述命令唯一警告是基线已有 Starlette / AnyIO BlockingPortal 弃用提示。全项目统一门禁由主任务在所有并行修改合并后运行，本组的 183 项不替代最终全量报告。

## 5. 验证边界

没有验证真实儿童音频、Vosk 模型下载、外部供应商账号、Mac 真机、树莓派耳麦或生产延迟。30 秒本地等待默认值仍须结合实际模型、CPU 和并发量验收。

线程中的原生识别若永久卡住，响应可超时，但 Python 无法安全强杀该线程；它会持续占用槽，后续请求及时返回 Busy，必要时由运维重启该公共服务进程。这里保证请求等待和任务数量有界，不声称已经解决所有原生库故障。4 槽是进程内容量；如果额外配置多个公共服务进程，需要按进程数规划总容量。
