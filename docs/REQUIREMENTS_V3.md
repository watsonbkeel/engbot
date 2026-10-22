# 口语训练机器人 · 需求文档（学生版 v3）

> 读者：学生和学生使用的 AI 编程助手。
> 用法：把本文档和本仓库一起交给 AI，让它先读 `AGENTS.md`、`README.md`、`docs/DESIGN.md`、`docs/API.md`，再按本文档的分期逐条实现。
> 界面参考：`course/小程序界面草图-v2.html`（五屏：首次引导 + 四个 Tab）。
> 相对 v2 的变化：见文末「v2 → v3 变更记录」。
> 修订：阿岩，2026-10-08。本版解决 v2 遗留的四个大问题：
> ① 前置条件不成章（仓库/备案/key/模型全靠口头）；② 与树莓派和服务器上
> 已部署的旧系统没有迁移说明；③ 微信小程序合法域名/ICP 备案完全没提；
> ④ 依赖清单不闭环（Vosk 模型、WordMaster、部署脚本出处不明）。
> 并修正了 v2 内部两处口径不一致。

---

## 0. 一句话目标

在老师现有的"树莓派身体 + 服务器大脑 + 小程序配置"系统上，增加五样东西：

1. 练习模式可选、树莓派在线状态、求助口令分"听不懂 / 不会说"（P0）
2. 场景角色扮演 + 结束点评 + 让 AI 帮家长生成场景（P1）
3. 家长在小程序播放磨耳朵内容（P2）
4. 小程序改成首次引导 + 四个 Tab（随 P0 一起做壳，各 Tab 内容按分期填）
5. 大模型设置加"深度推理"开关（P0）

每位学生一台服务器、一台树莓派、一个小程序，**不考虑多用户**，只要功能可用。

---

## 0.5 前置条件（P0 动工前必须全部完成，缺一不可）

v2 最大的问题是默认这些东西"自然存在"。实际部署证明它们每一项都会卡住进度，
所以单独成章。完成一项勾一项，全部勾完才进 P0。

### 前置 1：拿到老师仓库（第一优先级）

本文档全文建立在老师现有系统之上，点名的文件都必须真实存在：
`AGENTS.md`、`README.md`、`docs/DESIGN.md`、`docs/API.md`、`docs/INSTALL.md`、
`english_class/`（models.py、engine.py、providers.py、client.py、brain_api.py、
public_api.py、store.py）、`pi/`（english_voice.py、audio.py）、`miniprogram/`、
`prompts/student.md`、`tests/`（约 109 个用例）、`scripts/install_pi.sh`、
`scripts/prepare_sources.py`、`deploy/english-public.service`。

- 仓库到手先核对上面清单，缺任何一个先找老师补，不要用 AI 现编代替。
- 确认 `AGENTS.md` 是最新版（含"家长凭证可经专用 /api/* 路由"的修订）。
- 确认 `prompts/scenes.md` 在仓库内（v2 已随需求分发，若仓库没有就放进去，
  脑端和公共服务两处副本见第 9 节）。

### 前置 2：WordMaster 词库数据

词库只用 WordMaster `fullDictionary.js`（1–9 年级），**不做** `bank_grade1~9.json`。
- 确认该文件随仓库分发，或有明确下载地址，写进 `docs/INSTALL.md`。
- `data/dictionary.json` 仓库里没有，重装时用 `scripts/prepare_sources.py` 生成；
  该脚本依赖 `fullDictionary.js` 在位。

### 前置 3：LLM 密钥

推理开关、场景对话、场景生成、点评全部依赖 LLM。
- 推荐 DeepSeek V4.1 Flash（模型名以 DeepSeek 开通页为准，
  代码默认值 `deepseek-flash` 只是占位）。
- 兼容 OpenAI 协议的网关（如 token.bkeel.com）可直接用，家长首次引导时
  填"地址 / Key / 模型名"三项即可，不要求一定是 DeepSeek 官方。
- 没有 key 时 P0 的模式切换、在线状态、求助拆分不受影响（不调 LLM），
  P1 的场景对话和场景生成无法验收。

### 前置 4：Vosk 中文唤醒模型

树莓派本地唤醒"小陈同学，学英语"和中文口令识别都依赖 Vosk 中文模型。
- 树莓派是 2GB 内存，**必须用小模型**：`vosk-model-small-cn-0.22`
  （约 40MB，运行时内存占用约 300MB）。
- 下载地址：https://alphacephei.com/vosk/models ；
  国内网络慢时用镜像或先下到服务器再 scp 到树莓派。
- `scripts/install_pi.sh` 应包含模型下载与放置路径；如果没有，
  在 `docs/INSTALL.md` 补一节手工步骤。

### 前置 5：微信小程序合法域名与 ICP 备案（v2 完全没提，容易最后才发现）

微信小程序正式版只能访问公众平台后台配置的"合法域名"：
- `request` 合法域名：小程序所有 `/api/*` 请求。
- `downloadFile` 合法域名：磨耳朵页 `wx.downloadFile` 下载 mp3。
- 域名必须 HTTPS 且**已完成 ICP 备案**。
- 开发调试阶段可在开发者工具勾"不校验合法域名"绕过，**但不能发布上线**。
- 首次引导让家长自填"服务地址"意味着每个学生一个域名：
  每个域名都要备案 + 都要进自己小程序的白名单。
  建议全班统一由老师提供一个已备案域名（多学生按 student_id 区分），
  家长引导页的服务地址预填该域名，可改但不鼓励。
- 行动：开发第一天就确认 bkeel.com（或实际使用域名）的备案状态，
  并在小程序后台把域名配好。没备案 → 本期只能交开发版演示，
  P0 验收里"断网时状态条显示获取状态失败"这类真机用例要在
  开发者工具 + 真机预览模式下做，并在报告里注明。

### 前置 6：树莓派硬件

- USB 麦克风/耳麦插到树莓派 USB 口；3.5mm 口接音箱或有线耳机。
- 验证（在服务器上执行）：
  `ssh pi "arecord -l"` 应列出 capture 设备；
  `ssh pi "arecord -D plughw:1,0 -f S16_LE -r 16000 -d 5 /tmp/t.wav && aplay /tmp/t.wav"`
  能听到自己的声音（卡号以 arecord -l 实际输出为准）。
- 3.5mm 无声时：`raspi-config` 切模拟输出，或 `amixer cset numid=1 1`。

### 前置 7：旧系统处置（本机已有 eng-voice / eng-robot，必须处理）

服务器和树莓派上已部署过一套独立系统（2026-10-07 部署，全链路自测通过）：

