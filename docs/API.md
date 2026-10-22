# 接口约定 · v0.3.4

公共层数据接口要求查询参数 `student_id` 和 `Authorization: Bearer <本人课堂凭证>`。服务端核对凭证绑定的学生；不能用修改 student_id 的方式访问别人的数据。角色分 parent（家长）和 brain（本人脑端）；Pi 使用独立 EDGE_TOKEN 访问自己的脑端。

## 1. 公共层

| 路径 | 角色 | 功能 |
|---|---|---|
| GET `/health` | 无鉴权 | 服务、版本、词库数；不代表供应商可用 |
| GET `/api/capabilities` | parent | 配置版本、四模式、features、voice_protocol=2 |
| GET `/api/words` | parent / brain | 年级学期词表和练习组 |
| GET / PUT `/api/config` | parent / brain | 配置读写，下一轮生效 |
| GET / PUT / DELETE `/api/llm` | parent | 自带模型、保存前测试、清除回平台 |
| GET `/api/progress` | parent / brain | 本人逐词记录 |
| POST `/api/progress` | brain | 幂等追加学习证据 |
| GET `/api/status` | parent | Pi、脑端心跳与可选 SSH 探测 |
| POST `/api/status/heartbeat` | brain | 脑端报活，pi=true 时同时报 Pi 活跃 |
| GET `/api/scene/usage` | parent | 当日尝试、成功、上限与剩余次数 |
| GET `/api/scene/templates` | parent | 场景模板、示例、复制给外部模型的提示 |
| POST `/api/scene/generate` | parent | 根据学生／家长描述生成可编辑场景草稿 |
| GET `/api/listening` | parent | 指定 1—9 年级的预生成素材列表 |
| GET `/api/listening/{id}/audio` | parent | 鉴权下载 MP3，Cache-Control private/no-store |

### 词表

`grade=1..12`，`semester=1|2`，`unit=0` 全学期，正整数按原顺序每 10 个词分组。返回 words、units、available_terms 和 `unit_kind=ordered_group_not_textbook`。非法范围或无此练习组返回 422，不偷偷回退年级。

### 学习配置

```json
{
  "grade": 1,
  "semester": 1,
  "unit": 0,
  "duration_minutes": 10,
  "practice_words": 3,
  "chinese_help": true,
  "difficulty": "basic",
  "mode": "full",
  "scene": null
}
```

时长允许 5/10/15/20/30，practice_words 为 1—10，难度 basic/standard/challenge，mode 为 full/en2zh/zh2en/scene。严格拒绝未知字段。旧配置缺 mode、scene 时补 full、null。

场景对象必须完整包含以下五个字段：

```json
{
  "name": "在商店",
  "robot_role": "店员",
  "student_role": "顾客",
  "goal": "问候店员，询问商品，说明想买什么并道谢",
  "opening": "Hello!"
}
```

name、robot_role、student_role 各 1—40 字，goal 1—200 字，opening 1—60 字且为英文短句。去除首尾空白后校验。mode=scene 且 scene=null 兼容旧端强制提交；前端提示选择场景，脑端按通用场景处理。

### 自带模型

PUT 正文 `{base_url,model,api_key?,thinking:false,allow_platform_fallback:false}`。thinking 和 allow_platform_fallback 为严格布尔值；GET 只回 key_hint，不回真实密钥。旧行与省略回退字段均为false。GET还返回last_status、last_error、last_used_at，错误原因已脱敏。空 api_key 可沿用同地址已保存密钥；换地址必须提供新密钥。

保存前执行一次真实 JSON 判题格式测试，整个保存验证（含 DNS）最多 20 秒。成功才覆盖旧设置；失败 422，旧设置保留。地址仅允许公网 HTTPS，拒绝用户名密码、查询串、锚点和任何内网／本机解析结果，不跟随重定向。DNS 使用有限工作池，取消请求不会立即放出仍在执行的工作槽。

v0.3.2 的每次自带模型请求把实际连接固定到当次检查通过的公网 IP，不允许 HTTP 客户端再次解析域名；保留原域名 Host、TLS SNI 和证书主机名校验。连接失败可在同一总时限内尝试下一个已验证 IP。自带模型不读取环境代理，须由公共服务直接访问有有效证书的公网 HTTPS 服务；老师在服务器配置的平台模型保留原有网络配置行为。

