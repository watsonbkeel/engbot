# 安装部署 · v0.3.4

按“公共服务 → 一个学生的文字测试 → 六页小程序 → Pi 耳麦 → 完整语音验收”的顺序部署。已有安装请先看 [UPGRADE.md](UPGRADE.md)，首次安装器会拒绝覆盖已有目录。

本次交付是已完成本地回归的源码包，没有替你改动线上服务、数据库或原 aibot。真实设备、账号、网络和模型输出仍需按第 8 节验收。

## 1. 运行位置与依赖

| 内容 | 默认路径 |
|---|---|
| 公共服务源码 | `/opt/english-class` |
| 公共层模型／语音配置 | `/etc/english-class/public.env` |
| 学习数据与学生模型设置 | `/var/lib/english-class/class.sqlite3` |
| 模型凭证主密钥（默认） | `/var/lib/english-class/class.sqlite3.key`，0600，另行备份 |
| 每学生脑端代码和 prompts | `/opt/english-class/students/s001` |
| 脑端服务配置 | `/etc/english-class/students/s001.env` |
| 脑端断点和回合恢复日志 | `/var/lib/english-class-brain/s001` |
| Pi 插件 | `/opt/english-class-edge` |
| Pi 配置 | `/etc/english-class/pi.env` |
| Pi 未确认请求恢复 | `/var/lib/english-class-edge/pending-turn.json` |

自动安装器面向支持 Python 3.11+ 的 Debian/Ubuntu 和 64 位 Raspberry Pi OS，需要系统包与 Python 依赖下载网络。公共层安装 ffmpeg；Pi 使用 ALSA 与中文 Vosk 唤醒。默认公共端口 18090，学生脑端示例端口 9101，均绑定回环地址。

### Mac／本地开发复核

本轮实测环境为Linux/Python3.12.14/Node24.19.0/ffmpeg6.1.1；项目要求Python3.11+。在Mac或Linux先安装Node与ffmpeg（包含ffprobe），然后在主工程运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
bash scripts/test_all.sh
```

脚本按显式PYTHON、项目.venv、python3依次选解释器，缺pytest会在开始时提示。`requirements.txt`是服务运行依赖，`requirements-dev.txt`包含运行与测试依赖，`requirements-voice.txt`补Vosk等服务器语音依赖，Pi依赖由其安装器管理。v0.3.4新增cryptography50.0.2；仅复制源码而不更新依赖会启动失败。Linux/Mac CI已配置但本次未在远端执行。

## 2. 原词库和听力素材

本包已带 `data/dictionary.json`、原 `fullDictionary.js` 和来源摘要。共有 3,919 条词，覆盖 1—12 年级，原文件 Git blob 与锁定版本一致。安装时无需重新下载词库。

后续使用自己的更新词库时执行：

```bash
python3 scripts/prepare_sources.py --dictionary /你的实际路径/WordMaster_SZ/utils/fullDictionary.js
```

导入器不执行 JavaScript。练习组是原顺序每 10 词一组，不是教材单元。

听力文稿和预生成 MP3 位于 `data/listening/`，具体清单和生成命令见 [LISTENING.md](LISTENING.md)。播放只读取文件，不实时请求模型，也不写口语进度。索引或文件缺失时 API 明确返回 503；不要将“缺素材”误判为“该年级没有听力”。

## 3. 首次安装公共服务

```bash
cd /你的实际路径/Eng/aienglishhelper
sudo bash scripts/install_server.sh
sudo systemctl status english-public --no-pager
curl -fsS http://127.0.0.1:18090/health
```

`/health` 应返回 `service=public`、`version=0.3.4` 和词条数。健康检查只验证服务、数据库和词库，不验证真实供应商。

编辑 `/etc/english-class/public.env`，填写你实际有权限使用的模型地址、模型 ID 和密钥：

```ini
LLM_BASE_URL=https://你的实际模型服务/v1
LLM_MODEL=服务实际接受的模型ID
LLM_API_KEY=仅在服务器填写
CLASS_TIMEZONE=Asia/Hong_Kong
```

平台默认关闭思考；家长自带模型的 `thinking` 由小程序单独保存并传入实际调用。模型需支持当前适配器的 OpenAI 兼容 chat/completions 和 JSON 结构化回复。不要直接采用供应商产品显示名称作为模型 ID。

家长自带模型必须由公共服务直接访问公网 HTTPS，并使用可验证的有效证书。v0.3.2 固定连接到已验证 IP，同时保留域名证书校验；自带模型不使用 `HTTP_PROXY`／`HTTPS_PROXY` 等环境代理。老师配置的平台模型保持原有网络行为。如果自带服务只能通过代理到达，改用可直连的地址，或由老师评估后配置为平台模型；不要关闭证书验证。

### 保存学生模型Key

Key测试成功后才写库，并用Fernet认证加密。主密钥默认是DATABASE_PATH后加`.key`，可用LLM_SECRET_KEY_FILE指定独立路径；只给公共服务读取，文件0600。默认systemd仅允许写`/var/lib/english-class`；自定义DB或主密钥路径时需核对目录所有者及ReadWritePaths。主密钥在只读目录时必须提前放好原文件，不能让服务在该目录生成新文件。

数据库与主密钥分别备份，恢复要匹配；旧版升级先读UPGRADE。小程序自带模型回退默认关闭，开启前界面会说明平台数据去向和成本。保存新开关仍要通过真实模型测试；自己的模型当前完全不可用时，若希望明确切回平台，可删除保存的自带设置，不会假装测试通过。

### ASR 与实时 TTS

默认 ASR 是 Vosk，必须准备中英文模型；Pi 本地中文模型只负责唤醒，不替代公共层英文识别：

```bash
cd /opt/english-class
sudo .venv/bin/python scripts/download_models.py --language both --dest /opt/english-class/models
```

也可按 `deploy/public.env.example` 配置兼容 HTTP ASR 或腾讯云 ASR，并保留本机 Vosk 降级。ASR错误、静音和有效识别是不同状态；日志不包含音频或识别正文。默认云端ASR_TIMEOUT=8、本地ASR_LOCAL_TIMEOUT=30，每进程同时最多4次处理；满载明确503。16kHz单声道16bit PCM WAV限30秒，上传限10秒。

实时朗读支持 Edge TTS 和兼容 HTTP TTS。默认 Edge 通道必须在你的服务器网络中可用；离线听力 MP3 可播放，不代表实时对话 TTS 已通过。HTTP TTS 需支持中英文本。小学／初中／高中语速分别约为基准的 85%／92%／100%，请求“慢一点”进一步降低速度。

```bash
sudo systemctl restart english-public
sudo journalctl -u english-public -n 50 --no-pager
```

### 可选设备电源探测

心跳无须 SSH：脑端独立报活，Pi 空闲时也会发送 tick。仅当你希望区分“Pi 开机但插件没运行”时，配置服务专用 SSH 主机别名和密钥。

单学生可设 `PI_SSH_HOST=pi`；多学生必须设 `PI_SSH_HOSTS={"s001":"pi-one","s002":"pi-two"}`。没有明确映射的学生显示未知，不能把一台 Pi 的结果套给全班。

将专用配置和密钥放在 `/etc/english-class/pi_ssh_config`、`/etc/english-class/pi_ssh_key`，由 `english-public` 可读，私钥权限 0640、root:english-public；known_hosts 默认在 `/var/lib/english-class/pi_known_hosts`。服务开启 `ProtectHome`，不要引用 `/root/.ssh`。程序每 30 秒异步检查，单次最多约 7 秒，最近 30 秒有 Pi 心跳时不探测。SSH 失败仅代表没有确认连通，不等同于确认断电。

## 4. 创建一个学生与反向代理

```bash
cd /opt/english-class
sudo bash scripts/create_student.sh s001 9101 \
  https://class.your-domain.tld \
  https://class.your-domain.tld/students/s001
