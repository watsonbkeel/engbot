const { validateConnection } = require('./english-view')
const STORAGE_KEY = 'englishClassConnectionV1'
// 仓库只带空模板；本人的 english-env.local.js 可以没有（全新副本、测试环境），此时显示“未配置”。
let initial = Object.assign({}, require('./english-env.example'))
try { initial = Object.assign(initial, require('./english-env.local')) } catch (e) { /* 未放置本地连接文件 */ }
function connection() { return Object.assign({}, initial, wx.getStorageSync(STORAGE_KEY) || {}) }
function isConfigured(c) { return Boolean(c && c.baseUrl && c.studentId && c.token) }
function saveConnection(c) { validateConnection(c); wx.setStorageSync(STORAGE_KEY, Object.assign({}, c)) }
function connectionIdentity() { const c = connection(); return JSON.stringify([c.baseUrl, c.studentId, c.token]) }
function responseError(status, detail, requestId, code) {
  let message = typeof detail === 'string' ? detail : ''
  if (Array.isArray(detail)) {
    message = detail.map(entry => {
      const e = entry && typeof entry === 'object' ? entry : {}
      const field = Array.isArray(e.loc) ? e.loc.filter(x => x !== 'body' && x !== 'query').join('.') : ''
      return `${field ? field + '：' : ''}${typeof e.msg === 'string' ? e.msg : '字段格式不正确'}`
    }).join('；')
  }
  if (!message) message = status === 401 ? '课堂凭证已失效，请到设置重新连接' : `服务器返回 ${status}，请检查配置`
  const id=typeof requestId==='string'&&/^[A-Za-z0-9_-]{8,64}$/.test(requestId)?requestId:''
  const error = new Error(message+(id?'（反馈编号：'+id+'）':'')); error.statusCode = status
  error.requestId=id;error.code=typeof code==='string'?code:'';return error
}
function call(method, path, data, params = {}, timeout = 15000, candidate, includeHeaders = false) {
  return new Promise((resolve, reject) => {
    let c
    try { c = validateConnection(candidate || connection()) } catch (e) { reject(e); return }
    const query = Object.assign({ student_id: c.studentId }, params)
    const qs = Object.keys(query).map(k => `${encodeURIComponent(k)}=${encodeURIComponent(query[k])}`).join('&')
    wx.request({
      url: c.baseUrl.replace(/\/$/, '') + path + '?' + qs, method, data, timeout,
      header: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + c.token },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) { resolve(includeHeaders?{data:res.data,headers:res.header||{}}:res.data); return }
        reject(responseError(res.statusCode, res.data && res.data.detail,res.data&&res.data.request_id,res.data&&res.data.error_code))
      },
      fail() { reject(responseError(0, '没有连接到公共服务。请检查地址、HTTPS合法域名和网络。')) }
    })
  })
}
// 磨耳朵音频下载用：带凭证的完整 URL（InnerAudioContext 的 src 不能带请求头，
// 所以先 downloadFile 到本地临时文件再播）。
function audioDownloadUrl(path) {
  if (!/^\/api\/listening\/[A-Za-z0-9_-]+\/audio$/.test(path)) throw new Error('音频地址格式不正确，请刷新素材')
  const c = validateConnection(connection())
  return { url: c.baseUrl.replace(/\/$/, '') + path + '?student_id=' + encodeURIComponent(c.studentId), token: c.token }
}
module.exports = {
  connection, saveConnection, isConfigured, connectionIdentity,
  testConnection: candidate => call('GET', '/api/config', undefined, {}, 15000, Object.assign({}, candidate)),
  config: () => call('GET', '/api/config'),
  saveConfig: cfg => call('PUT', '/api/config', cfg),
  words: cfg => call('GET', '/api/words', undefined, { grade: cfg.grade, semester: cfg.semester, unit: cfg.unit }),
  progress: () => call('GET', '/api/progress'),
  status: () => call('GET', '/api/status', undefined, {}, 10000),
  llm: () => call('GET', '/api/llm'),
  // 保存自带模型要先测试调用一次（服务器最多等 20 秒），这里给 30 秒。
  saveLlm: body => call('PUT', '/api/llm', body, {}, 30000),
  clearLlm: () => call('DELETE', '/api/llm'),
  // 场景（P1）：模板/示例只读；AI 生成单次 LLM 调用，放宽到 30 秒。
  sceneTemplates: () => call('GET', '/api/scene/templates'),
  sceneUsage: () => call('GET', '/api/scene/usage'),
  sceneGenerate: (description, grade, includeHeaders=false) => call('POST', '/api/scene/generate', { description, grade }, {}, 30000, undefined, includeHeaders),
  // 磨耳朵：200 空列表表示无素材；HTTP / 网络错误由页面独立提示。
  listening: grade => call('GET', '/api/listening', undefined, { grade }),
  audioDownloadUrl
}
