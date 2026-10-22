// A visible page owns one poll generation; the next delay starts after settlement.
const life = require('./page-state')
const NORMAL_DELAY = 10000

function stop(page) {
  const state = page._statusPoller
  page._statusPoller = null
  if (state && state.timer !== null) clearTimeout(state.timer)
}

function start(page) {
  stop(page)
  const state = {timer:null,failures:0}
  page._statusPoller = state
  const current = life.begin(page,'status-poll')
  const active = () => page._statusPoller === state && current()
  async function poll() {
    state.timer = null
    if (!active()) return false
    let success = false
    try { success = await page.refreshStatus() === true } catch (_) {}
    if (!active()) return false
    state.failures = success ? 0 : Math.min(state.failures + 1,3)
    const delay = success ? NORMAL_DELAY : Math.min(NORMAL_DELAY * Math.pow(2,state.failures),60000)
    state.timer = setTimeout(poll,delay)
    // Node test timers are objects; WeChat timers may be numeric handles.
    if (state.timer && typeof state.timer.unref === 'function') state.timer.unref()
    return success
  }
  return poll()
}

module.exports = {start,stop}