```

以上域名是占位，请换成你自己的 HTTPS 域名。凭证导出到 `/root/english-class-students/s001/`：

- `brain.env` 留在服务器；它允许本人脑端写进度、调用模型。
- `pi.env` 只交给该学生 Pi；它只访问本人脑端。
- `english-env.local.js` 放入本人小程序的 `utils/`，只含家长凭证。

不同角色凭证不能混用。代码包不带共用密码。已有同名学生或端口会拒绝覆盖。

将 `deploy/nginx-locations.conf.example` 合并到你已有 HTTPS server。`/api/` 指向公共层；`/students/s001/` 指向 9101 并去掉学生前缀；`/internal/` 不公开。先 `nginx -t` 再 reload。不要把回环端口直接开放到公网。

## 5. 先做文字流程验证

在服务器复制 `pi.env` 为 `pi-local.env`，仅把副本的 `BRAIN_URL` 改成 `http://127.0.0.1:9101`、`ALLOW_INSECURE_HTTP=1`，不把这份副本发给远程 Pi。

```bash
cd /opt/english-class
sudo .venv/bin/python -m pi.english_voice \
  --env /root/english-class-students/s001/pi-local.env --text --no-audio
```

输入 `/start`，按照实际题目作答；尝试“这是什么意思”“我不会说”“再说一次”“I want to stop”，确认帮助后回原任务、停止后有收尾。在小程序分别保存四种模式后重新开始测试。此方式仍调用真实文本模型；缺少配置会明确报错，不使用测试替身。

## 6. 六页小程序

微信开发者工具导入 `miniprogram/`。使用自己的合法 AppID 和开发权限，`touristappid` 仅是占位。可以放入本人 `english-env.local.js`，也可以在 onboarding 填课堂根地址、学生 ID 和家长凭证。候选连接通过后才写入本地。

微信后台需要配置公共 HTTPS 域名为 **request 合法域名和 downloadFile 合法域名**，后者用于鉴权下载听力 MP3。真实手机不依赖开发者工具的“忽略域名检查”。