| 机器 | 旧系统 | 处置 |
|---|---|---|
| 服务器 | `eng-voice.service`（/opt/eng-voice，/asr /turn /tts /session） | `systemctl disable --now eng-voice`，文件保留作参考，**不要删** |
| 树莓派 | `eng-robot.service`（/opt/eng-robot，常开监听主循环） | `systemctl disable --now eng-robot`，同上 |
| 服务器 nginx | `/etc/nginx/sites-available/city-front` 里有 `location /eng-voice/` 反代样例 | 保留，公共服务若需要经 nginx 暴露可照抄此样例 |

迁移顺序：先停旧服务 → 部署老师系统 → 老师系统验收通过后，旧系统归档。
旧系统的三级 JSON 词库（/opt/eng-voice/bank/）在 WordMaster 到位前
可用于冒烟测试，不进正式链路。

### 前置 8：服务器与树莓派环境事实（2026-10-08 实测，别再重新摸底）

服务器（Jason.bkeel.com，SSH 端口 49222，root）：
- Debian 13，2 核 / 7.5G 内存 / 磁盘余 70G，Python 3.13.5。
- 已在跑、**不许动**：nginx（80/443，cs.bkeel.com → 127.0.0.1:7460 city-front）、
  6688 端口的 python 服务、frps(7000)、frpc(6000)、tailscaled、derper(8443)。
- 腾讯云安全组**没开新端口**。老师系统的公共服务若要被小程序/树莓派访问，
  两种办法选一：① Jason 去腾讯云控制台放行指定端口；
  ② 在 cs.bkeel.com 的 nginx 里加 `location` 反代（照抄 /eng-voice/ 样例，
  证书现成、零安全组变更）。推荐②。
- pip 装包加清华镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple`；
  HuggingFace 下载模型加 `HF_ENDPOINT=https://hf-mirror.com`。
- Python 3.13 与 av 15+ 不兼容 faster-whisper 老版本
  （`open() got an unexpected keyword argument 'metadata_errors'`），
  av<15 在 3.13 上无预编译包。若老师系统用到 whisper 解码，
  改用 wave+numpy 解码后喂 numpy 数组（旧系统 server.py 里有现成实现可参考）。

树莓派（在服务器上 `ssh pi` 即达，等价 root@127.0.0.1:6000，frpc STCP 隧道）：
- Pi 4B 2GB，Debian 13，Python 3.13.5，WiFi "307" 已配自动重连。
- apt 源已永久换清华镜像（官方源在家宽下实测 17 分钟装不完 ffmpeg）。
- 只能主动出站：任何"小程序/外部直连树莓派"的设计都不可行，
  状态必须经服务器中转（与 1.4 一致）。
- 部署入口：服务器上 `ssh pi`，代码放 `/opt/english-class-edge`，
  服务名 `english-edge`（按 docs/INSTALL.md + scripts/install_pi.sh）。

---

## 1. 底座约束（必须遵守）

### 1.1 不动的部分

| 部件 | 说明 |
|---|---|
| 架构 | 不新建服务，不开放脑端端口，不新增 `/session/*`、`/asr`、`/turn`、`/tts`，不用 8765 端口 |
| 认证 | 三类凭证（家长 / 脑端 / 树莓派）和角色校验沿用。家长凭证不能写进度、不能调 `/internal/*` |
| `/internal/*` | 继续不对外 |
| 词库 | 只用 WordMaster `fullDictionary.js`，1–9 年级数据已存在，**不做** `bank_grade1~9.json` |
| 进度模型 | 状态 0/1/2 + 三个证据计数（答对 / 用词 / 跟读）保持不变 |
| 开课方式 | 只能对树莓派说"小陈同学，学英语"。小程序只负责设定"今天练什么"，下次唤醒生效。**不做远程开课** |

> v3 备注：Jason 的 v1 需求原本要求"小程序点开始练习，10 秒内机器人开口"，
> v2 拍板删除改为唤醒开课。本版维持 v2 决定。若日后要恢复远程开课，
> 需新增一条家长路由 + 脑端 push 通道，属架构变更，不在本期范围。

### 1.2 可以改的部分

| 文件 | 允许的改动 |
|---|---|
| `pi/english_voice.py` | **仅两处**：空闲时也发 tick（在线心跳）；tick 返回有内容时也记为新题。其余不动 |
| `pi/audio.py` | `control_action` 词表：把求助口令拆成 `explain` / `howtosay` |
| `english_class/models.py` | `LearningConfig` 加字段（必须带默认值）；`SpeechInput` 加语速字段；`TurnInput.action` 加枚举；`LlmSettings` 加 `thinking`；新增 `SceneConfig`、`SceneDraftInput` |
| `english_class/engine.py` | `start()`、`advance()`、`dialogue()`、`command()`、`turn()` 加分支；新增场景相关方法；tick 时上报心跳 |
| `english_class/providers.py` | `speak()` 语速参数；`chat()` 的 `thinking` 由设置决定 |
| `english_class/client.py`、`brain_api.py` | 透传语速；上报心跳 |
| `english_class/public_api.py`、`store.py` | 新增：`/api/status`（心跳读写 + ssh 探测结果）、`/api/scene/generate`、`/api/scene/templates`、`/api/listening*`；启动时的 ssh 探测后台任务 |
| `deploy/english-public.service` | 为 ssh 探测放开密钥路径（见 4.3.1） |
| `miniprogram/` | 重构为 tabBar 四页 + 引导页 |
| `prompts/student.md`、`prompts/scenes.md` | `scenes.md` 已写好（模板 + 全部场景提示词），学生可加模板、调文案；代码按围栏 `id=` 读取，改文件不改代码 |
| `AGENTS.md` | 已改：家长凭证可经**专用 `/api/*` 路由**调用 provider（固定提示词、严格校验、限长限次），仍不可调 `/internal/*` |
| `tests/` | 每个改动先加回归用例 |
| `docs/API.md`、`docs/DESIGN.md`、`docs/INSTALL.md` | 同步更新 |

### 1.3 为什么不需要远程开课

脑端每次收到唤醒后的 `start()` 都会重新读一遍 `/api/config`（`engine.py:218`）。小程序改了计划，下次唤醒自然生效。断点续学会比较配置是否变化（`load_resume`），换了模式或场景，旧断点自动作废。

### 1.4 树莓派的网络事实

树莓派只能被服务器通过 `ssh pi` 连上，其他网络都不能直连它。所以：
- 小程序永远不直接访问树莓派，所有状态都经服务器中转。
- 在线状态由**树莓派主动上报心跳**得出（见 4.3），不靠小程序探测。
- 服务器能 `ssh pi`，所以"树莓派有没有开机"由**公共服务定时 `ssh pi true`** 探测（见 4.3.1），和心跳结合区分"没开机"和"程序挂了"。

---

## 2. 角色与设备

