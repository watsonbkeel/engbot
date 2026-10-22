# 代码结构 · v0.3.4

| 模块 | 职责 |
|---|---|
| `models.py` | 严格校验配置、场景、thinking、语速和题位协议 |
| `dictionary.py` / `sources.py` | 解析原词库、保持原 word_id、非破坏性构建小程序 |
| `store.py` | SQLite进度、幂等写入、配置、心跳、生成尝试与成功计数 |
| `migrations.py` | 版本登记、独立迁移锁、旧库加密与可恢复清理 |
| `secret_store.py` | 按学生绑定的凭证认证加密、主密钥与文件权限 |
| `llm_service.py` | 学生模型选择、明确授权的平台回退、统一截止时间 |
| `diagnostics.py` | 公共请求编号、安全错误边界与脱敏结构化日志 |
| `public_api.py` | 家长 API、脑端内部能力、角色和学生范围校验 |
| `scene_prompts.py` / `prompts/scenes.md` | 唯一的场景模板、生成与教学提示词来源 |
| `listening.py` | 校验并提供预生成音频，不在请求时生成音频 |
| `status.py` | 可选的异步 SSH 探测，按学生设备映射 |
| `providers.py` | 真实模型、ASR、TTS 适配、超时与错误格式归一 |
| `engine.py` | 四种模式、求助回原题、逐词学习证据、结束点评 |
| `turn_recovery.py` | 短期回合日志、IO 重放、稳定写入意图和响应缓存 |
| `brain_api.py` | 学生会话串行化、题位校验、心跳、脑端路由 |
| `client.py` | 本人凭证、同事件循环HTTP连接池与aclose；脑端lifespan负责关闭 |
| `pi/audio.py` | 录音、VAD、声卡发现、控制词 |
| `pi/english_voice.py` | Pi 交互、语音播放、同请求恢复、短期未确认录音 |

## 实际小程序

`miniprogram/app.json` 定义六页：初次连接 onboarding、今日练习 today、场景 scenes、设置 settings、听力 listening、结果 english-result。构建器使用这个目录；测试也载入这些页面，避免旧两页测试与交付代码分离。

`utils/english-api.js` 管理鉴权和连接候选验证；`page-state.js` 管理页面／课堂代际和请求lane；`status-poller.js` 负责单一轮询调度、退避和暂停；`pi-status.js` 将服务端时间和心跳映射为状态；`english-view.js` 管理展示和校验。

`pages/scenes/scene-flow.js` 只管理当前课堂的短期页面交接：场景选择、今日未保存草稿、前往模型设置时的场景编辑草稿。它不存 API Key，不写服务器配置，不持久化到本地存储；保存安排仍由今日页执行。

`tests/manual_scene_simulation.py` 是手工 GPT 模拟专用桥，必须由外部测试执行者回答文件队列，正式服务不导入它。普通回归无需运行该脚本；它的20秒场景超时在手工模拟中被测试专用延长，不能用于衡量真实模型延迟。

## 修改时应保持的约束

1. 场景和学生文字作为不可信数据传入模型；不能覆盖服务端系统规则。
2. 有帮助的模仿和独立表达分开记录；语音没听清不当答错；不能从 ASR 文本生成精确发音评分。
3. 配置、课程引擎、Pi 和前端字段必须配套更新；新增行为先写能复现问题的回归。
4. `tests/` 中的模型与音频替身不能被运行时代码导入。
5. 同请求重试必须复用请求编号和题位；新回答必须新编号。进度只由 brain 身份写入。
6. 恢复日志是短期可靠性状态，不能扩展成默认永久保存儿童语音或对话历史的功能。
