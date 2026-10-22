# 升级到 v0.3.4

本包没有替你操作线上服务。它在v0.3.3的场景教学流程上修复运行边界与凭证存储；**本版有数据库迁移，不能再沿用v0.3.3“通常只回退代码”的做法。** 先读完备份与回滚部分，再在没有孩子练习的时间升级。

## 1. 行为变化

| 变化 | 对现有课堂的影响 |
|---|---|
| 学生模型Key认证加密 | 首次打开旧库时转换，主密钥默认保存在`DATABASE_PATH + '.key'`；数据库和主密钥必须分别备份。 |
| 回退默认关闭 | 旧学生迁移后`allow_platform_fallback=false`。自己的模型出错时不自动换平台；家长明确开启并测试保存后才允许。 |
| 尝试与成功分开显示 | 原每天20次尝试不变，失败也占用；旧尝试保留，成功数从本版启用后统计。 |
| 新依赖 | 必须更新`requirements.txt`，包含`cryptography==50.0.2`。语音依赖仍按`requirements-voice.txt`。 |
| ASR处理边界 | 原WAV格式／时长校验保留，补类型、上传超时、每进程4个处理槽与`ASR_LOCAL_TIMEOUT=30`。 |
| 连接与轮询 | 脑端复用HTTP池；设置／今日页失败退避、隐藏暂停，旧课堂响应不能更新新页面。 |
| API兼容 | 场景仍为五字段，`config_version=3`、`voice_protocol=2`保留；新增回退开关、用量接口、请求ID。 |

公共服务、各学生脑端、Pi共享模块与小程序应配套更新。每学生脑端运行自己的代码副本，更新公共目录不会自动覆盖`/opt/english-class/students/<sid>/english_class`。

## 2. 先在解压目录复跑

```bash
cd /你的实际路径/Eng/aienglishhelper
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
bash scripts/test_all.sh
```

Python需3.11+，同时需要Node与ffmpeg/ffprobe。脚本会使用项目`.venv`并打印版本；也可通过`PYTHON=/完整路径/python`明确指定。测试只用临时数据，不需要真实Key。包内实测记录见[TEST_REPORT.md](TEST_REPORT.md)，原Mac上的两项听力错误根因见[REVIEW_V034.md](REVIEW_V034.md)。

## 3. 结束课程，暂停本项目并备份

先明确结束当前练习，记录实际学生服务清单，再停止`english-public`及本次升级的所有`english-brain@学生ID`，同时暂停其他会打开同一SQLite的旧CLI、监控查询或备份读取任务。不要停止无关服务，也不要重建已有学生。

例如只有s001时：

```bash
sudo systemctl stop english-brain@s001.service english-public.service
```

备份旧代码、学生个性化prompts、服务单元、`/etc/english-class`、脑端／Pi状态目录和Pi配置。数据库备份应使用SQLite backup API；仅复制主文件可能遗漏WAL。以下示例读取现有公共环境文件中的实际数据库路径，不执行其中的shell文本，不打印凭证：

```bash
cd /opt/english-class
sudo .venv/bin/python - <<'PYBACKUP'
import datetime, os, sqlite3
from contextlib import closing
from pathlib import Path
from english_class.run import load_env
os.umask(0o077)
load_env(Path('/etc/english-class/public.env'))
database_path=os.environ.get('DATABASE_PATH')
if not database_path:
    raise SystemExit('请先在public.env明确实际DATABASE_PATH，再执行备份')
source=Path(database_path).resolve()
assert source.is_file(), '数据库不存在，请先核对路径'
folder=Path('/root')/('english-class-before-v034-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
folder.mkdir(mode=0o700)
target=folder/'class.sqlite3'
with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(target)) as dst:
    src.backup(dst)
os.chmod(target,0o600)
print('数据库备份：',target)
PYBACKUP
```

这是升级前备份，可能仍包含旧版明文Key，应作为凭证材料私密保存。若原来已经使用本版或此前迁移过，还必须在另一受控位置备份匹配的原主密钥；不要把“数据库＋主密钥”一起作为脱敏材料对外发送。

## 4. 合并代码、依赖与配置

保留生产配置、数据库、凭证、模型权重和状态目录，合并本包源码与文档；不要把整份解压目录直接覆盖运行数据。按新`requirements.txt`更新公共服务虚拟环境，需要本地Vosk／Edge时同时更新`requirements-voice.txt`。每个学生脑端的完整`english_class/`也要更新，保留其个性化prompts。Pi合并本包`pi/`与引用的共享模块，保留本人pi.env和耳麦配置。

`LLM_SECRET_KEY_FILE`留空时，新版自动在`DATABASE_PATH + '.key'`生成一次主密钥。默认部署目录`/var/lib/english-class`已经只给公共服务用户使用。新目录0700，数据库、辅助文件与主密钥0600。已有目录不会被程序擅自改权限，管理员仍需核对所有者与目录隔离。

如果要把主密钥改放其他路径，必须使用同一个原文件；停止服务后原样复制、设置0600和`english-public`所有者，再设置环境变量。`ProtectSystem=strict`下的`/etc`通常只读，所以要提前准备主密钥，不能要求公共服务在那里自动新建。自定义数据库目录还须配置systemd的`ReadWritePaths`和所有者。公共服务和CLI必须读同一份环境文件；本版安装／创建学生脚本已统一使用`--env`，不再固定覆盖数据库或词库路径。