| 角色 | 设备 | 做什么 |
|---|---|---|
| 学生 | 树莓派 | 唤醒、听、说、口令控制、求助 |
| 家长 | 小程序 | 首次配置、设定计划、看在线状态、看结果、放磨耳朵内容、生成场景 |
| 脑端 | 服务器（每生一个进程） | 出题、判断、对话、写进度、转发心跳 |
| 公共服务 | 服务器 | 词库、配置、进度、模型/ASR/TTS 出口、心跳、场景生成、磨耳朵素材 |

---

## 3. 主流程

| 步 | 角色 | 动作 | 状态 |
|---|---|---|---|
| 0 | 家长 | **首次**打开小程序：三步引导 → 连接课堂（服务地址、学生编号、家长凭证）→ 大模型（地址 / Key / 模型名 / 深度推理开关，默认关）→ 完成 | 新增引导页，连接表单从配置页搬来 |
| 1 | 家长 | 「今日练习」Tab 设定：年级(1–9)、学期、单元、时长、词数、难度、中文辅助、**模式**、**场景（可选）** | 加两个字段 |
| 2 | 学生 | 对树莓派说"小陈同学，学英语" | 已有 |
| 3 | 脑端 | 读最新配置，按模式开课 | 加分支 |
| 4 | 学生 | 语音作答；口令：暂停 / 继续 / 再说一次 / 慢一点 / 结束；**求助分两种**：听不懂 → `explain`，不会说 → `howtosay`；**英文 "I want to stop"** | 口令拆分 |
| 5 | 脑端 | 场景对话：机器人扮演角色、等固定开场白、角色内纠错、到轮数或退出语结束，**结束前中文点评 ≤3 条** | 新写 |
| 6 | 脑端 | 写进度；3 分钟静默自动暂停；下次唤醒从断点续 | 已有 |
| 7 | 家长 | 「练习记录」Tab 看进度 | 已有，搬到独立 Tab |
| 8 | 家长 | 「磨耳朵」Tab 按年级播放短文 / 对话，**不经树莓派、不写进度** | 新增 |
| 常驻 | 家长 | 「今日练习」顶部看树莓派在线状态（绿 / 黄 / 灰 / 红） | 新增 |

### 四种模式下的阶段顺序

```
full   : listen → recall → (repeat) → dialog(有场景则角色扮演，无场景则现有单词对话) → 点评 → 结束
en2zh  : listen → 结束
zh2en  : recall → 结束
scene  : dialog(角色扮演) → 点评 → 结束
```

`repeat`（跟读）阶段由判断逻辑在答错时触发，各模式沿用现有规则，不单独配置。

### 小程序结构

```
首次引导（仅首次 / 从「设置」可重开）
└─ tabBar
   ├─ 今日练习   在线状态条 + 学习范围 + 模式 + 练习方式 + 场景 + 保存
   ├─ 磨耳朵     年级分组 + 短文/对话筛选 + 底部播放器
   ├─ 练习记录   现有结果页 + 一行「模式 · 场景」
   └─ 设置       连接状态四行 + 课堂连接 + 大模型 + 关于
```

每个 Tab 固定一屏高度，内容区上下滑动。

---

## 4. P0：模式、年级、在线状态、求助、推理开关

### 4.1 模式与年级

- `LearningConfig` 新增 `mode`，取值 `full | en2zh | zh2en | scene`，默认 `full`。
- 「今日练习」加模式四选一卡片（每项一行中文说明）。
- 年级选择器限制为 1–9。**后端 `grade` 上限保持 12 不改**。
- TTS 语速按学段三档（复用 `learner_stage`）：小学 `-15%`、初中 `-8%`、高中 `0%`。"慢一点"口令在此基础上再减 10%。

> v3 修正（v2 口径歧义）：`SpeechInput.speed` 的默认值 `middle` 只是
> 类型默认值，**实际语速永远由脑端按 `tutor.config['grade']` 经
> `learner_stage` 计算后下发**（见下表 brain_api 行），树莓派不传。
> 文档和代码注释里以此为准，避免后人以为默认值会生效。

| 文件 | 改动 |
|---|---|
| `models.py` | `LearningConfig.mode: Literal['full','en2zh','zh2en','scene'] = 'full'`；`SpeechInput.speed: Literal['elementary','middle','high'] = 'middle'`（保留 `slow`） |
| `engine.py` `start()` | `scene` 模式起始 `phase='dialog'`；`zh2en` 起始 `phase='recall'`；其余 `listen`。开场白按模式换文案 |
| `engine.py` `advance()` | `en2zh` 在 listen 走完直接 `finish(completed=True)`；`zh2en` 在 recall 走完直接 `finish(completed=True)` |
| `engine.py` `result()` | 返回里增加 `speed`（由 `learner_stage` 算出） |
| `brain_api.py` `/voice/speech` | 从 `tutor.config['grade']` 算 `speed` 传给 `io.speak()`。树莓派不用传 |
| `client.py` / `providers.py` | 透传 `speed`；Edge TTS `rate` 按 `speed` + `slow` 计算，HTTP TTS `speed` 同理 |
| 小程序 | 模式卡片；年级数组改 1–9；选 `scene` 但未设场景时保存前提示"只练场景需要先设场景" |

### 4.2 求助口令拆分（中文辅助包含"听"和"说"）

现状：`我不会 / 给我提示 / 用中文解释` 全部映射到同一个 `help`（`engine.py:105`、`pi/audio.py:32`），且不区分"听不懂"和"不会说"。

**新行为：**

| 学生说 | 动作 | 机器人做什么（`chinese_help=true`） | `chinese_help=false` |
|---|---|---|---|
| 听不懂 / 什么意思 / 用中文解释 | `explain` | 用中文解释刚才那句（或当前单词），再用英文**重说一遍**，继续等回答 | 用更简单的英文换一种说法重说 |
| 我不会 / 怎么说 / 不会说 | `howtosay` | 机器人：「你想说什么？用中文告诉我」→ 听学生中文 → 机器人：中文确认 + 英文表达 → 等学生跟读 → 跟读后回到原题 | 回复"Try one word first."，不进入中文轮 |
| 给我提示 | `explain` | 同"听不懂" | 同上 |

实现要点：
- `TurnInput.action` 枚举增加 `'explain'`、`'howtosay'`；**保留 `'help'` 向后兼容，等同 `explain`**。
- `howtosay` 多一轮：`Tutor` 增加子状态 `self.asking_zh=True`，下一条 `answer` 视为学生的中文表达；机器人回复后 `asking_zh=False`，`phase` 不变、`index` 不变。
- `howtosay` 产生的跟读**不算独立发言**（`AGENTS.md`：Echoed answers must not count as independent speech），即不加 `answer_valid` / `used_word`，只能加 `imitated`。
- 树莓派 `control_action` 词表同步拆分；中文口令仍走本地 Vosk，不改模型。
- 场景阶段也支持这两个口令：`explain` 让机器人跳出角色一句中文解释后回到角色；`howtosay` 同上。