运行时使用学生已保存模型；请求失败或JSON不是对象时，只有allow_platform_fallback=true才尝试平台模型，否则503/CustomModelUnavailable。无自带配置时使用平台模型。chat返回content、provider、fallback_used；实际回退还带fallback_code与脱敏fallback_reason。两次尝试共享总等待时限，超时更新最近状态并返回Timeout。模型JSON的具体业务语义仍由调用者验证，不合格不能算学习成功。Key按学生绑定认证加密保存在公共库，主密钥不发给脑端或小程序；删除设置明确选择平台模式。

v0.3.3 保持首次请求的 `thinking` 扩展。仅当 HTTP 400 明确拒绝整个 `thinking` 参数、且当前设置为 false 时，移除这一字段并在同一目标和总时限内重试一次；不重新解析域名、不换凭证、不扩大时限。嵌套字段、错误取值、其他参数、鉴权或限流错误不触发此重试。开启深度推理而参数不被支持时，明确提示关闭或换支持的模型，不静默丢弃已开启的偏好。省略扩展后的模型按服务商自身默认行为运行，不等于强制关闭其内置推理。官方协议差异及边界见 [兼容复核](verification/llm-optional-thinking.md)。

### 进度与证据

POST 示例（示例 word_id 并非预置学习结果）：

```json
{
  "word_id":"1a_021",
  "status":1,
  "unclear":false,
  "evidence":{"answer_valid":true,"used_word":false,"imitated":false}
}
```

status 0/1/2/null：已练尚需继续／曾听懂／曾独立说出／不改变档位。数据库保存历史最大档，不因这次答错而降低已达到的档位，不代表当前熟练度或本次考试分数。unclear=true 时 status 必须 null，不能带有效证据。

answer_valid、used_word、imitated 为本次增量，分别累加 valid_count、used_word_count、imitated_count。示范后重复和独立输出分开；没听清单独累计。只有实际练到的词更新。

v0.3.2 仅把符合当前跟读任务的整句／整词匹配或有正确证据的示范后回答计为成功跟读；明确单词跟读匹配刚示范的原词，不自动推导词尾。包含目标词的猜词列表、伪词、示范后的错误使用不增加 imitated_count。valid_count 仍是有效回答次数，不等于独立说出次数；used_word_count 仍是非复制回答含词的次数，不等于正确次数。旧累计记录不重新判定，结果页将历史 imitated_count 中性表述为“累计跟读／模仿记录”。

脑端传 `Idempotency-Key`。同学生、同 key、同内容返回首次结果；同 key 不同内容返回 409。脑端稳定的回合日志保证重试沿用同一判断及写入意图。默认角色校验阻止 parent 伪造进度。

GET 返回 today（按 CLASS_TIMEZONE）、words；每词包括状态、累计次数和 last_practiced_date。不存在的词视作未练，不能把整个服务请求失败当成“全部 0 分”。

结果页“今日记录词”只按 last_practiced_date 筛选词条，其档位和次数仍为历史累计。场景交流可能没有出现选定词，因此无逐词记录不能推出没有完成对话。引擎给模型的本轮 word observations 与求助标记属于内部短期上下文，不增加数据库字段，不向家长宣称新测得的口语等级。

### 心跳与状态

POST 正文 `{"pi":false}` 仅更新 brain_last_seen；`true` 同时更新 pi_last_seen。GET 返回：

```json
{
  "pi_last_seen":null,
  "brain_last_seen":"2026-10-21T12:00:00+08:00",
  "pi_ssh_ok":null,
  "pi_ssh_checked_at":null,
  "server_time":"2026-10-21T12:00:01+08:00"
}
```

前端以 server_time 计算年龄：脑端心跳在 60 秒内、Pi 心跳在 30 秒内才算新鲜；未来时间不当在线。SSH 只使用 60 秒内的明确结果辅助判断，未配置／过期显示未知。多学生 SSH 必须明确映射设备。

### 场景

GET templates 返回 `{templates:[{key,...五字段}],examples:[...],copy_for_parent:"..."}`。所有提示词来自服务端 `prompts/scenes.md`，家长描述只放 user 数据，不拼进 system 规则。