首次连接 → today 保存配置 → scenes 选模板或生成并编辑 → 返回确认草稿仍在 → 保存 → Pi 开始新一轮 → english-result 查看实际记录。配置只影响下一轮。`scene` 模式无场景时页面应提示；兼容旧客户端强制提交的空场景配置时，脑端使用通用场景。

构建独立目录或非破坏性合入原 WordMaster_SZ 的准确参数见 `python3 scripts/build_miniprogram.py --help` 与小程序内导入说明。所有构建都以本项目六页源码为来源；合并输出必须是新目录，原项目不被覆盖。

## 7. 安装 Pi 插件

先用 `arecord -l`、`aplay -l` 确认 USB 耳麦。在本人 `pi.env` 配置稳定的 ALSA 声卡名，检查 `BRAIN_URL` 是从 Pi 可达的 HTTPS 地址。

```bash
cd /你的实际路径/Eng/aienglishhelper
sudo bash scripts/install_pi.sh --env /你的实际路径/s001/pi.env
# 已有中文 Vosk 模型可加 --model /实际模型目录
```

安装完成不自动占用麦克风。公共层、文字流程和连接确认无误后，再明确切换：

```bash
sudo python3 /opt/english-class-edge/scripts/course_mode.py on
sudo journalctl -u english-edge -f
```

该命令按原项目标准服务名暂停 `nox-voice.service`；`nox-body`、`nox-bridge` 仍保留。恢复用 `course_mode.py off`。若原环境改过服务名，先确认实际麦克风使用者。

“小陈同学，学英语”开始课程；单说“小陈同学”可进入原机器人聊天，需原 bridge 可用。在课中可重复、解释、表达帮助、暂停或停止。录音结束等待已放宽，降低思考短暂停顿被截断的概率；实际阈值仍按耳麦校准。

新版脑端 `/voice/audio` 要求会话和题目编号，必须配套升级 Pi。网络异常后 Pi 先恢复同一请求，确认前不拿新编号重复提交旧录音。明确停止会放弃未完成提示，已确认的学习记录保留。

## 8. 真机验收（下载后执行）

| 验收项 | 通过条件 |
|---|---|
| 自带模型与回退 | 本人模型成功；失败且开关关闭时不换平台；明确开启后回退并显示实际路由 |
| 自定义场景 | 描述、生成、检查、保存、安排、逐轮练习、求助、自然收尾可完成；请求／成功／剩余次数与结果一致 |
| 四模式 | 每种模式按相应路径开始并结束，不误入其他模式 |
| 帮助 | 解释不算回答；中文意图→英文示范→跟读→原题可完成 |
| 记录 | 真正独立回答可升级；跟读和失败不被当成独立掌握；旧最高档保留 |
| 断网 | 当前请求可恢复且不重复计次；旧题录音不污染下一题 |
| 语音 | 儿童真实音量、口音和停顿下，能识别、播放、重复和停止 |
| 小程序 | 真手机保存、草稿、结果、状态、听力下载播放均可用；退出听力页停播 |
| 体验延迟 | 关闭思考，连续 5 轮平均响应不超过 v3 的 8 秒目标；唤醒到开场不超过 15 秒 |
| 共存 | 课程模式切入和切回后原 aibot 正常，设备未被两个程序同时占用 |

以上硬件、真实供应商与延迟指标未在本次环境实测，不能用单元测试时长替代。

## 9. 排错

| 现象 | 处理方向 |
|---|---|
| 401/403 | 核对角色、student_id 和本地保存的连接；不要混用凭证 |
| 409 stale_question | 旧题录音已被安全拒绝；听当前题后重新回答 |
| 409 上一回合尚未确认 | 用 Pi 的原请求恢复；无法恢复时明确结束后重开 |
| 422 录音格式 | 重新录制当前题；检查 16kHz、单声道、16 位 PCM WAV 和录音文件是否截断 |
| 422 配置／场景失败 | 查看具体字段提示；确认前后端都是本包版本 |
| 429 场景生成次数 | 每学生每天最多 20 次尝试，可手动编辑场景 |
| 503 素材缺失 | 检查 listening 索引和文件、服务用户读权限 |
| 503 模型／语音 | 记录反馈编号；核对供应商、JSON支持、限额、回退选择与ASR并发。不要上传Key或儿童对话正文 |
| 启动报主密钥缺失／不匹配 | 保留故障库，恢复匹配的原主密钥；不要删文件或生成新Key试图解密旧数据 |
| 状态未知 | 检查心跳；SSH 未配置、过期或时钟异常不会假报在线 |
| 更新后行为没变 | 每学生脑端运行自己的副本；公共模板更新不会自动覆盖它 |

日志：`journalctl -u english-public`、`journalctl -u english-brain@s001`、Pi 上 `journalctl -u english-edge`。分享排错日志前去除凭证；无需发送原始儿童录音或完整个人配置。