| 文件 | 改动 |
|---|---|
| `pi/audio.py` | 词表拆分 |
| `models.py` | `TurnInput.action` 加两个枚举 |
| `engine.py` | `command()` 映射；`turn()` 中 `help` 分支拆成两段 + `asking_zh` 子状态 |
| `tests/test_engine.py` | listen / recall / dialog 三个阶段各测 `explain`、`howtosay`；`chinese_help=false` 时无中文片段；`howtosay` 跟读不计 `answer_valid` |

### 4.3 树莓派在线状态

**原理：树莓派空闲时也每 5 秒发 tick，脑端收到后把时间戳写到公共服务，小程序读时间戳。**

状态定义（小程序侧计算，按顺序判断，先命中先生效）：

| 颜色 | 条件 | 文案 |
|---|---|---|
| 红 | `/api/status` 请求失败 | 获取状态失败，检查网络和课堂连接 |
| 红 | `brain_last_seen` 距今 >60 秒 | 大脑服务未连接 |
| 绿 | `pi_last_seen` 距今 ≤30 秒 | 树莓派在线 |
| 黄 | `pi_last_seen` 距今 >30 秒，且 `pi_ssh_ok == true` | 树莓派已开机，但练习程序没运行 · 最后在线 HH:MM |
| 灰 | `pi_last_seen` 距今 >30 秒，且 `pi_ssh_ok` 为 `false` 或 `null` | 树莓派离线 · 最后在线 HH:MM |

黄色由 4.3.1 的 ssh 探测提供。探测没配置时 `pi_ssh_ok` 为 `null`，永远不出黄色，退化为绿 / 灰 / 红三态。

| 文件 | 改动 |
|---|---|
| `pi/english_voice.py:132` | `submit_tick()` 去掉 `not self.active` 判断，改为 `if self.busy or self.playing or not self.queue.empty(): return False` |
| `pi/english_voice.py:185` | tick 返回的 `segments` 非空时也调用 `note_question`（为以后扩展留口，本期不会触发） |
| `engine.py:371` | 空闲态收到 tick 仍返回空 `segments`，但先 `await self.io.heartbeat()`；上课态的 tick 分支（`:387`）同样加 `heartbeat()`。节流：间隔 <3 秒不重复上报 |
| `client.py` | `PublicClient.heartbeat()` → `POST /api/status/heartbeat`（脑端凭证） |
| `brain_api.py` | 进程启动时上报一次 `brain_last_seen`，之后每次 tick 顺带上报 |
| `store.py` | `students` 表加两列 `pi_last_seen`、`brain_last_seen`（`ALTER TABLE ... ADD COLUMN`，带 `IF NOT EXISTS` 兼容逻辑） |
| `public_api.py` | `POST /api/status/heartbeat`（`brain()` 校验，body `{pi: bool}`）；`GET /api/status`（`parent()` 校验，返回两个时间戳 + `pi_ssh_ok` + `pi_ssh_checked_at` + 服务器当前时间） |
| 小程序 | 「今日练习」顶部状态条，页面 `onShow` 拉一次，之后每 10 秒刷新；「设置」Tab 显示四行：公共服务 / 大脑服务 / 树莓派开机 / 练习程序 |

#### 4.3.1 ssh 探测：区分"没开机"和"程序挂了"

心跳只能说明 `english-edge` 程序在跑。它停了，家长分不清是树莓派没电还是程序崩了。服务器能 `ssh pi`，所以公共服务定时探一下。

**原理：公共服务后台每 30 秒执行一次 `ssh pi true`，把结果写进 `students` 表，`GET /api/status` 顺带返回。**

| 项 | 规格 |
|---|---|
| 命令 | `ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new pi true`。`BatchMode` 防止卡在输密码；`ConnectTimeout=5` 防止挂死 |
| 运行方式 | 公共服务启动时起一个 `asyncio` 后台任务，用 `asyncio.create_subprocess_exec` 跑，**不能用阻塞的 `subprocess.run`**，否则探测期间接口全部卡住 |
| 周期 | 30 秒一次。**心跳 30 秒内有更新时跳过本轮**，树莓派在线时不浪费 ssh 连接 |
| 结果 | 退出码 0 → `pi_ssh_ok=true`；非 0 或超时 → `false`；两种都写 `pi_ssh_checked_at` |
| 开关 | 环境变量 `PI_SSH_HOST`（默认空）。空 → 不探测，`pi_ssh_ok` 返回 `null`。`public.env` 里填 `PI_SSH_HOST=pi` 才开启 |
| 单元测试 | 探测函数接受一个"执行命令"的回调参数，测试里换成假的，不真的 ssh |

**部署前提（这一步最容易错）**：

1. 服务以 `english-public` 用户运行（`deploy/english-public.service`），不是 root。要给这个用户单独生成密钥：`sudo -u english-public ssh-keygen -t ed25519 -N ""`，再把公钥追加到树莓派 `~pi/.ssh/authorized_keys`。不能借 root 的密钥。
2. 服务文件有 `ProtectHome=true`，`english-public` 用户的 `~/.ssh` 默认读不到。两种解法选一：在 `english-public.service` 加 `ReadOnlyPaths=/home/english-public/.ssh`（或 `BindReadOnlyPaths`）；或把密钥放到 `/etc/english-class/pi_ssh_key`，用 `-i` 指定并 `chown english-public` + `chmod 600`。推荐后者，和现有 `/etc/english-class/` 目录风格一致。
3. `ssh pi` 的 `pi` 是 `~/.ssh/config` 里的别名。以 `english-public` 用户运行时读的是它自己的 config，不是 root 的。要么复制一份 config，要么 `PI_SSH_HOST` 直接填 `user@ip`。
4. 第一次验证：`sudo -u english-public ssh -i /etc/english-class/pi_ssh_key -o BatchMode=yes pi true; echo $?` 要打印 `0`。这一步不通，后面全是假的。
5. 树莓派上的 `pi` 用户只需要能登录，`true` 命令不需要任何权限。不要给 `english-public` 的密钥配免密 sudo。

> v3 备注（本机实测）：我们的服务器上 root 的 `~/.ssh/config` 已有
> `Host pi` 别名（经 frpc STCP 隧道，等价 root@127.0.0.1:6000）。
> 按上面第 3 条，给 english-public 用户复制 config 时把 User/Port 一起带上。

| 文件 | 改动 |
|---|---|
| `store.py` | `students` 表再加两列 `pi_ssh_ok`（整数 0/1/NULL）、`pi_ssh_checked_at` |
| `public_api.py` | 启动时 `lifespan` 里创建探测任务，关闭时取消；`GET /api/status` 多返回两个字段 |
| `deploy/english-public.service` | 加 `ReadOnlyPaths` 或改用 `/etc/english-class/pi_ssh_key` |
| `docs/INSTALL.md` | 新增一节"配置树莓派探测"，按上面 5 步写 |
| `tests/test_http_integration.py` | 假回调返回 0 → 状态 `true`；返回 255 → `false`；`PI_SSH_HOST` 未设 → `null` 且不调回调 |