POST generate 正文 `{"description":"孩子想练的具体场景","grade":1}`。description 去空白后 5—200 字，grade 1—12。每学生、按公共层时区每天最多 20 次尝试（失败尝试也计入）；超额 429。总时限 20 秒，超时 503；模型 error 字段以 422 明确显示；不合格五字段格式也返回 422。生成后家长仍可编辑并保存配置。成功响应仍只含原五字段，X-Model-Provider及X-Model-Fallback响应头说明实际路由。

GET usage返回`{day,attempts,successes,limit,remaining,successes_since_version:"0.3.4"}`。successes只在完整场景验证通过后增加，跨午夜归原预留日期；旧尝试保持，成功统计从本版开始，因此不返回不可靠的失败数。手动保存场景不消耗生成尝试。

生成、随后角色对话及结束点评都优先使用该学生保存的同一套模型设置；有效的学生模型可以在平台没有模型 Key 时工作。配置仍保存一个当前场景，生成草稿本身不写配置。小程序“保存并去安排练习”保存场景后选中今日页的场景模式草稿；学生还需保存今日安排，避免自动覆盖其他未保存选项。

v0.3.3 不改场景五字段和上述公共接口。脑端发送给模型的内部上下文新增 `dialogue_budget`，场景模型输出新增可选严格布尔值 `scene_complete`。`completed_turns` 包括当前回答，`remaining_turns` 是本回答后的余量。只有配置场景、至少两轮学生交流、`relevant=true` 且 `scene_complete=true` 时才提前收尾；缺省 false，错误类型拒绝，仍有 6/8/10 轮上限。结束信号不写掌握记录，词汇证据仍按原规则处理。

### 听力

GET `/api/listening?student_id=s001&grade=1`：

```json
{"grade":1,"items":[{"id":"g1_story_01","grade":1,"type":"story","title":"...","duration_seconds":82.416,"transcript":"...","audio_url":"/api/listening/g1_story_01/audio"}]}
```

type 为 story 或 dialogue；duration_seconds 为实测秒数。小程序以带 Authorization 的 downloadFile 下载音频，链接也需 student_id。播放不创建学习记录。缺少索引、文件或非法路径返回 503，不返回伪装正常的空素材。

## 2. 脑端内部能力

`POST /internal/chat`、`/internal/asr?language=en|zh`、`/internal/tts` 只接受 brain 凭证，部署时不公开代理。

- chat 输入 messages 和 json_output，返回 content/provider/fallback_used；实际回退另带安全原因与错误码。
- ASR 输入16kHz、单声道、16bit PCM WAV，0.01—30秒、完整PCM帧、不超过2MB；显式Content-Type接受audio/wav、audio/x-wav、audio/wave、application/octet-stream，缺省兼容旧端，其他类型415。上传最多10秒；每公共服务进程最多4次云端／本地处理，满载503。云端ASR_TIMEOUT默认8秒、本地ASR_LOCAL_TIMEOUT默认30秒；取消或超时不提前释放仍运行的本地工作槽。返回 text、confidence/null、unclear、provider 及可用的供应商 request_id/fallback_reason。静音、错误响应、没有听清分别处理；不伪造置信度。
- TTS 输入 `{segments:[{text,language}],slow:false,speed:"middle"}`，speed 为 elementary/middle/high；返回 WAV。小学/初中/高中有对应基础语速，再叠加 slow。

## 3. Pi → 学生脑端（voice_protocol=2）

`Authorization: Bearer <EDGE_TOKEN>`，不用公共层 brain 或 parent 凭证。

### POST /voice/turn

```json
{
  "request_id":"每次新动作的唯一编号",
  "action":"answer",
  "text":"learner answer",
  "confidence":null,
  "unclear":false,
  "session_id":"上一轮响应中的会话编号",
  "question_id":"上一轮响应中的题目编号"
}
```

action 支持 answer/start/stop/pause/resume/repeat/slow/explain/howtosay/help/tick/played。help 保留为 explain 的旧协议别名。session_id 与 question_id 同时传或同时省；新 Pi 的答案必须带题位。兼容旧文字桥可省题位，不能享有录音题位校验。

