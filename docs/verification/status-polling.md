# 设置页／今日页状态轮询修复验证

日期：2026-10-21。实测环境为 Linux、Node.js 24.19.0；本专项未运行微信真机测试。

## 行为与修改边界

新增 `miniprogram/utils/status-poller.js`，由设置页和今日页共同调用。进入页面时立即请求状态；只有当前请求的 Promise 已经成功或失败结束，才创建下一次 `setTimeout`。成功后等待 10 秒；连续失败依次等待 20、40、60 秒，后续保持 60 秒；任一次成功都恢复 10 秒。

`onHide` 和 `onUnload` 清除已有定时器并使该轮询失效。重新显示页面或成功保存课堂连接时创建新的轮询状态，立即请求当前课堂并重置失败次数。定时器使用可选 `unref()`，兼容 Node 的对象句柄与微信的数字句柄。既有 `page-state` 页面可见性、生命周期和连接身份校验继续生效，另用独立的 `status-poll` 通道阻止旧轮询恢复。

页面改动限于上述调度调用和 `refreshStatus()` 返回成功／失败布尔结果；设置页已有平台回退同意、模型状态等业务字段保留。设置页连接保存成功后会先清理旧轮询，再为新课堂立即请求状态。

**已有网络请求不能通过当前 API 包装器中止。** 隐藏后马上重新显示，或在请求尚未结束时切换课堂，仍可能留下旧一代网络请求在途；新一代需要立即获取当前课堂状态。旧请求的迟到响应不能写入页面，也不能创建下一次定时器。单个有效轮询中的下一次请求必须等待上一次实际结束，因此慢请求不会造成同一轮询持续叠加。

## 可控时间回归

`tests_js/status-poller.test.js` 加载实际设置页／今日页 Page 定义，经过实际 `english-api` Promise 调用，在 `wx.request` 边界控制响应。测试替换计时器并推进虚拟时间，无真实秒级等待。

16 项用例覆盖两页的立即请求、请求挂起 30／60 秒期间不重复发送、结束后才计时、20／40／60 秒失败退避与成功恢复、隐藏和卸载清理、隐藏后的迟到响应、重新显示时失败次数重置、课堂身份变更以及设置页连接保存前后的在途请求隔离。网络失败与 HTTP 503 都进入退避；成功的旧课堂响应和失败的旧课堂响应均不能影响新课堂。

| 执行 | 实测结果 | 证据 |
|---|---|---|
| 新回归对原 `setInterval` 实现 | 7 通过、9 失败；挂起请求发生重复发送、失败仍按 10 秒请求等 | [status-polling-red.log](status-polling-red.log) |
| 共享调度实现后，同一回归 | **16 通过、0 失败、0 跳过**；收尾重跑仍全通过 | [status-polling-green.log](status-polling-green.log) |
| 状态、页面、场景流、v0.3.2 前端、review-policy 及本专项共六个相关文件 | **90 通过、0 失败、0 跳过** | [status-polling-integration.log](status-polling-integration.log) |
| 新模块与两页 JavaScript 语法、diff 空白检查 | 通过 | 本次执行记录 |

相关集成命令为 `node --test tests_js/status-poller.test.js tests_js/status.test.js tests_js/pages.test.js tests_js/scene-design-flow.test.js tests_js/v032-frontend.test.js tests_js/review-policy.test.js`。本环境对 Node 子进程存在沙箱限制，验证在允许本地测试子进程的上下文运行，没有跳过用例。没有调用外部模型或实际课堂服务；整个工程的最终统一门禁由主流程执行并记录。