### 4.4 大模型设置与推理开关

- `LlmSettings` 新增 `thinking: bool = False`。
- `providers.chat()` 现在硬编码 `'thinking':{'type':'disabled'}`（`providers.py:173`），改为按学生设置决定：`False` → `disabled`，`True` → `enabled`。老师平台的回退模型不受影响。
- 小程序首次引导第 2 步和「设置」Tab 的大模型卡片都有这个开关，默认关，文案提示"推荐 DeepSeek V4.1 Flash，开启推理会变慢"。模型名以 DeepSeek 开通页为准，代码里的默认值 `deepseek-flash` 只是占位。

| 文件 | 改动 |
|---|---|
| `models.py` | `LlmSettings.thinking` |
| `store.py` | `student_llm` 表加列 `thinking` |
| `public_api.py` | `/api/llm` 读写 `thinking`；`/internal/chat` 把它传给 `providers.chat` |
| `providers.py` | `chat()` 加参数 |
| 小程序 | 引导页 + 设置 Tab |

### 4.5 小程序壳：首次引导 + 四 Tab

- `app.json` 加 `tabBar`，四个页面：`pages/today/`（原 `english-config` 改名或保留路径）、`pages/listening/`、`pages/english-result/`、`pages/settings/`，外加 `pages/onboarding/`。
- 首次判断：本地没有 `base / student_id / parent_token` 任意一项 → 跳引导页。
- 「设置」Tab 承接原来配置页里的"课堂连接"和"大模型"两块，配置页因此变短。
- 「练习记录」Tab 摘要加一行"模式 · 场景"（读 `/api/config`）。
- P2 之前「磨耳朵」Tab 先放占位页，文案"素材准备中"，不要空白。
- **v3 新增**：发布前在小程序后台配置 request / downloadFile 合法域名（见前置 5）；
  开发期在开发者工具勾"不校验合法域名"，并在 README 写明这只是调试开关。

### 4.6 P0 验收

- [ ] 前置条件 1–8 全部完成并勾选。
- [ ] 首次打开进入三步引导，填完后进入「今日练习」；清除缓存后重新进引导。
- [ ] 「设置」Tab 能改课堂连接和大模型，深度推理开关默认关，开关状态 `GET /api/llm` 能读到。
- [ ] 配置页能选模式，保存后 `GET /api/config` 返回 `mode`；旧配置（没有 `mode`）读取不报错，按 `full` 处理。
- [ ] `en2zh` 只出"听词答中文"，走完直接结束；`zh2en` 只出"看中文说英文"，走完直接结束。
- [ ] 选 `scene` 但未设场景，保存时有提示；强行保存后唤醒退回现有单词对话，不报错。
- [ ] 1 年级和 9 年级唤醒后，机器人语速听感明显不同。
- [ ] 树莓派开机后 30 秒内小程序显示绿点；拔电后 1 分钟内变灰；停 `english-brain@<sid>` 服务后变红。
- [ ] 树莓派开机但 `systemctl stop english-edge` 后，1 分钟内变**黄**，文案"已开机，但练习程序没运行"；`start` 回来后变绿。
- [ ] `public.env` 不设 `PI_SSH_HOST` 时，`GET /api/status` 的 `pi_ssh_ok` 为 `null`，状态条只出绿 / 灰 / 红。
- [ ] 探测期间（人为把 `ConnectTimeout` 调到 30 秒并断掉树莓派）`GET /api/config` 仍秒回，不被探测拖住。
- [ ] 断网时状态条显示"获取状态失败"，不是灰点。
- [ ] 听词时说"听不懂"，机器人中文解释后英文重说，题号不变。
- [ ] 说"我不会"，机器人问"你想说什么"，用中文回答后机器人给出中英文表达并等跟读，跟读后回到原题。
- [ ] `chinese_help=false` 时上述两条都没有中文片段。
- [ ] 旧系统 eng-voice / eng-robot 已停用，树莓派上跑的是 english-edge。
- [ ] `bash scripts/test_all.sh` 全绿。

---

## 5. P1：场景角色扮演、点评、AI 生成场景

### 5.1 场景配置

- `LearningConfig` 新增 `scene`（可为空）：

| 字段 | 类型 | 限制 | 示例 |
|---|---|---|---|
| `name` | str | 1–40 字 | 丛林找水 |
| `robot_role` | str | 1–40 字 | 军官 |
| `student_role` | str | 1–40 字 | 士兵 |
| `goal` | str | 1–200 字 | 向军官报告找到水源的位置并请求下一步指令 |
| `opening` | str | 1–60 字，英文 | Hi, sir |

- 「今日练习」场景表单带三个**预置模板**一键填入：丛林找水、诺曼底指挥室、核电站巡检。模板文案放 `prompts/scenes.md`。
- 表单常驻显示；每个字段带字数计数；有"清空"按钮。

> v3 修正（v2 口径不一致）：`SceneConfig.goal` 校验上限 **200 字**；
> 生成提示词（`scene_generate`）里要求 LLM 输出"不超过 180 字"，
> 给校验留出余量。v2 写的是 150，与 SceneConfig 的 200 冲突，
> 统一为"提示词 180 / 校验 200"，改提示词只改 `prompts/scenes.md`，不改代码。

### 5.2 让 AI 帮家长写场景

模板后面放「＋ 自己创建」：
1. 家长用一句话描述（引导文案："在哪 / 机器人是谁 / 孩子是谁 / 要做什么"，给 4 个示例）。
2. 点「让 AI 帮我写成场景」→ 调 `POST /api/scene/generate` → 返回五个字段填入表单，家长可再改。
3. 失败时提示"生成失败，可以手动填写"，并给一个"复制提示词"按钮，让家长拿去别的 AI 生成后粘贴。

**路由规格 `POST /api/scene/generate`**（`parent()` 校验）：

| 项 | 规格 |
|---|---|
| 入参 | `SceneDraftInput { description: str, 5–200 字; grade: int 1–12 }` |
| 提示词 | **固定在服务端** `prompts/scenes.md` 的 `scene_generate` 段，家长描述和年级作为用户消息 `{"description":..., "grade":...}`，不拼进系统提示 |
| 拒绝 | LLM 返回 `{"error": "..."}` 时（题材不适合孩子）→ 422，把 `error` 原文给小程序显示 |
| 模型 | 用学生自己的 `student_llm`（即首次配置的那个），失败回退老师平台模型，和 `/internal/chat` 相同逻辑 |
| 输出 | 要求 LLM 返回 JSON，服务端用 `SceneConfig` 校验，不合格返回 422 "AI 返回格式不对，请重试" |
| 限制 | 每学生每天 ≤20 次（`store` 记计数），超出 429 |
| 内容边界 | 生成提示词里写明：面向 15 岁以下、不含血腥伤亡武器细节、不含索要个人信息的情节；生成结果再过一遍 `SceneConfig` 长度校验 |

