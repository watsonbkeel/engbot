# v0.3.4 · 模型策略、公共错误边界与页面反馈独立复核

日期：2026-10-21。对象：v0.3.4 开发工作树，代码基线为 `b0a85e54c3b3815306b717fcaaa4980a5b433ce9`。本轮只读审查实现与既有测试，并使用临时 SQLite、虚构凭证和受控适配器执行独立探针；未修改实现或测试。设置／今日页的轮询改动由另一代理处理，不在本次范围。

## 1. 结论与发现项关闭状态

未发现 Critical。初次独立审查发现并向实现者报告 **2项 Important**，另有 **1项中等页面反馈问题**。实现者完成修复后，本审查员重新执行原独立探针及对应回归，**3项均已关闭**。以下保留修复前实测、建议和修复后结果，便于核对问题与证据；本结论只覆盖本报告的审查范围。

### I-1 · 默认请求校验响应回显凭证，且缺少统一错误编号 · 已关闭

位置：`english_class/public_api.py` 的异常处理器注册；`miniprogram/utils/english-api.js` 的错误读取。

服务注册了 ValueError、ProviderError 和 HTTPException，但 FastAPI 的 RequestValidationError 仍由默认处理器响应。对 `/api/llm` 提交超过400字符的虚构 api_key 时，422 的 `detail[].input` 原样包含完整提交值。其他不合格字段也可能把提交文本放入错误响应。这违背凭证接口不回传明文的约定；本例是向已经提交该值的调用者回显，不是跨学生读取密钥，但会让客户端错误正文再次携带敏感材料。

该响应只有 `X-Request-ID`，正文没有 `request_id` 或 `error_code`；小程序目前仅从正文读取两字段，故实际界面也拿不到这一类错误的反馈编号。

独立探针只输出判断值，没有打印虚构密钥内容：

```json
{"probe":"validation_error","status":422,"echoes_submitted_key":true,"body_request_id":false,"header_request_id":true,"error_code":null}
```

建议：统一处理 RequestValidationError，去掉 input、原始 ctx 和其他请求值，只返回安全的字段位置、类型及受控提示；保留前端能解释的字段校验结构，并加入 InvalidRequest 与同一 request_id。回归应覆盖 api_key 长度／类型错误、StrictBool 错误和包含学习文本的不合格请求，而不只检查状态422。

修复后，注册的 RequestValidationError 处理器仅保留 `loc/type/msg` 并使用统一错误响应。原超长 Key 探针不再回显提交值；正文与头部的 request_id 相同。独立补充的超长学习文本探针同样不回显文本，并且校验失败不调用模型、不额外占用尝试次数。对应3项 Key／StrictBool 回归全部通过。

```json
{"probe":"validation_error","status":422,"echoes_submitted_key":false,"body_request_id":true,"header_body_id_match":true,"error_code":"InvalidRequest","safe_detail_fields":true}
{"probe":"learner_validation_error","status":422,"echoes_submitted_text":false,"header_body_id_match":true,"attempts_after_invalid":1,"provider_calls":1}
```

第二条探针延续前一条合法但超时的场景调用，因此已有1次尝试和1次供应商调用；不合格学习文本没有增加它们。

### I-2 · 场景外层超时绕过模型状态更新 · 已关闭

位置：`english_class/public_api.py` 的 `generate_scene`；`english_class/llm_service.py` 的 `ModelService.chat`。

场景路由先进入一个20秒 timeout，随后 ModelService 再进入另一个20秒 timeout。外层总会略早到期，因此在学生模型未返回的场景中，它向 ModelService 注入 CancelledError，绕过后者的 TimeoutError 分支。场景正确返回503且不计成功，但已保存模型状态仍可能为 `ok`，设置页因而继续显示最近一次模型调用成功，结构日志则把超时记为 Cancelled。

独立探针使用15毫秒的场景时限和200毫秒的受控模型延迟，实测：

```json
{"probe":"scene_timeout","status":503,"error_code":"ServiceUnavailable","saved_last_status":"ok","usage":{"attempts":1,"successes":0,"remaining":19}}
```

建议：让 ModelService 统一拥有这一总时限，或者由外层超时明确记录模型失败状态和 Timeout 分类。不要为了修复反馈而扩大原有20秒场景预算。回归须经过真实生成路由，同时核对响应、模型状态、日志分类和 attempts/successes。

修复后移除了路由外层 timeout，由 ModelService 使用同一场景时限处理学生尝试及可选平台尝试。重新执行相同15毫秒／200毫秒探针，确认响应分类、保存状态和模型日志均为超时失败，次数仍为1次尝试、0次成功；HTTP 与模型日志关联到同一 request_id。经过真实路由的新增回归通过。

```json
{"probe":"scene_timeout","status":503,"error_code":"Timeout","saved_last_status":"error","usage":{"attempts":1,"successes":0,"remaining":19},"model_timeout_logged":true,"http_model_id_match":true}
```

### M-1 · 生成中编辑草稿后，已消耗额度不再刷新 · 已关闭

位置：`miniprogram/pages/scenes/index.js` 的 `onGenerate`、`onDescInput`、`onTemplate`、`onField`。

