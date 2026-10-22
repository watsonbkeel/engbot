# 自带模型关闭 thinking 时的兼容修复

日期：2026-10-21。范围：v0.3.3 发布前，学生自行填写模型接口的保存测试、场景生成及后续对话共用的 `Providers.chat`。

## 发现的问题

原适配器对每个 Chat Completions 请求都发送 `thinking: {type: "enabled" | "disabled"}`。因此即使小程序的深度推理开关关闭，请求仍包含 `thinking`。严格拒绝未知字段的兼容端点会拒绝这个请求；保存探针随之返回 422，学生无法保存本来支持其余请求字段的模型配置。

这是请求协议差异，而不是密钥填写错误。原错误转换把相应 HTTP 400 归一为“自带模型调用失败”，无法绕开被拒绝的可选字段。

### 官方来源

已打开并检查以下官方页面（检索日期 2026-10-21）：

- [OpenAI：Create chat completion](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)：请求参数列有 `reasoning_effort`，没有 `thinking`。参数支持也受具体模型限制。
- [DeepSeek：Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)：明确提供 `thinking.type=enabled|disabled`，默认 enabled。
- [DeepSeek：Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)：在 OpenAI SDK 示例中通过 `extra_body` 传入 thinking，说明它是兼容协议的供应商扩展。

由此可以确认 `thinking` 不是通用 OpenAI Chat Completions 请求字段。这里没有使用真实 OpenAI Key 发起调用，所以 **不能把下面的测试替身 HTTP 400 当成真实 OpenAI 账号的观测结果**。证据分别是官方协议文档、当前请求代码及受控端点的可复现错误处理。

## 修复前的红测

新增 `tests/test_llm_optional_thinking.py`，使用实际 `Providers` 和公共 API。测试端点在请求含 thinking 时返回明确的未知字段 HTTP 400，移除该字段后返回合格 JSON；DNS 和 HTTP 均由测试替身提供，不联网。

初轮 20 项测试在修复前：**7 failed, 13 passed in 0.49s**。其中实际保存调用返回：

```json
{"detail":"测试调用失败，未保存：自带模型调用失败"}
```

HTTP 状态为 422；第一条请求确实携带 `thinking: {"type":"disabled"}`。失败断言对应缺少兼容重试、开启状态的可操作错误、重试上限和截止时间，以及保存后继续生成场景的完整路径。

## 有界修复

正式修改仅在 `english_class/providers.py`：

1. **第一条请求完全保持原样。** 支持此扩展的供应商仍收到显式 enabled / disabled，不额外发请求。
2. 只识别 HTTP 400 中结构化 error 对象明确指出 `thinking` 字段未知、无法识别或不支持的情况。缺少明确字段元数据时，错误 message 必须完整匹配对 thinking 字段的拒绝（可带成对引号和末尾句号/感叹号）；不接受前缀匹配。具体值不支持、子字段错误、其他字段、泛化的 400、非结构化错误不触发。
3. 原值是 disabled 时，只移除 thinking，然后 **最多重试一次**。不修改 messages、model、JSON 输出要求、token 上限、温度或其他字段。
4. 重试使用同一已验证目标 IP、Host、Authorization、TLS SNI 和客户端；不重新 DNS 解析，不换地址、学生或供应商，不读取环境代理。
5. 重试仍在原来的 `asyncio.timeout` 内：保存验证总时限 20 秒，常规模型调用默认 45 秒。第二次拒绝不继续重试。
6. 原值是 enabled 时，不偷偷移除用户要求的推理设置；返回固定提示“这个模型不支持 thinking 参数，请关闭深度推理后重试，或更换支持该参数的模型”。保存失败保留之前的有效配置。

### 为什么不在关闭时一律省略

DeepSeek 当前文档的 thinking 默认开启。若关闭开关时统一省略该字段，会改变已有 DeepSeek 请求的实际偏好。按明确拒绝结果做一次兼容重试，既保留原供应商的禁用要求，也允许拒绝该扩展的标准端点处理其余请求。

这个修复不把 thinking 映射为其他厂商的 reasoning 配置。端点拒绝 thinking 后移除它，只表示不再发送不支持的扩展；不能保证该供应商或具体模型自身的推理行为。仍须选择支持当前适配器其余参数、JSON 输出和延迟要求的实际模型。

## 验证结果

独立审查随后发现初版 message 分支的前缀匹配会误接收 `thinking.type`、`thinking.budget` 和值错误后缀。补充这些负向用例和引号匹配检查，先观测到 **4 failed, 12 passed, 9 deselected in 0.27s**，再改为完整字符串匹配。明确字段元数据分支保持不变；子字段、值后缀和不成对引号均不再触发兼容重试。

新增文件最终共 **25 项**。本次针对新修复、学生场景路径和原供应商/DNS安全边界运行：

```bash
python -m pytest -q tests/test_llm_optional_thinking.py tests/test_scene_design_api.py tests/test_providers.py tests/test_v032_engineering.py
```

最终结果：**109 passed, 1 warning in 3.67s，退出码 0**。警告是既有 Starlette / AnyIO `BlockingPortal` 弃用提示。

| 情况 | 断言 |
|---|---|
| 结构化未知字段、unsupported_parameter 或 unknown_parameter | disabled 请求只移除 thinking 后成功，恰好两次调用 |
| 供应商接受 disabled | 保留该字段，只调用一次 |
| enabled 遇到同样拒绝 | 一次调用，明确提示关闭开关或换模型 |
| unsupported_value、thinking.type / thinking.budget、值后缀、不成对引号、其他字段、近似字段名、泛化 400 | 不重试 |
| 401 / 403 / 404 / 429 / 500 | 不因正文提及 thinking 而重试 |
| 第二次仍失败 | 最多两次调用，正常失败处理 |
| 两次响应各需 0.06 秒、总限时 0.1 秒 | 在原总限时内超时，未得到两份独立限时 |
| 保存、生成、后续改开 enabled | 关闭时可保存并生成；改开后被拒绝，原设置完整保留 |
| 网络与凭证 | 两次请求目标、Key、Host、SNI、JSON格式相同，仅解析一次；原有 DNS pinning 回归仍通过 |

整包最终门禁由 v0.3.3 发布流程另行记录；这里不把上述定向 109 项冒充全量测试结果。未使用真实供应商或真实凭证，未对真实 API 成功率作承诺。
