# macOS 听力测试失败复核与修复

日期：2026-10-21。代码基线：`b0a85e54c3b3815306b717fcaaa4980a5b433ce9`（原样提取的 v0.3.3）。本专项在 Linux、Python 3.12.14、Node.js 24.19.0、ffmpeg 6.1.1 环境执行；**没有在原生 macOS 上运行，也没有触发 GitHub Actions**。

## 1. 两项失败来自同一个前置路径检查

原版 `tests_js/listening_assets.test.js` 在普通临时目录通过。在 Linux 上创建 `alias → physical` 目录符号链接，再把 `TMPDIR` 指向 `alias`，可以复现用户报告的两项失败，位置与堆栈一致：

| 原版用例 | 实际失败点 | 原因 |
|---|---|---|
| 第 28 行的缺 Piper 模型用例 | 第 32 行 `result.status`：实际 `2`，预期 `1` | `generate()` 在创建输出目录、加载模型、记录逐条失败之前，就被 `ensure_no_links(root)` 拦下 |
| 第 39 行的损坏音频／原子权限用例 | `validate_asset → safe_asset → ensure_no_links` | 还未计算摘要，就因临时目录祖先的符号链接抛出“素材输出路径不能经过符号链接” |

因此，第一项的 `2 !== 1` 是**进程退出码差异**，不是 `failures.failed` 中出现了两个失败条目。独立探针确认：祖先有别名时，输出目录和 `failures.json` 均未创建；普通物理路径下，返回码为 1，失败清单恰有一条缺模型记录，没有 MP3 或残留构建锁。

`ensure_no_links()` 的既有规则会从目标路径一直检查到文件系统根。测试曾假定 `os.tmpdir()` 和 Python `tempfile.TemporaryDirectory()` 返回的字符串不经过任何符号链接。系统临时目录使用别名时，这个假定不成立。只修正 Node 一侧，内嵌 Python 的损坏音频用例仍失败；只修正 Python 一侧，Node 创建的缺模型用例仍失败。两侧分别修正后才都通过。

原版证据见 [mac-listening-red.log](mac-listening-red.log)，其中保存了基线源文件摘要、临时目录设置、4 通过／2 失败的完整输出。日志中的 Linux 祖先别名模拟用于证明触发机制，不能据此宣称全部 macOS 环境已经通过。

## 2. 修复范围与保留的安全规则

只规范化由测试自己管理的可信临时目录：

- Node 测试先用 `fs.realpathSync(os.tmpdir())` 获得物理临时基目录，再用 `mkdtempSync()` 创建独立夹具。
- 内嵌 Python 测试将自己刚创建的临时目录转成 `Path(tmp).resolve()`，随后才写入损坏音频和权限测试文件。
- 新增 Node 回归会主动创建祖先别名，把 `TMPDIR`、`TEMP`、`TMP` 都指向该别名，再启动独立 Node 进程重跑原来的两个目标用例。它不会只依赖当前宿主机碰巧有符号链接。

**生产路径检查条件没有放宽。** 用户传入的资产根目录、年级子目录、音频文件及其祖先仍不能经过符号链接；元数据原子写入仍拒绝符号链接。不对生产输入新增无条件 `resolve()`，也不把错误原因断言改成“任意失败均可”。

新增 Python 回归覆盖资源根、内部目录和音频叶子的链接，分别包含指向内部、外部、已不存在目标的情况。`index.json` 和 `failures.json` 的原子写入检查同时覆盖正常与悬空链接，并核对链接目标没有改变、没有遗留临时文件。直接把带祖先别名的输出路径交给 CLI，仍在写入之前返回路径错误。

## 3. 稳定错误码

`BuildError` 现在具有 `.code`，`str(error)` 保留原中文文本。CLI 的人读提示附带方括号错误码；新生成的 `failures.json` 每个失败条目增加 `code`，既有 `id`、`error_type`、`message` 字段保留。

| code | 含义 |
|---|---|
| `PATH_SYMLINK` | 输出／资产／原子元数据路径经过符号链接 |
| `ASSET_PATH_INVALID` | 原稿或清单中的音频相对路径格式非法 |
| `ASSET_OUTSIDE_ROOT` | 音频路径超出素材根目录 |
| `ASSET_MISSING` | 合法路径下缺少音频文件 |
| `ASSET_DIGEST_MISMATCH` | 音频 SHA-256 与清单不同 |
| `PIPER_MODEL_MISSING` | 缺少已下载的 `.onnx` 或同名 `.onnx.json` |
| `PIPER_MODEL_REQUIRED` | 选择 Piper 却没有传入模型参数 |
| `GENERATION_FAILED` | 非 `BuildError` 的引擎／生成异常；仍只记录安全通用提示 |
| `BUILD_ERROR` | 其他已有人读构建校验错误的默认类别 |

测试对错误原因断言稳定代码，不依赖完整中文句子。缺模型用例继续要求返回码 1、恰有一条失败、`generated=0`、`complete=false`、空索引、无替代 MP3、无残留锁，并核对 `PIPER_MODEL_MISSING`。