描述与模板在生成期间仍可修改。修改会使 generate 请求代次失效，能正确阻止旧响应覆盖新草稿；但 `finally` 中额度刷新也放在同一个 active 判断下，因此实际已占用的请求结束后完全不刷新次数。用户留在页面上时，可以一直看到旧的剩余值。服务端上限仍然有效，未发现绕过20次限制。

独立 Node 探针加载真实 PageJS，先显示0次、剩余20，再发出生成、修改描述、完成旧响应，得到：

```json
{"probe":"usage_after_edited_generation","generatedRequests":1,"usageRefreshes":0,"visibleAttempts":0,"remaining":20}
```

建议：把“同课堂且页面仍可见的额度刷新”与“该响应仍拥有当前草稿的修改权”分开。旧结果不得覆盖草稿，但同课堂已消耗的请求应反映到额度；隐藏页面或切换课堂仍不得触发迟到状态写入。

修复后 `life.guard` 独立保护页面可见性、页面代次与课堂身份；生成 finally 用它决定是否刷新 usage，草稿覆盖继续由 generate 请求代次控制。原真实 PageJS 探针现在刷新至1次／剩余19，保留新草稿；新增隐藏页面、切换课堂探针都不刷新迟到额度。描述、字段、模板、示例4类编辑以及课堂切换回归全部通过。

```json
{"probe":"usage_after_edited_generation","boundary":"edit","usageRefreshes":1,"visibleAttempts":1,"remaining":19,"draftPreserved":true}
{"probe":"usage_after_edited_generation","boundary":"hidden","usageRefreshes":0,"visibleAttempts":0,"remaining":20,"draftPreserved":true}
{"probe":"usage_after_edited_generation","boundary":"classroom","usageRefreshes":0,"visibleAttempts":0,"remaining":20,"draftPreserved":true}
```

## 2. 已核对的有效行为

| 范围 | 核对结果 |
|---|---|
| 默认不回退 | LlmSettings 使用 StrictBool、缺省false；未授权的学生模型异常及非JSON对象只返回失败，不发送平台请求。 |
| 明确授权与凭证 | 保存时显式字段传入Store；运行时只取本人base_url/model/api_key/thinking，自带与平台分别调用，不将学生Key放入平台消息正文。 |
| 共同截止时间 | ModelService 内部的学生尝试与平台尝试受同一 timeout 包围；直接服务测试覆盖65ms＋65ms在100ms总预算内超时。场景外层重复时限已移除，I-2的独立探针确认超时状态与日志同步更新。 |
| 角色边界 | 模型设置与usage需parent；internal/chat、asr需brain；student_id与令牌归属先校验，不因新配置字段扩大权限。 |
| 成功／失败反馈 | 正常学生成功、授权回退、双方失败均记录相应状态；设置页显示最近状态、开关用途和发送内容／平台费用影响；未保存的切换不应影响后端。 |
| 五字段场景合同 | API正文仍只有场景五字段；真实供应商与是否回退放响应头，小程序按不区分大小写的头名显示来源，不把诊断字段存入场景。 |
| 配额 | 验证正文、鉴权后才预留attempt；模型错误、超时、格式失败不增加success；仅SceneConfig通过后标记成功。原20次尝试合同保留。 |
| 午夜与历史 | Store返回预留day并以该day记成功；旧attempts保留、success_count从升级后开始，不用二者之差宣称失败次数。存储实现由另一审查员独立复核，本轮只检查调用链。 |
| usage失败 | 接口失败或非整数响应使usage=null并显示错误，不伪装成0；仍允许手工编辑。迟到请求受页面与课堂身份保护。 |
| 结构化日志 | 公共请求和模型调用使用相同context request_id；常规日志只含固定路由、状态、分类、耗时和进程内学生化名，不写请求体、Authorization或学习文本。 |
| ASR入口 | 角色鉴权后检查媒体类型、2MB流式大小上限、10秒上传等待和WAV格式，合格后才进入适配器；错误音频不调用供应商。脑端旧题与已完成请求回放优先级未由这些公共路由校验改变。 |

## 3. 执行证据与边界

- 初次审查独立执行 `python -m pytest -q -p no:cacheprovider tests/test_review_model_policy.py`：当时16项通过；额外探针仍发现上述未覆盖边界。
- 修复后独立执行 `test_scene_timeout_updates_model_status_usage_and_correlated_error` 与 `test_request_validation_does_not_echo_keys_and_preserves_safe_diagnostics`：4项通过，仅既有Starlette／AnyIO弃用提示。本轮没有重复运行完整Python门禁。
- 修复后独立执行 `node tests_js/review-policy.test.js`：当前14项通过，包含4类生成中编辑和课堂切换边界。
- 修复后重新执行上述独立临时探针，确认请求校验不回显 Key／学习文本、场景超时保存失败状态并关联日志、编辑草稿后刷新实际次数且不跨页面／课堂。

没有使用真实模型账号、外部DNS、线上服务或微信手机。供应商边界由测试适配器控制，因此本报告验证策略、状态和请求隔离，不声明供应商实际可用、微信响应头行为或真实延迟已经验收。三项发现已由对应实测关闭；完整版本门禁结果与目标环境验收仍以本版统一报告为准。
