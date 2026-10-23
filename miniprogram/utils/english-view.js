function statusText(row) {
  if (row.status === 2) return '曾独立说出'
  if (row.status === 1) return '曾听懂'
  return row.last_practiced_date ? '继续练习' : '没练过'
}
function evidenceText(row) {
  // 旧记录没有这些字段时不显示，避免把“没有数据”说成“0 次”。
  if (!row.used_word_count && !row.imitated_count) return ''
  // 两个计数来自历次记录，不能当作今天的表现、正确次数或发音评分。
  const own = `累计回答含目标词 ${row.used_word_count || 0} 次`
  return row.imitated_count ? `${own}；累计跟读/模仿记录 ${row.imitated_count} 次（不代表独立表达）` : own
}
const MODE_TEXT = { full: '完整练习', en2zh: '听词说中文', zh2en: '听中文说英文', scene: '场景对话' }
const LESSON_STATUS_TEXT = { in_progress: '进行中', completed: '已结束', stopped: '已停止' }
const REVIEW_STATUS_TEXT = { pending: '点评处理中', success: 'AI点评已生成', failed: '点评未生成', not_applicable: '本模式无AI点评' }
function lessonTimeText(row) {
  const start = row.started_at ? String(row.started_at).replace('T', ' ').replace(/:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/, '') : ''
  const end = row.ended_at ? String(row.ended_at).replace('T', ' ').replace(/:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/, '') : ''
  return start && end ? `${start} 至 ${end}` : start || end || '时间未记录'
}
function elapsedText(seconds) {
  if (typeof seconds !== 'number' || seconds < 0) return ''
  const minutes = Math.floor(seconds / 60)
  const remain = seconds % 60
  return minutes ? `${minutes} 分 ${remain} 秒` : `${remain} 秒`
}
function decorateLesson(row) {
  const lesson = row && typeof row === 'object' ? row : {}
  const reviewStatus = lesson.review_status || 'pending'
  return { ...lesson, modeText: MODE_TEXT[lesson.mode] || lesson.mode || '课堂练习', statusText: LESSON_STATUS_TEXT[lesson.status] || lesson.status || '未知状态', reviewStatusText: REVIEW_STATUS_TEXT[reviewStatus] || reviewStatus, timeText: lessonTimeText(lesson), elapsedText: elapsedText(lesson.elapsed_seconds), reviewStatus, reviewSegments: Array.isArray(lesson.review_segments) ? lesson.review_segments : [] }
}
function buildReport(payload) {
  if (!payload || !Array.isArray(payload.words) || typeof payload.today !== 'string') throw new Error('进度数据格式不正确')
  const decorate = row => ({ ...row, stateText: statusText(row), unclearText: `系统累计没听清 ${row.unclear_count || 0} 次`, evidenceText: evidenceText(row) })
  const allWords = payload.words.map(decorate)
  const todayWords = allWords.filter(row => row.last_practiced_date === payload.today)
  const allLessons = (Array.isArray(payload.lessons) ? payload.lessons : []).map(decorateLesson)
  const todayLessons = allLessons.filter(row => row.day === payload.today || (!row.day && String(row.started_at || '').slice(0, 10) === payload.today))
  return { today: payload.today, todayWords, allWords, todayLessons, allLessons, speakingCount: todayWords.filter(x => x.status === 2).length,
    listeningCount: todayWords.filter(x => x.status === 1).length, practicingCount: todayWords.filter(x => x.status === 0).length }
}
function validateConnection(c) {
  if (!c || !/^https:\/\/[^\s/?#]+(?:\/[^\s?#]*)?\/?$/.test(c.baseUrl)) {
    if (!(c && c.allowHttpForLan && /^http:\/\/[^\s/?#]+(?:\/[^\s?#]*)?\/?$/.test(c.baseUrl))) throw new Error('请填写HTTPS公共服务地址；局域网HTTP测试须由老师明确开启')
  }
  if (!/^[a-z][a-z0-9_-]{1,31}$/.test(c.studentId || '')) throw new Error('学生ID格式不正确')
  if (typeof c.token !== 'string' || c.token.trim().length < 16 || /PUT_|REPLACE|YOUR_/.test(c.token)) throw new Error('请填写老师分配的本人课堂凭证')
  return c
}
module.exports = { statusText, buildReport, validateConnection, decorateLesson, elapsedText }
