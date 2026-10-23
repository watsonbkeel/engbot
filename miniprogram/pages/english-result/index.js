const navigation = require('../../utils/english-navigation')
const api = require('../../utils/english-api')
const life = require('../../utils/page-state')
const { buildReport } = require('../../utils/english-view')
const MODE_TEXT = { full: '完整练习', en2zh: '听词说中文', zh2en: '听中文说英文', scene: '场景对话' }
Page({
  data: { loading: false, error: '', loaded: false, today: '', todayWords: [], allWords: [], todayLessons: [], allLessons: [], speakingCount: 0, listeningCount: 0, practicingCount: 0, showAll: false, showAllLessons: false, modeScene: '' },
  onShow() { life.show(this); this.setData(navigation.pageData()); return this.refresh() },
  onHide() { life.hide(this); this.setData({ loading: false }) },
  onUnload() { life.hide(this) },
  async refresh() {
    const active = life.begin(this, 'report')
    this.setData({ loading: true, error: '', loaded: false })
    try {
      const result = buildReport(await api.progress())
      if (!active()) return
      this.setData(Object.assign({}, result, { loaded: true }))
      try {
        const cfg = await api.config()
        if (active()) this.setData({ modeScene: (MODE_TEXT[cfg.mode || 'full'] || '完整练习') + (cfg.scene ? ` · ${cfg.scene.name}` : '') })
      } catch (e) { if (active()) this.setData({ modeScene: '' }) }
    } catch (e) { if (active()) this.setData({ error: e.message }) }
    finally { if (active()) { this.setData({ loading: false }); wx.stopPullDownRefresh() } }
  },
  onPullDownRefresh() { return this.refresh() },
  onToggleAll() { this.setData({ showAll: !this.data.showAll }) },
  onToggleAllLessons() { this.setData({ showAllLessons: !this.data.showAllLessons }) },
  onToday() { navigation.open('/pages/today/index') }
})