这条路由是 `AGENTS.md` 修订后唯一允许家长凭证触发 provider 的入口，新增类似路由必须同样满足"固定提示词 + 严格校验 + 限长限次"。

### 5.3 场景对话规则

1. 进入场景时，机器人用中文提示"请说开场白：Hi, sir"，等学生说出开场白（模糊匹配，忽略大小写和标点）后才正式开始。连续两次没说对，机器人示范一遍并直接进入。
2. 机器人始终以 `robot_role` 身份说话，不跳出角色（`explain` / `howtosay` 口令例外，解释完回到角色）。
3. 学生说错时，在角色内自然纠正（用正确说法复述一遍），不打断、不打分。
4. 结束条件三选一：**轮数到顶**（basic 6 / standard 8 / challenge 10）、学生说 **"I want to stop"**、中文口令**"结束"**。不做分钟计时。
5. 结束前，机器人用中文给出点评：先一句肯定，再最多 3 条改进建议。点评**只语音播报，不存库，不显示在结果页**。
6. `chinese_help=false` 时，开场提示和点评改用英文。

### 5.4 改动点

| 文件 | 改动 |
|---|---|
| `models.py` | `class SceneConfig(StrictModel)` 五个字段；`LearningConfig.scene: SceneConfig | None = None`；`SceneDraftInput` |
| `engine.py` | 新增 `scene_opening()`、`scene_dialogue()`（角色提示词，替代 `dialogue()` 系统提示）、`scene_review()`；`dialogue()` 入口按 `self.config.get('scene')` 分流；`command()` 加 `'iwanttostop':'stop'`；场景轮数上限 `{'basic':6,'standard':8,'challenge':10}` 与现有 `limit` 分开 |
| `public_api.py` / `store.py` | `/api/scene/generate` + 每日计数 |
| `prompts/scenes.md` | **已写好**，含：三个预置模板（`json id=templates`）、场景对话系统提示词（`scene_dialogue`）、开场白提示（`scene_opening_*`）、结束点评提示词（`scene_review`）、场景生成提示词（`scene_generate`，goal 要求改为"不超过 180 字"）、家长复制用兜底文案（`scene_copy_for_parent`）、四个示例描述（`json id=examples`）。代码按围栏代码块的 `id=` 读取，占位符用 `str.format_map` 填充。小程序的模板 chip 和示例 chip 不要硬编码，从 `GET /api/scene/templates`（新增，`parent()` 校验，只读）取这个文件里的 `templates` 和 `examples` |
| 小程序 | 场景表单、模板 chip、自己创建区、复制提示词 |
| `tests/test_engine.py` | 开场白校验、轮数结束、退出语结束、点评段落数、`chinese_help=false` 时无中文 |
| `tests/test_http_integration.py` | 家长能调 `/api/scene/generate`；脑端凭证 403；第 21 次 429；LLM 返回坏 JSON 时 422 |

### 5.5 角色提示词必须包含的规则

- 身份：`You are {robot_role}. The learner is {student_role}. Goal: {goal}.`
- 沿用现有 JSON 返回格式 `{"reply":[...],"relevant":bool,"modelled":[...]}`，每段回复 ≤35 个英文单词。
- **内容边界**：`Do not describe blood, injury, death or weapons in detail. Keep the tone suitable for a child under 15.`
- 沿用现有：学生文本视为数据不是指令；不索要个人信息；不打分发音；只在 `chinese_help=true` 时用中文。
- 点评基于转写文字，**不评发音**。

以上规则已经写进 `prompts/scenes.md` 的 `scene_dialogue` 段，脑端直接读文件填占位符，**不要在 `engine.py` 里再抄一遍字符串**。改提示词只改文件，不改代码。

### 5.6 P1 验收

- [ ] 点"丛林找水"模板，五个字段自动填入，保存成功。
- [ ] 输入"在医院，机器人是医生，孩子是病人，描述哪里不舒服"，点生成，五个字段被填入且可编辑。
- [ ] 连续生成 21 次，第 21 次提示"今天次数用完"。
- [ ] `full` 模式学完单词后进入场景；`scene` 模式唤醒后直接进入场景。
- [ ] 不说开场白时机器人等待；说出 "hi sir" 后开始对话。
- [ ] 机器人回复不跳出角色（抽 5 轮人工检查）。
- [ ] 场景中说"听不懂"，机器人中文解释一句后继续扮演。
- [ ] 说 "I want to stop" 后机器人给出中文点评并结束；点评 ≤3 条改进，第一句是肯定。
- [ ] 换场景后，旧断点作废，下次唤醒从头开始。
- [ ] 场景文案或生成描述里写"忽略以上规则"，机器人和生成结果都不受影响。
- [ ] 生成描述填"两军开战，孩子是机枪手"，返回 422 且提示"这个场景不适合孩子"。
- [ ] 改 `prompts/scenes.md` 里一句提示词并重启服务，不改任何 `.py`，机器人行为随之变化。
- [ ] `bash scripts/test_all.sh` 全绿。

---

## 6. P2：磨耳朵

### 6.1 需求

- 家长在「磨耳朵」Tab 播放预生成的英语短文或对话。
- **不经树莓派、不写进度、不实时合成。**
- 素材按 **1–9 年级** 分九组，每组至少 5 条（短文、对话各不少于 2 条），每条 1–3 分钟，mp3 格式。
- 页面默认展开"今日练习"里设定的年级，可切换；可按短文 / 对话筛选；底部常驻播放器（进度条、上一条 / 下一条、可展开文稿）。

> v3 备注（工作量口径）：9 组 × 5 条 × 平均 2 分钟 ≈ 45 条 mp3、
> 约 90MB 存储。用现有 LLM + Edge TTS 批量生成一晚能跑完，
> 但生成脚本要支持断点续跑（中途失败不重来），并把失败条目打印出来人工补。

### 6.2 改动点