新增`ASR_LOCAL_TIMEOUT=30`可留默认；`ASR_TIMEOUT=8`现在明确是云端预算，本地回退另有等待上限。每进程最多4个识别任务，多进程部署须另算总并发。原自带模型仍要求可直连的公网HTTPS和有效证书，不读取环境代理；不要通过关闭TLS校验排错。

## 5. 首次启动与迁移检查

先仅启动公共服务，确认日志没有迁移、权限或主密钥错误：

```bash
sudo systemctl start english-public.service
sudo systemctl status english-public.service --no-pager
curl -fsS http://127.0.0.1:18090/health
```

端口按实际public.env调整。health应为`version=0.3.4`、`service=public`，词库数与原库一致；这只验证服务／数据，不验证真实供应商。

迁移分为三次登记：1保留并补齐原表；2加密旧Key、增加回退选择与成功计数；3完成空闲页重建和WAL截断。过程用独立`.migration.lock`串行，SQL变更使用`BEGIN IMMEDIATE`。保留足够临时磁盘空间。若旧读事务导致WAL清理失败，启动明确报错；关闭旧连接后再次启动，会使用原主密钥继续清理。**不要删除数据库、主密钥或手工改schema版本来绕过失败。**

已迁移库缺失或损坏主密钥会阻止启动；存在已保存模型密文时，不匹配的主密钥也会拒绝启动，不会生成一把新Key覆盖。若所有学生模型设置都已删除，目前只能验证文件存在且格式有效，无法判断一把格式有效的Key是否为历史原Key，因此仍须保管原文件并保持备份配套。先保留现场，从备份恢复匹配的原文件；丢失原主密钥无法通过密文还原模型Key。损坏密文也需从受控备份恢复或由维护人员做有记录的修复，不要对整个学生库重置。

确认旧学生、课堂凭证、学习进度与配置保持，然后为**迁移后的数据库**做一次新的SQLite一致备份，并将生成的**原主密钥另行备份**。两份备份必须成对可恢复；记录只写路径、时间、版本，不写密钥内容。旧备份、文件系统快照和存储介质残留不会被本次迁移物理擦除。

## 6. 恢复脑端、Pi和小程序

公共服务确认正常后再启学生脑端与Pi。微信开发者工具导入新的`小程序-english-helper/`或主工程`miniprogram/`；两者同源。保留自己的AppID和本人课堂连接，重新编译，核对request／downloadFile合法域名。

本版版本号变化仍使用既有跨版本回合策略：升级时若有旧版未确认请求，先按旧日志的原载荷与幂等键确认尚未确认的学习写入；成功后明确收尾并提示重新开始，不用新提示词重新判断旧回答。失败时保留原请求；明确停止可以放弃未确认意图，已经写入的记录保留。无未确认回合的旧状态按已有迁移规则继续。详见[API.md](API.md)，不是未完成场景的无缝续答保证。

## 7. 重点验收

1. 小程序可读取旧配置与学习记录；按真实数据核对，不能把网络失败当0分。
2. 自己的模型保存验证、场景生成和逐轮对话可用；失败且回退关闭时明确提示，不换平台。
3. 明确开启回退后，让自己的测试供应商失败，核对实际平台标记与设置页最近状态；只有本人有权限的测试账号用于此验收。
4. 场景失败增加尝试而不增加成功；手动编辑不占次数；生成中修改草稿不被旧回复覆盖，次数仍刷新。
5. 学生当店员／采访者的场景保留提问权，帮助后回任务，核心目标完成并自然告别后进入点评。
6. 真机录音、重听、慢速、停止与Pi恢复正常；非法录音明确报错；页面退出停止轮询和听力播放。
7. 每次失败只记录请求编号、错误码、版本和耗时，不把Key或儿童完整对话贴入日志报告。

完整设备、网络、模型与听感矩阵见[INSTALL.md](INSTALL.md)第8节。自动化测试不能替代这些真实目标环境验收。

## 8. 回滚限制

**v0.3.3不识别v0.3.4加密后的学生模型Key；不要只还原代码并继续指向已迁移的库。** 需要回退时，先停止本项目相关服务，保留当前数据库、匹配主密钥、状态目录和错误证据。恢复升级前匹配版本的代码、配置与数据库，并核对相应学生脑端／Pi版本。

恢复前停止所有打开该数据库的进程，归档当前数据库、辅助文件和匹配主密钥。不要直接用备份覆盖仍带当前`-wal`、`-shm`或`-journal`的数据库路径；应在干净目标中恢复SQLite一致备份，避免混用另一份数据库的辅助文件。数据库和主密钥设为公共服务用户（默认`english-public`）所有、权限0600，目录权限及systemd可写路径核对无误后再启动。恢复v0.3.4含模型密文的备份时，必须使用该备份匹配的原主密钥；v0.3.3旧明文备份没有新增主密钥要求。

恢复升级前数据库会失去备份之后的新记录，不会自动合并。若已经产生重要新记录，优先在保留v0.3.4数据和主密钥的基础上修复前进，或由维护者制定受控数据恢复；不要自动覆盖。主密钥没有在线轮换入口，供应商Key替换仍通过设置页测试后保存，真正撤销旧Key需到供应商控制台操作。

上一版无数据库变化的升级说明仅作为历史保存在[history/v0.3.3-UPGRADE.md](history/v0.3.3-UPGRADE.md)，不适用于本次回滚。
