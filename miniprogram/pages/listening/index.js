const navigation = require('../../utils/english-navigation')
const api = require('../../utils/english-api')
const life = require('../../utils/page-state')

const GRADES = ['一年级', '二年级', '三年级', '四年级', '五年级', '六年级', '初一', '初二', '初三']
const TYPES = [{ value: 'all', label: '全部' }, { value: 'story', label: '短文' }, { value: 'dialogue', label: '对话' }]
function failure(e) {
  const prefix = { 401: '课堂凭证失效，请到设置重新连接。', 404: '听力接口不可用，请更新服务。', 503: '听力服务暂不可用，请稍后重试。' }[e.statusCode]
  return prefix || e.message || '素材加载失败，请重试'
}
Page({
  data: {
    grades: GRADES, gradeIndex: 0, grade: 1, types: TYPES, typeIndex: 0,
    loading: false, error: '', notReady: false, items: [], shown: [],
    currentId: '', currentTitle: '', playing: false, progress: 0, durationText: '', positionText: '',
    transcript: '', transcriptOpen: false, hasCurrent: false
  },
  onShow() { life.show(this); this.setData(navigation.pageData()); return this.loadGradeThenList() },
  onHide() { life.hide(this); this.stopAudio(); this.setData({ loading: false }) },
  onUnload() { life.hide(this); this.stopAudio() },
  async loadGradeThenList() {
    const active = life.begin(this, 'grade')
    life.begin(this, 'list')
    this.setData({ loading: true, error: '', notReady: false, items: [], shown: [] })
    try {
      const cfg = await api.config()
      if (!active()) return
      const grade = Number.isInteger(cfg.grade) && cfg.grade >= 1 && cfg.grade <= 9 ? cfg.grade : this.data.grade
      this.setData({ grade, gradeIndex: grade - 1 })
      return this.loadList()
    } catch (e) { if (active()) this.setData({ error: failure(e), notReady: false, loading: false }) }
  },
  async loadList() {
    const active = life.begin(this, 'list')
    this.setData({ loading: true, error: '', notReady: false, items: [], shown: [] })
    try {
      const res = await api.listening(this.data.grade)
      if (!active()) return
      if (!res || !Array.isArray(res.items)) throw new Error('素材列表格式不正确，请更新服务')
      const items = res.items.map(x => Object.assign({}, x, { durationLabel: this.fmt(x.duration_seconds) }))
      this.setData({ items, notReady: items.length === 0 }); this.applyFilter()
    } catch (e) { if (active()) this.setData({ items: [], shown: [], notReady: false, error: failure(e) }) }
    finally { if (active()) this.setData({ loading: false }) }
  },
  applyFilter() {
    const selected = TYPES[this.data.typeIndex] || TYPES[0]
    this.setData({ shown: selected.value === 'all' ? this.data.items : this.data.items.filter(x => x.type === selected.value) })
  },
  onGrade(e) {
    const g = Number(e.detail.value) + 1
    if (!Number.isInteger(g) || g < 1 || g > 9) return
    life.begin(this, 'grade'); this.stopAudio()
    this.setData({ grade: g, gradeIndex: g - 1 }); return this.loadList()
  },
  onType(e) {
    const index = Number(e.currentTarget.dataset.index)
    if (!TYPES[index]) return
    this.setData({ typeIndex: index }); this.applyFilter()
  },
  ensureAudio() {
    if (this._audio) return this._audio
    const a = wx.createInnerAudioContext(), identity = api.connectionIdentity()
    const active = () => life.visible(this) && this._audio === a && api.connectionIdentity() === identity
    this._audio = a
    a.onTimeUpdate(() => {
      if (!active()) return
      this.setData({ progress: a.duration > 0 ? Math.min(100, Math.round(a.currentTime / a.duration * 100)) : 0,
        positionText: this.fmt(a.currentTime), durationText: this.fmt(a.duration) })
    })
    a.onPlay(() => { if (active()) this.setData({ playing: true }) })
    a.onPause(() => { if (active()) this.setData({ playing: false }) })
    a.onEnded(() => { if (active()) this.setData({ playing: false, progress: 0, positionText: '0:00' }) })
    a.onError(() => { if (active()) this.setData({ playing: false, error: '这段音频加载失败，请重试或换一条' }) })
    return a
  },
  fmt(sec) {
    sec = Number.isFinite(Number(sec)) ? Math.max(0, Math.floor(Number(sec))) : 0
    return `${Math.floor(sec / 60)}:${sec % 60 < 10 ? '0' : ''}${sec % 60}`
  },
  onPlay(e) {
    if (!life.visible(this) || this.data.loading) return
    const item = this.data.shown[Number(e.currentTarget.dataset.index)]
    if (!item) return
    this.stopAudio()
    const activePage = life.begin(this, 'play'), sequence = this._playSequence
    const active = () => activePage() && this._playSequence === sequence
    let dl
    try { dl = api.audioDownloadUrl(item.audio_url || `/api/listening/${item.id}/audio`) }
    catch (e) { this.setData({ error: e.message }); return }
    this._downloadBusy = true; wx.showLoading({ title: '加载音频…' })
    const finish = () => { this._download = null; if (this._downloadBusy) wx.hideLoading(); this._downloadBusy = false }
    this._download = wx.downloadFile({
      url: dl.url, header: { Authorization: 'Bearer ' + dl.token }, timeout: 30000,
      success: res => {
        if (!active()) return
        finish()
        if (res.statusCode !== 200) { this.setData({ error: failure({ statusCode: res.statusCode, message: `音频下载失败（${res.statusCode}）` }) }); return }
        const a = this.ensureAudio()
        this.setData({ hasCurrent: true, currentId: item.id, currentTitle: item.title || '未命名素材',
          transcript: item.transcript || '', transcriptOpen: false, error: '', progress: 0,
          durationText: this.fmt(item.duration_seconds), positionText: '0:00' })
        a.src = res.tempFilePath; a.play()
      },
      fail: () => { if (active()) { finish(); this.setData({ error: '音频下载失败，请检查网络后重试' }) } }
    })
  },
  onToggle() {
    const a = this._audio
    if (!life.visible(this) || !a || !this.data.hasCurrent) return
    if (this.data.playing) a.pause(); else a.play()
  },
  onSeek(e) { const a = this._audio; if (life.visible(this) && a && a.duration) a.seek(Math.max(0, Math.min(100, Number(e.detail.value))) / 100 * a.duration) },
  onPrev() { this.step(-1) }, onNext() { this.step(1) },
  step(direction) {
    if (!this.data.shown.length) return
    const i = this.data.shown.findIndex(x => x.id === this.data.currentId)
    const index = i < 0 ? 0 : (i + direction + this.data.shown.length) % this.data.shown.length
    this.onPlay({ currentTarget: { dataset: { index } } })
  },
  onToggleTranscript() { this.setData({ transcriptOpen: !this.data.transcriptOpen }) },
  stopAudio() {
    this._playSequence = (this._playSequence || 0) + 1
    const task = this._download; this._download = null
    if (task && typeof task.abort === 'function') task.abort()
    if (this._downloadBusy) wx.hideLoading()
    this._downloadBusy = false
    const a = this._audio; this._audio = null
    if (a) { a.stop(); a.destroy() }
    this.setData({ playing: false, hasCurrent: false, currentId: '', currentTitle: '', transcript: '', progress: 0 })
  }
})