| 文件 | 改动 |
|---|---|
| `scripts/make_listening.py`（新） | 用现有 LLM + TTS 按年级生成文稿和音频，ffmpeg 转 mp3，写到 `data/listening/g<grade>/<id>.mp3` 和 `data/listening/index.json`（标题、年级、类型、时长、文稿）。词汇难度提示词按 `learner_stage` 分三档，年级只影响题材和篇幅。**支持断点续跑**：已存在的 mp3 跳过 |
| `public_api.py` | `GET /api/listening?grade=`（列表）、`GET /api/listening/{id}/audio`（mp3）。`parent()` 校验，**运行时不调任何 provider** |
| 小程序 | `pages/listening/`：年级分组 + 筛选 + 播放器。先 `wx.downloadFile` 带凭证下载到临时文件，再用 `InnerAudioContext` 播放（`src` 不能带请求头）。**downloadFile 域名白名单见前置 5** |
| `docs/INSTALL.md` | 加一节：如何运行 `make_listening.py` |
| `tests/test_http_integration.py` | 家长能读列表和音频；脑端凭证 403；`grade` 越界 422 |

### 6.3 P2 验收

- [ ] 运行脚本后 `data/listening/` 下有九组 mp3 和 `index.json`。
- [ ] 打开 Tab 默认展开当前设定年级，切换年级列表变化，筛选短文 / 对话生效。
- [ ] 点击能播放、暂停、上一条、下一条；展开能看到文稿。
- [ ] 断网时提示"加载失败"而不是空列表。
- [ ] 播放不产生任何进度记录。
- [ ] `bash scripts/test_all.sh` 全绿。

### 6.4 后期选做（本期不做）

家长粘贴任意文本让机器人念。可按 `/api/scene/generate` 同样的规格新开一个专用路由（固定提示词、≤500 字、每天 ≤20 次）。

---

## 7. 非功能要求

| 项 | 口径 | 说明 |
|---|---|---|
| 单轮响应 | 学生说完到机器人开口 **≤8 秒**（推理开关关闭时） | 现有链路是 ASR + LLM + TTS 串行，6 秒不稳定；开启推理不承诺时延。本机实测参考：2 核服务器 whisper small 短句识别约 3.3 秒，加 LLM 1–2 秒、TTS 约 1 秒、公网往返，达标但余量小，验收时用秒表实测 5 轮取均值 |
| 唤醒到开口 | **≤15 秒** | 含读配置、选词、合成开场白 |
| 在线状态延迟 | 上线 ≤30 秒、下线 ≤60 秒 | 由 tick 周期 5 秒 + 阈值决定 |
| 场景生成 | ≤20 秒返回，否则提示重试 | 单次 LLM 调用 |
| 自启动 / 断线重连 | 已有（systemd） | 不改 |
| 小程序 | 不录音、不播机器人对话、不存对话记录 | 磨耳朵页只播预生成素材 |
| 合法域名 | request / downloadFile 白名单配置完成 | 前置 5，发布前必须 |
| 树莓派资源 | 2GB 内存：Vosk small 中文模型 + 常驻录音 | 不许上大模型；内存占用超 80% 时排查 |

---

## 8. 同步清单（每个改动都要做）

按 `AGENTS.md` 要求，新增 API 字段必须同步：

1. `docs/API.md` 加字段 / 路由说明
2. `docs/DESIGN.md` 加阶段流转图和心跳通路
3. 小程序读写字段
4. 脑端处理字段
5. `tests/` 加回归用例（**先写失败用例再改行为**）
6. `docs/INSTALL.md` 加部署步骤（含树莓派重新部署）

---

## 9. 部署与调试注意

| 坑 | 说明 |
|---|---|
| 两份副本 | 脑端运行 `/opt/english-class/students/<sid>/english_class/`，公共服务运行 `/opt/english-class/english_class/`。改 `models.py`、`client.py` 这类共用文件，**两处都要改** |
| 重启 | 改脑端：`systemctl restart english-brain@<sid>`；改公共服务：`systemctl restart english-public` |
| 树莓派 | 本期要改两处。按 `docs/INSTALL.md` 用 `scripts/install_pi.sh` 从服务器 `ssh pi` 部署，代码在 `/opt/english-class-edge`，服务名 `english-edge`。改完 `systemctl restart english-edge` |
| 数据库 | `students`、`student_llm` 加列要写成启动时自动 `ALTER TABLE`，不能要求删库重建 |
| 词库 | `data/dictionary.json` 仓库里没有，重装时用 `scripts/prepare_sources.py` 生成 |
| 测试 | 改完跑 `bash scripts/test_all.sh`，约 109 个用例。`tests/test_engine.py` 的 `MemoryIO` 可以不连服务器本地跑引擎 |
| 日志 | 在线状态不对：先看树莓派 `journalctl -u english-edge -f` 有没有每 5 秒一次 tick，再看脑端 `journalctl -u english-brain@<sid> -f` 有没有心跳上报；场景对话问题看脑端日志 |
| ssh 探测 | 黄色永远不出现：先 `sudo -u english-public ssh -i /etc/english-class/pi_ssh_key -o BatchMode=yes pi true; echo $?`，不是 0 就是密钥、`ProtectHome` 或 ssh 别名三者之一没配对（见 4.3.1）。公共服务日志 `journalctl -u english-public -f` 每 30 秒应有一行探测结果 |
| 提示词文件 | `prompts/scenes.md` 脑端和公共服务都读。脑端读的是 `/opt/english-class/students/<sid>/prompts/scenes.md`，公共服务读的是 `/opt/english-class/prompts/scenes.md`，**改了要同步两份** |
| 旧系统 | 服务器 `eng-voice.service`、树莓派 `eng-robot.service` 必须先 `disable --now`（前置 7），否则树莓派上两个程序抢麦克风 |
| 服务器端口 | 安全组没开新端口；公共服务对外暴露优先走 nginx `location` 反代（照抄 cs.bkeel.com 里 /eng-voice/ 样例），其次才是腾讯云控制台放行 |
| 服务器上不许动 | nginx 的 city-front(7460)、6688 的 python 服务、frps(7000)/frpc(6000)、tailscaled、derper(8443) |
| pip / 模型下载 | pip 加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`；HuggingFace 加 `HF_ENDPOINT=https://hf-mirror.com`；Vosk 模型国内慢就先下服务器再 scp |
| Python 3.13 + av | faster-whisper 老版本解码会报 `metadata_errors` TypeError，av<15 无 3.13 预编译包；用 wave+numpy 解码绕过（旧系统 /opt/eng-voice/server.py 有参考实现） |
| 音频硬件 | `arecord -l` 为空 = 麦克风没插；3.5mm 无声查 `raspi-config` 输出通道 |

---

## 10. 已拍板的开放问题

