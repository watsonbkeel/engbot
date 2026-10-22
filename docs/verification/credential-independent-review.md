# v0.3.4 凭证存储与部署联动：独立复核

日期：2026-10-21。基线提交：`b0a85e54c3b3815306b717fcaaa4980a5b433ce9`。

## 角色与范围

本复核由本轮运行时边界任务的审查者执行，检查另一实现任务新增的凭证存储、迁移和部署联动代码；审查者没有修改本范围的生产实现或回归测试。发现提交给主任务与凭证实现负责人，由后者修复，再由审查者独立复验。本文件是本复核唯一写入的项目文件。

检查文件：[secret_store.py](../../english_class/secret_store.py)、[migrations.py](../../english_class/migrations.py)、[store.py](../../english_class/store.py)、[cli.py](../../english_class/cli.py)、[install_server.sh](../../scripts/install_server.sh)、[create_student.sh](../../scripts/create_student.sh)、[public.env.example](../../deploy/public.env.example)、凭证存储／CLI 测试及[实现说明](credential-storage.md)。

所有探针使用虚构凭证、临时 SQLite 和本机子进程。未部署、未接触真实供应商账号；没有执行安装脚本的 apt、用户管理或 systemd 操作。

## 最终结论

**在本次代码、测试与本地独立探针覆盖的范围内，无剩余 Important 问题。** 初次发现的 C1 和 C2 均已由凭证实现负责人修复，并通过审查者独立复验。修复后专项回归 **22 通过**；真实跨进程 SQLite 互斥、迁移提交后强制退出及错／缺主密钥恢复、自定义数据库的实际创建学生 CLI 均通过，具体证据见文末。

结论限于本次检查的存储与部署命令边界；全项目门禁由主任务统一记录。本复核没有执行真实 systemd 安装、真实云账号请求、其他操作系统矩阵或磁盘级历史快照清除验证。

## 初次复核结论

初次专项测试 `tests/test_credential_storage.py tests/test_credential_cli.py`：**20 通过**。随后三组独立探针确认 1 个新 Important 问题及 1 个已有部署联动缺陷；主任务已授权实现负责人修复两者。其余关键存储边界见后文。

### C1 · Important：权限检查关闭原始文件描述符，破坏 SQLite 写锁

初次实现中，`secure_database_files` 对数据库及 `-wal`／`-shm`／`-journal` 文件调用 `private_file`，随后直接 `os.close(fd)`；`migration_lock` 同样以数据库本体为 flock 文件。这些独立于 SQLite 的原始文件描述符关闭操作，会释放该进程对同一 inode 持有的 POSIX 记录锁。

使用真实 Store、SQLite 和独立 Python 子进程复现：

1. 父进程保持 `Store.connect()`，执行 `BEGIN IMMEDIATE` 并更新学生状态，不提交。
2. 子进程尝试 `BEGIN IMMEDIATE` 加写入，得到 `OperationalError: database is locked`，符合预期。
3. 父进程调用 `secure_database_files(path)`。
4. 相同子进程操作立即成功并提交，输出 `WRITER_ADMITTED`；父连接此时 `con.in_transaction` 仍为 true。

```text
before_private_file_open_close: OperationalError database is locked
after_private_file_open_close: WRITER_ADMITTED
original_transaction_still_open: True
final_readable_state: ('child-writer',)
integrity_check: ('ok',)
```

该探针最后主动回滚父事务，未把它当作“已复现物理数据库损坏”；实际证据是写事务排他性被破坏，存在并发写入和进度覆盖风险。原有“4 个线程同时启动 Store”测试不能覆盖这一跨进程竞争场景。

