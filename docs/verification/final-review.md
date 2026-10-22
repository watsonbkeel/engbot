# v0.3.4 最终复核汇总

日期：2026-10-21。实现基线b0a85e54c3b3815306b717fcaaa4980a5b433ce9；最终版本0.3.4。

## 结论

本轮已确认的重要问题均完成修复和独立复验；最终统一门禁464条Python、113条Node全部通过，0失败、0跳过；1条既有第三方弃用警告。Python19.29秒，Node约5.22秒。此结论限于本次代码与本地边界；没有部署或宣称真实供应商、Mac、微信手机、Pi及儿童语音验收通过。

## 已关闭的交叉审查问题

| 发现 | 实现与独立复验证据 |
|---|---|
| SQLite权限加固open/close破坏记录锁 | 现有DB／aux仅lstat/chmod，迁移锁sidecar；WAL／DELETE真实子进程保持阻塞。 |
| 创建学生覆盖自定义DATABASE_PATH | 脚本遵循public.env；实际CLI写入自定义库，原学生与主密钥保持。 |
| 校验响应回显提交Key | 只保留loc/type/msg；InvalidRequest与request_id可用，Key与学习正文不回显。 |
| 场景双重timeout绕过状态更新 | ModelService唯一预算；原短时限探针得到Timeout、last_status=error、同请求日志与1尝试0成功。 |
| 编辑期间生成用量不刷新 | 独立页面／课堂guard刷新用量，生成lane继续保护草稿；隐藏与换课堂不刷新。 |

详见[credential-independent-review.md](credential-independent-review.md)和[policy-independent-review.md](policy-independent-review.md)。两份记录分别由未修改被审实现的审查者完成，保留修复前后真实探针摘要。

Mac听力失败先复现再修可信测试路径；生产链接边界保持。ASR与连接生命周期由独立任务分析实现，root合并后执行全项目门禁；轮询16项真实Page时间测试并入113条Node。完整执行输出见[final-tests.txt](final-tests.txt)。

后续仅做文档同步、由canonical源码重建独立小程序、交付包摘要与解压核对；若发现需要更改运行代码的问题，应重新执行相关门禁后再交付。