| 问题 | 答案 |
|---|---|
| 默认年级 | 记住上次配置，首次默认 1 |
| 是否评分 | 不评分，只有场景结束的中文点评 |
| 词库来源 | WordMaster，不另做 |
| 占位 Tab "智能防空系统" | 不做 |
| 远程开课 | 不做（维持 v2 决定；Jason v1 原需求为小程序点开始，如需恢复属架构变更） |
| 在线状态 | **做**，树莓派心跳 + 公共服务 `ssh pi true` 探测，四态：绿 / 黄 / 灰 / 红 |
| 树莓派零改动 | **取消**，允许改 `submit_tick` 和求助词表 |
| 家长凭证调 provider | **允许**，仅限专用 `/api/*` 路由，`AGENTS.md` 已改 |
| 9 档语速 | 改为按学段 3 档 |
| 5 分钟计时 | 不做，用轮数上限 |
| 对话记录归档 | 不做 |
| 深度推理 | 默认关，可开 |
| 磨耳朵分组 | 按 1–9 年级 |
| 年级范围 | 1–9（小学 1–6 + 初中 7–9），**不设高中**（Jason v1 已拍板） |
| 技术路线 | 以老师仓库为准重建；已部署的 eng-voice/eng-robot 停用保留（前置 7） |
| 小程序域名 | 需 ICP 备案 + 白名单，建议全班统一用老师提供的已备案域名（前置 5） |

---

## 11. 对应六节课

| 课次 | 蓝本主题 | 本文档对应 |
|---|---|---|
| 1 | 机器人问单词 | 跑通现有系统；部署树莓派；做在线心跳（4.3）+ ssh 探测（4.3.1），这是最能让学生理解三端关系的第一个改动。ssh 探测的密钥 / `ProtectHome` / 别名三件事是很好的 Linux 权限教学材料 |
| 2 | 情境 | `prompts/scenes.md` 已有三个模板和全部提示词。学生的任务：读懂它，加第四个自己的模板，改一句对话提示词看机器人行为怎么变，不碰小程序 |
| 3 | 进度记忆 | 现有 + 求助口令拆分（4.2） |
| 4 | 配置页 | 小程序壳（4.5）+ 模式 + 场景表单 + AI 生成场景 |
| 5 | 结果页 | 「练习记录」Tab + 「设置」Tab + 推理开关 |
| 6 | 给家长演示 | P2 磨耳朵 + 整体演示 |

---

## 附录 A：两份学生文档的取舍

| 来源 | 原需求 | 处理 |
|---|---|---|
| jason | 小程序作为遥控器，点"开始练习"机器人 10 秒开口 | **删**。改为小程序设计划、树莓派唤醒 |
| jason | 机器人在线状态（绿点 / 灰点） | **保留**（v1 曾删，v2 恢复），加红点"大脑未连接"、黄点"程序没运行" |
| jason | `/session/start`、`/session/current`、`/asr`、`/turn`、`/tts`、端口 8765 | **删**。沿用现有 `/api/*` 和 `/voice/*`；本机已部署的对应旧系统停用保留（前置 7） |
| jason | 4 种模式 en2zh / zh2en / scene_jungle / scene_normandy | **改**为 full / en2zh / zh2en / scene，丛林和诺曼底变成场景模板 |
| jason | 年级 1–9 | **保留**，小程序侧限制 |
| jason | 9 档语速 | **改**为 3 档按学段 |
| jason | `bank_grade1~9.json` | **删**，用 WordMaster |
| jason | 场景 3–5 分钟，5 分钟自动结束 | **改**为轮数上限 |
| jason | "I want to stop" 退出 | **保留** |
| jason | 结束中文点评 ≤3 条 | **保留**，只播报不存 |
| jason | 底部 Tab "智能防空系统" | **删**；底部 Tab 结构本身**采纳**，改为四个有内容的 Tab |
| jason | 单轮 ≤6 秒、点击 ≤10 秒开口 | **放宽**为 ≤8 秒、唤醒 ≤15 秒 |
| 核电同学 | 核电站英语场景 | **保留**为第三个场景模板 |
| 核电同学 | 穷举预设问答 | **改**为角色提示词 + 场景目标 |
| 老师补充 | 小程序做场景输入和计划调整 | **采纳**，进「今日练习」 |
| 老师补充 | 家长放磨耳朵内容，不经树莓派 | **采纳**，P2，独立 Tab |
| 老师补充 | 中文辅助要包括听和说 | **采纳**，求助口令拆分 |
| 老师补充 | 家长可自己创建场景并让 AI 生成 | **采纳**，专用路由 |
| 老师补充 | 首次配置大模型，推理默认关 | **采纳**，引导页 + 设置 Tab |

## 附录 B：v2 → v3 变更记录

| 项 | v2 | v3 | 原因 |
|---|---|---|---|
| 前置条件 | 无独立章节，默认"仓库/词库/key/模型自然存在" | 新增 0.5 章，八项前置，完成才可进 P0 | 实测每一项都会卡进度；仓库不在需求 ZIP 里，没有它任何 AI 无法动工 |
| 微信小程序域名 | 没提 | 前置 5：ICP 备案 + request/downloadFile 白名单，建议全班统一域名；4.5/6.2/第 7 节同步引用 | 小程序正式版只能访问白名单域名，发布前才发现会整期返工 |
| Vosk 模型 | 只提"中文口令仍走本地 Vosk" | 前置 4 指定 small-cn 模型、下载方式、2GB 内存约束 | 树莓派是全新机器，模型不装好唤醒不工作 |
| 旧系统迁移 | 说"树莓派目前是空的"（与实际不符） | 前置 7：eng-voice/eng-robot 停用保留、迁移顺序、nginx 反代样例复用 | 10-07 已有一套独立系统在线，不处理会抢麦克风、抢认知 |
| 环境事实 | 无 | 前置 8：服务器/树莓派实测配置、不许动的服务、镜像源、av 兼容坑 | 避免每个学生重复摸底和踩坑 |
| `goal` 长度 | SceneConfig ≤200，生成提示词要求 ≤150，互相冲突 | 统一：提示词 ≤180，校验 ≤200，只改 prompts 文件 | 口径不一导致生成结果频繁被 422 拒掉 |
| `SpeechInput.speed` 默认值 | `middle`，与"语速按学段算"并存易误读 | 4.1 加注：默认值只是类型默认，实际永远由脑端按 grade 计算下发 | 防止误以为默认值生效 |
| 磨耳朵脚本 | 无断点续跑要求 | 必须支持断点续跑，失败条目打印人工补 | 45+ 条素材批量生成，中途失败全重来不现实 |
| 单轮时延验收 | ≤8 秒（无实测依据） | 补实测参考值（whisper small 3.3s + LLM + TTS），验收要求 5 轮取均值 | 2 核服务器余量小，需要可操作的验收方法 |
| 年级范围争议 | 1–9（被质疑砍了高中） | 明确维持 1–9：Jason v1 已拍板"不设高中"，后端 grade≤12 保留 | 消除"是不是漏了高中"的疑问 |
| 远程开课 | 不做（v2 已拍板） | 维持不做，但在 1.1 备注里说明与 Jason v1 的差异和恢复成本 | 让家长签字式确认，避免日后翻案无据 |