机制依据也已核对 SQLite 官方文档 [How To Corrupt An SQLite Database File，第2.2节](https://www.sqlite.org/howtocorrupt.html)：同一进程绕过 SQLite 后自行关闭对应文件 fd，会使 SQLite 无从感知自己的记录锁已被撤销。该来源用于解释探针结果，结论不依赖仅凭文档推测。

修复要求：迁移锁使用独立 sidecar；对已被 SQLite 使用的数据库／辅助文件进行权限检查时，避免自行打开再关闭同一 inode 的原始 fd。保留普通文件、最终路径符号链接与权限防线。由实现负责人补充真实跨进程互斥回归。

### C2 · Important：创建学生仍覆盖公共服务配置的数据库路径

`create_student.sh` 已传入 `--env /etc/english-class/public.env`，但仍显式传入固定 `--database /var/lib/english-class/class.sqlite3`，覆盖环境文件中的 `DATABASE_PATH`。此固定路径行为在 v0.3.3 脚本中已经存在，本报告不把它冒充凭证加密引入的新回归；它影响本次承诺的公共服务／CLI 配置联动。

探针只替换临时部署根目录和 runuser 边界，执行脚本里的实际 CLI 命令。公共服务配置使用自定义数据库，原有 s001 及其模型密钥已保存：

```text
script_cli_exit 0
configured_public_students ['s001']
hardcoded_default_students ['s002']
original_model_unchanged True
custom_key_reused True True
```

新增 s002 被写入另一库，脚本却报告成功；公共服务使用的库没有这个学生。独立主密钥路径在此探针中确实一致，原有凭证也未损坏，问题是数据库选择不一致。主任务已授权同轮移除脚本对配置路径的不当覆盖，并补充实际 CLI 联动回归。

## 已独立核对的其他边界

| 边界 | 证据与初次结论 |
|---|---|
| 保存后的数据库／WAL 不含原始供应商 Key | 现有真实文件测试通过，包含替换和删除；存储字段为 Fernet 密文，GET 所需的解密只在进程内发生。 |
| 旧凭证、旧空闲页与 WAL 清理 | 现有测试及独立中断探针通过；旧 Key、新 Key 的指定虚构字节均不再出现在可访问的 SQLite 文件中。 |
| 迁移在提交后、清理前崩溃 | 独立子进程在版本2提交后、执行 VACUUM 前 `os._exit(73)`；磁盘保留版本1、2和密文。重启沿用同一主密钥，完成版本3并恢复原凭证。 |
| 学习进度不丢失 | 独立崩溃探针预置完整 progress 行；重启后 `('s001','1a_021',2,3,'2026-10-20','original',8,5,2)` 逐字段不变，包含历史档位、计数和时间。 |
| 错误、损坏或缺失主密钥不重新生成 | 现有真实 SQLite／文件测试通过：缺失时不生成新文件；错误或无效文件保持原字节，原密文不改写。 |
| 跨学生密文复制 | 现有测试复制 s001 密文至 s002 后解密失败，认证载荷包含学生 ID。 |
| 最终路径符号链接 | 独立探针对数据库链接返回 OSError、密钥链接返回 SecretStorageError；目标文件内容和原 0644 权限未改变。 |
| systemd 外部只读主密钥 | 现有测试模拟只读打开边界并通过，前提是管理员已准备原主密钥、正确所有者和0600模式；未进行真实 systemd 部署。 |
| CLI 读取主密钥路径 | 原有 CLI 联动测试与独立第三探针均证实 `LLM_SECRET_KEY_FILE` 被读取，带空格路径可用，不执行环境文件中的 shell 文本。 |

独立中断探针输出：

```text
crash_exit 73 versions_after_crash [(1,), (2,)]
credential_is_encrypted True
recovered_original_credential True
master_key_unchanged True
versions_after_retry [1, 2, 3]
preserved_progress ('s001', '1a_021', 2, 3, '2026-10-20', 'original', 8, 5, 2)
plaintext_remains False False
```

## 修复后独立复验

### C1：已修复，真实跨进程互斥保持

复核后的 `secure_database_files` 对已有 DB／WAL／SHM／journal 仅执行 `lstat` 和必要的 `chmod(..., follow_symlinks=False)`，不再自行打开并关闭对应 inode。首次数据库创建被独立的 `<database>.migration.lock` 串行化；迁移锁的文件描述符只指向该 sidecar。

独立探针分别使用 WAL 与 DELETE journal。父连接持有 `BEGIN IMMEDIATE` 和未提交写入；子进程在安全操作前后都尝试写入。中间主动把实际存在的数据库及辅助文件权限改为 0644，再执行权限收紧与迁移锁进入／退出，避免只覆盖“权限原本正确”的空操作：

```text
mode WAL before_and_after ['OperationalError database is locked', 'OperationalError database is locked'] parent_transaction_open True
mode DELETE before_and_after ['OperationalError database is locked', 'OperationalError database is locked'] parent_transaction_open True
independent_sidecar True
integrity_check ('ok',)
```

C1 的原始失败条件已经关闭。实现方另补充两参数回归 `test_file_security_operations_do_not_release_active_sqlite_transaction_locks`，也包含真实子进程及实际权限收紧；独立回归运行中两项均通过。

### 迁移中断后错／缺主密钥：保持失败关闭，并能恢复

独立子进程仍在版本2已提交、VACUUM 尚未执行时以退出码73终止。此时先把主密钥替换为另一把格式有效的 Fernet 密钥，再删除主密钥，两次重启均拒绝打开，保持原密文与迁移版本不变，也没有重新生成文件。恢复原主密钥后，重启完成清理和版本3；原凭证、完整学习进度逐字段保持，当前数据库及辅助文件中的两种指定旧明文字节均消失：

```text
crash_exit 73 versions_after_crash [1, 2]
wrong_key_rejected_without_rewrite True
missing_key_rejected_without_regeneration True
recovered_original_credential True master_key_unchanged True
versions_after_retry [1, 2, 3] preserved_progress ('s001', '1a_021', 2, 3, '2026-10-20', 'original', 8, 5, 2)
plaintext_remains False False integrity_check ('ok',)
```

### C2：已修复，自定义数据库与主密钥路径一致

`install_server.sh` 与 `create_student.sh` 的实际 CLI 命令保留 `--env`，移除了固定数据库和字典路径覆盖。独立复跑初次发现 C2 的创建学生探针，仍使用不同于默认值的 `DATABASE_PATH`，结果为：

```text
script_cli_exit 0
configured_public_students ['s001', 's002']
hardcoded_default_exists False
original_model_unchanged True custom_master_key_unchanged True
```

两个脚本的命令边界均由 `test_credential_cli.py` 实际调用真实 CLI 回归覆盖；独立探针再次确认新增学生进入公共服务指定的数据库，没有创建固定默认库，原 s001 的模型密钥及主密钥文件保持不变。

### 独立专项回归

```sh
/workspace/scratch/d3b03e9e7aea/eng_audit/venv/bin/python -m pytest -q tests/test_credential_storage.py tests/test_credential_cli.py
```

结果：`22 passed in 2.40s`。以上复验未修改生产代码或测试；仅更新本报告。C1／C2 均关闭，未提出额外通用重构或 KMS 改造要求。