## 4. 统一测试解释器与依赖预检查

`scripts/test_all.sh` 的 Python 选择顺序是：显式 `PYTHON` → 项目 `.venv/bin/python` → `PATH` 中的 `python3`。选定值导出给 Node 子进程；Python 编译、pytest 和 Node 启动的听力脚本不再各自选择解释器。解释器入口保留虚拟环境路径，不对它使用 `realpath`，因为虚拟环境的 Python 本身可能是符号链接。

脚本在测试前检查 Python 至少为 3.11、能导入 pytest，以及 `node`、`ffmpeg`、`ffprobe` 命令可用；启动输出各自版本。缺项时返回 2，提示用户安装相应依赖，脚本不会自动安装。

通过临时命令边界探针，已验证：无效的显式 `PYTHON` 提前失败；显式覆盖优先于项目虚拟环境；未指定时优先项目虚拟环境，再退到 `python3`；缺少 pytest、ffprobe 或全部三个外部工具时，在运行测试之前报告具体缺项。原版忽略 `PYTHON` 的红测与上述结果见 [mac-test-runner-preflight.log](mac-test-runner-preflight.log)。这些探针用于验证入口选择与前置失败，不冒充实际测试套件运行。

新增 `.github/workflows/tests.yml` 配置 `ubuntu-latest`、`macos-latest` 与 Python 3.11、3.12 的四组合矩阵，使用 Node 24，并调用同一个 `bash scripts/test_all.sh`。依赖安装写在 CI 作业的显式步骤里。工作流 YAML 已在本地解析并核对矩阵及入口，但未推送、未在 GitHub 上执行；macOS 的实际通过结果必须等待该环境执行后才能记录。GitHub 官方动作的接口参考：[checkout](https://github.com/actions/checkout)、[setup-python](https://github.com/actions/setup-python)、[setup-node](https://github.com/actions/setup-node)。

2026-10-21 另以只读 `git ls-remote --exit-code` 核对三个官方仓库的 `refs/tags/v7`，再读取对应提交的 `action.yml`。实际标签及当前工作流使用的输入均已确认：

| 官方 Action | v7 对应提交及定义 | 已核对输入 |
|---|---|---|
| `actions/checkout` | [3d3c42e5aac5ba805825da76410c181273ba90b1](https://github.com/actions/checkout/blob/3d3c42e5aac5ba805825da76410c181273ba90b1/action.yml) | `persist-credentials` |
| `actions/setup-python` | [5fda3b95a4ea91299a34e894583c3862153e4b97](https://github.com/actions/setup-python/blob/5fda3b95a4ea91299a34e894583c3862153e4b97/action.yml) | `python-version`、`cache`、`cache-dependency-path` |
| `actions/setup-node` | [949feb2413d6458794dcd2491c4babbbce0c15c1](https://github.com/actions/setup-node/blob/949feb2413d6458794dcd2491c4babbbce0c15c1/action.yml) | `node-version`、`package-manager-cache` |

现有 standalone 构建用例已补充完整文件集合和逐文件字节比较：从仓库内 canonical `miniprogram/` 生成临时新目录，只排除 builder 契约中的本地连接、私有配置和工具产物；默认构建没有其他内容差异需要豁免。此用例不依赖仓库外的 sibling 目录，CI 的同一 pytest 入口会自动执行。原有六页、无本地凭据、`urlCheck=true` 及拒绝覆盖输出目录的断言保留；补强后单例实测 **1 通过**。

## 5. 本专项实测结果

| 验证 | 结果 | 证据 |
|---|---|---|
| 原版完整听力文件，模拟祖先别名 | 4 通过、2 失败，复现用户报错 | `mac-listening-red.log` |
| 新错误码及路径边界回归，修改前 | 17 失败，原因是错误码尚不存在 | `mac-listening-codes-red.log` |
| 新祖先别名 Node 回归，修改前 | 失败，内部两项目标用例均失败 | `mac-listening-fixtures-red.log` |
| `pytest tests/test_listening_paths.py -q`，修改后 | **17 通过、0 跳过** | `mac-listening-green.log` |
| `node --test tests_js/listening_assets.test.js`，修改后 | **7 通过、0 跳过**；新例内部另执行两个目标用例 | `mac-listening-green.log` |
| 解释器选择与缺依赖边界 | 预期退出码、缺项提示和选择结果均符合 | `mac-test-runner-preflight.log` |
| Bash 语法、工作流 YAML 结构、diff 空白检查 | 通过 | 本次执行记录 |

本执行环境对 Node 创建 Node 子进程存在沙箱限制；专项 Node 红／绿回归已在允许本地测试子进程的执行上下文中运行，未跳过用例，也未把 `EPERM` 当作产品行为。素材复验仍使用交付的真实 MP3、摘要和 ffprobe，不重新合成、不调用外部语音服务。

按并行任务协调要求，本专项没有在其他模块尚未收敛时反复运行全量套件。全工程统一结果由最终 `docs/TEST_REPORT.md` 与全量日志记录；这里的 17／7 只代表本专项实际执行范围。