开始、停止等会话控制不能因已丢失响应留下的旧题号而被锁住；答案仍严格按当前题位处理。控制词仅在识别可靠时解析，低置信度的“停止”等不改变会话。

跨版本恢复：pending 记录执行版本；v0.3.1 无版本标记的未确认回合或不同版本回合，在原 request_id 重试时只确认原有未确认 record 意图，不重新 ASR／判题。确认完成后返回 `active=false,phase=done` 及明确的升级结束话术，并缓存原编号；再次开始生成新会话。确认失败 503 且保留原 pending。显式 stop 可放弃尚未确认意图并直接结束，已写进度不删除；原编号和 stop 编号各自回放匹配 request_id 的结束回复。无 pending 的旧状态可继续，旧完成回复不改写。

### POST /voice/audio

查询必须包含 request_id、session_id、question_id，正文原始 WAV，不超过 1 MB。相同请求重试先查已完成结果；新的旧题请求返回 409 stale_question，拒绝发生在 ASR 和写入之前。未确认回合尚存时，先恢复原请求或明确停止，不将新的回答混入半完成回合。

当前题位的新录音在创建未确认回合前验证 WAV 格式；不合格返回 422，保持当前题目，Pi 清除这次失败提交后提示重新回答。已完成请求的回放与旧题拒绝仍先于音频校验。

响应包含：ok、active、phase、session_id、question_id、request_id、expected_language、segments、slow、speed、word_index、word_count、dialog_count、help_stage、help_turn、scene_opening_pending、evidence_incomplete。录音另有 recognized_text、asr_provider。

模型缺少可靠的逐词证据时，evidence_incomplete=true，正常交流可以继续，缺失证据的词不升级。此标志只属于当前回合。

### POST /voice/speech

输入 segments/slow/speed，返回 WAV。脑端依据实际学生配置确定学段语速，不能靠客户端伪造语速档。重播只合成已生成文本，不重新提交答案或写进度。

### 心跳、沉默与恢复

脑端独立每 5 秒报活；Pi 空闲时约每 5 秒 tick。played 在播放结束后报告，用于从“问完”开始计算重问时间。20 秒、40 秒沉默分别简短重问一次，约 3 分钟无响应则休息收尾。tick、played 不计为回答。

脑端 `turn-recovery.json` 保存短期恢复状态：首次判题、按顺序完成的 IO、稳定的进度写入 key/正文、最近最多 128 个响应。有效期最长 6 小时，私有原子写入；结束后清除活动会话的完整对话历史。它不是永久对话档案，也不把原始录音写到公共库。

Pi `pending-turn.json` 仅保存当前未确认请求及必要的短期原录音，以同编号跨重启恢复；完成或明确放弃后清理，最长 6 小时。没有配置可写状态目录时只能进程内恢复。systemd 单元已经配置 0700 目录、0600 文件。

词汇续学断点 `resume.json` 是另一层：同配置下 7 天内可从词汇阶段继续；配置变化、过期、完成或成功进入对话后清除。进入下一阶段的请求失败时，不提前删除有用断点。

旧 `/voice/push` 文字桥仍支持。不同消息即使文本相同也产生不同事件；桥如果重试同一投递，应显式提供原 request_id。推荐使用新版 Pi 插件。

## 4. 错误语义

v0.3.4公共接口统一提供`X-Request-ID`；失败正文为`{detail,error_code,request_id}`。参数校验的detail保留loc/type/msg列表，去除会包含提交Key或正文的input/ctx。其他预期错误的detail为可操作字符串。未知运行异常返回安全500/InternalError，不透传栈或供应商细节。脑端原有题位协议错误结构保持。

典型码：InvalidRequest、UnsupportedAudioType、InvalidAudio、AudioUploadTimeout、CustomModelUnavailable、Timeout、SceneAttemptLimit。未知供应商错误码规范到安全字符范围。日志含请求编号、路由模板、学生散列、实际模型类别、回退标记、耗时、结果与错误码，不记录认证头、Key或完整对话。


401 凭证无效；403 学生／角色不符；409 请求冲突、旧题或未确认回合；413 音频过大；422 输入／模型格式不符；429 场景生成配额；503 当前服务或素材无法完成。界面应展示可操作错误，不以成功、0 分或“素材准备中”掩盖鉴权／网络问题。
