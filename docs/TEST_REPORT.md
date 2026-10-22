# v0.3.4 最终测试报告

日期：2026-10-21。基于已交付v0.3.3的精确副本修改；本报告只记录本次实际运行与复核，不代表Mac、线上供应商或真实设备已经验收。

## 1. 最终统一门禁

**464条Python、113条Node全部通过，0失败、0跳过；1条既有第三方弃用警告。** 相比原385／82基线，新增79条Python与31条Node回归；既有测试按明确变化更新了授权回退和异步请求定位，没有用跳过或放宽生产路径安全规则使结果变绿。

实际命令（项目根目录）：

```bash
PYTHON=/workspace/scratch/d3b03e9e7aea/eng_audit/venv/bin/python bash scripts/test_all.sh
```

使用者在自己的解压目录建立`.venv`后直接运行`bash scripts/test_all.sh`；也可用自己的解释器路径设置PYTHON。上述绝对路径仅记录本次执行环境，不是安装路径要求。

| 检查 | 实际结果 |
|---|---|
| Python／pytest | Python3.12.14、pytest9.0.2；464通过，19.29秒 |
| Node | Node24.19.0；113通过，约5.22秒；失败／取消／跳过均0 |
| ffmpeg／ffprobe | 6.1.1-3ubuntu5 |
| Python编译 | english_class、pi、scripts、tests通过 |
| 实际小程序JS语法 | 六页及工具全部通过 |
| shell语法 | scripts下全部sh通过 |
| diff空白检查 | git diff --check通过 |

完整原始日志：[verification/final-tests.txt](verification/final-tests.txt)。唯一警告为Starlette测试客户端引用AnyIO已弃用BlockingPortal别名；没有测试失败，也没有因此升级全部框架。统一命令执行在最终实现冻结以后，随后只调整文档、构建独立副本和打包。

## 2. 本轮新增覆盖

| 范围 | 关键验证 |
|---|---|
| 听力与Mac差异 | 真实Linux子进程制造祖先TMPDIR符号链接，复现原两项失败；可信临时路径规范化后通过，生产链接仍拒绝；稳定错误码区分路径／缺文件／摘要／缺模型。 |
| 凭证与迁移 | 真实SQLite加密、文件权限、缺／错主密钥、损坏密文、学生ID绑定、旧空闲页与WAL清理、并发初始化、清理中断可恢复。 |
| 数据库互斥 | WAL与DELETE两种模式下，实际权限收紧与迁移锁进入退出不解除父事务锁；真实子进程仍被阻止。 |
| CLI配置 | 执行部署脚本中的实际CLI命令，仅替换系统部署路径／切换用户边界；自定义数据库、词库、主密钥与公共环境一致，不另建固定库。 |
| 回退政策 | 默认不发平台；明确开关后才回退；严格布尔值、两次尝试共用时限、双方失败与最近状态、错误Key脱敏。 |
| 场景用量 | 五字段校验后成功计次，失败仅计尝试；午夜归原日期；旧次数保留；编辑草稿后刷新用量，隐藏与换课堂不写旧响应。 |
| 请求诊断 | 公共HTTP与模型同request_id、参数校验不回显Key／学习正文、未知异常安全500、结构化日志不含凭证或完整对话。 |
| 音频运行边界 | 原PCM WAV合同、畸形RIFF、错误媒体类型、上传时限、跨Providers实例共享并发、取消／超时后仍运行工作保留槽、本地等待上限。 |
| HTTP客户端 | 同生命周期连接池复用、同事件循环关闭、不同学生隔离、退出清理、畸形错误体安全映射；不新增业务POST自动重试。 |
| 小程序轮询 | 实际Page＋可控时间16项：settled后再调度、20/40/60退避、成功恢复、隐藏／卸载暂停、数字timer句柄0、课堂切换与迟到响应隔离。 |
| 独立小程序构建 | 从canonical源码生成全新临时目录，完整文件集合与字节逐项一致；CI不依赖交付包sibling目录。 |

## 3. 独立审查闭环

凭证实现由运行边界审查者独立检查，发现SQLite锁释放和创建学生路径覆盖问题，修复后用真实跨进程／CLI探针关闭。政策实现由凭证审查者独立检查，发现校验Key回显、重复时限导致旧成功状态、编辑中用量不刷新，修复后以原探针确认关闭。

- [credential-independent-review.md](verification/credential-independent-review.md)：存储／CLI独立复核。
- [policy-independent-review.md](verification/policy-independent-review.md)：路由／状态／UI独立复核。
- [runtime-boundaries.md](verification/runtime-boundaries.md)：音频与连接生命周期证据。
- [mac-listening-review.md](verification/mac-listening-review.md)、[status-polling.md](verification/status-polling.md)：跨环境路径、CI定义、轮询证据。

审查结论限于本轮代码与本地证据覆盖范围，无剩余已确认Important；不能推导全部未来供应商或部署环境无缺陷。带red的文件是修复前预期失败，不能单独当成最终失败报告。

## 4. 基线与历史场景证据

精确v0.3.3基线在本次Linux环境重新执行385条Python与82条Node通过；用户Mac缺pytest与两个路径相关失败仍是真实环境反馈，没有用基线结果否定它。旧交付报告、全量日志、独立复核与升级说明保存于docs/history/v0.3.3-*。

四组GPT场景模拟保留在[SCENE_SIMULATION_REPORT.html](SCENE_SIMULATION_REPORT.html)。它们来自v0.3.3阶段，不是本轮新供应商调用。本次继续跑场景API、实际Page设计／保存／安排、角色对话、年级草稿隔离、自然完成与学习证据回归；正式代码仍不会加载测试示例作课堂答案。

## 5. 发布包核对

独立小程序从最终主工程重建。打包器核对原词库3919条及原fullDictionary.js Git blob、45段MP3清单／摘要／解码／非静音、六页小程序逐文件一致、已知原连接凭证排除、无运行数据库／主密钥／缓存，并在ZIP解压后核对CRC与全部文件SHA-256。

最终实物结果在[verification/release-package.json](verification/release-package.json)，主工程和Eng顶层分别有SHA256SUMS.txt。上述打包检查是交付门禁，不是供应商验收。

## 6. 未实测的目标环境

真实Mac与GitHub Actions矩阵、用户自己的模型账号／DNS／JSON稳定性／费用、微信开发者工具与手机合法域名和渲染、Pi耳麦／唤醒、儿童口音ASR、实时TTS听感及连续对话延迟均未在本次执行。测试适配器只控制外部边界，不能证明实际儿童已达到口语目标，也不是发音评分。

新CI为Linux/macOS × Python3.11/3.12、Node24，使用同一入口；三个官方v7标签及所用输入已核实，但没有远端运行结果。下载后按[INSTALL.md](INSTALL.md)第8节验收。已有服务必须先按[UPGRADE.md](UPGRADE.md)备份，迁移后恢复需要匹配主密钥，不能直接降回v0.3.3。
