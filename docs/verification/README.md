# 复核证据索引

## v0.3.4 当前交付

- [final-tests.txt](final-tests.txt)：最终完整门禁，464 Python／113 Node，0失败。
- [final-review.md](final-review.md)：最终复核汇总及交叉问题关闭。
- [mac-listening-review.md](mac-listening-review.md)：Mac临时路径根因、错误码、测试入口、CI与构建检查。
- [credential-storage.md](credential-storage.md)：认证加密、迁移、权限、用量与恢复合同。
- [credential-independent-review.md](credential-independent-review.md)：SQLite跨进程锁、迁移中断与部署CLI独立复验。
- [policy-independent-review.md](policy-independent-review.md)：回退、参数脱敏、超时状态与用量UI独立复验。
- [runtime-boundaries.md](runtime-boundaries.md)：ASR并发、超时与HTTP客户端生命周期。
- [status-polling.md](status-polling.md)：16项轮询边界回归与不能abort的实际限制。
- [release-package.json](release-package.json)：最终ZIP、独立小程序、词库、音频和凭证排除核对。

## 历史证据

v0.3.3的四组GPT场景模拟位于scene-simulations与上级SCENE_SIMULATION_REPORT.html；不是v0.3.4新调用。scene-design-api.md与llm-optional-thinking.md记录该阶段接口及模型协议工作。

v0.3.2的前端／教学／音频和v0.3.1的工程／产品记录继续保留；历史TEST_REPORT、UPGRADE、final-tests和final-review在docs/history。历史版本号和旧测试数量不应被替换成本次结果。

含red的日志是修复前预期失败；attempt、progress是中间结果。只有本版final-tests代表本次统一门禁。全部夹具凭证均为虚构测试内容，不含真实Key；自动化替身与真实供应商、微信和设备验收分开说明。
