const api = require('./utils/english-api')

App({
  onLaunch() {
    // 首次判断：本地没有完整的课堂连接（base / student / token 任一缺失）→ 进引导页。
    const c = api.connection()
    if (!(c && c.baseUrl && c.studentId && c.token)) {
      wx.reLaunch({ url: '/pages/onboarding/index' })
    }
  }
})
