英语陪练家长端（需求 v3）

这是唯一的小程序源码，包含今日练习、磨耳朵、练习记录、设置四个 Tab，以及首次引导和场景设置。

推荐独立构建：
  python scripts/build_miniprogram.py --output /新的输出目录
在微信开发者工具导入输出目录，选择自己的 AppID。仓库使用 touristappid 占位，默认开启合法域名检查。
在微信公众平台配置自己服务的 request 和 downloadFile HTTPS 合法域名。
开发者工具本地调试可以按微信平台规则配置调试选项；正式真机/发布仍须合法 HTTPS 域名。

课堂连接：
首次打开后填写老师提供的公共服务地址、学生编号、家长凭证。程序验证候选连接成功后才保存。
凭证和模型 Key 不在交付源码中。模型 Key 仅通过 HTTPS 提交服务器，成功后清空输入；不会写入本地连接存储。
首次引导完成表示连接已验证。还要在设置查看大脑、树莓派和练习程序状态，再执行一次真实语音练习。

如需合并原 WordMaster 小程序：
  python scripts/build_miniprogram.py --source /原小程序根目录 --output /新的合并目录
原项目不修改。保留原 app.js 和 tabBar，将六页及完整工具文件加到副本；同名路由/文件会在复制前明确报错。
合并页底部有四项陪练导航和“返回原小程序主页”。若原项目有 pages/profile/index.wxml，会在副本添加陪练入口。
合并版不会自动替换原项目的启动逻辑；原项目其他页面可用 navigator 跳到 /pages/today/index。

连接文件：
不需要连接文件也可在引导中输入。若明确需要预填本人的连接，可使用 --connection /本人/english-env.local.js。
带有本人连接的构建只用于本人设备，不得作为公开代码或公开 ZIP 分享。

交付自动测试覆盖实际页面 JS 与 HTTP 合同。Node 测试不等同于微信开发者工具、真机音频及真实设备验收。
听力素材、生成和复验详见仓库 docs/LISTENING.md。
