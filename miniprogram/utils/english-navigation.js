const origin = require('./english-origin')
const TABS = ['pages/today/index', 'pages/listening/index', 'pages/english-result/index', 'pages/settings/index']
function destination(path, source = origin) {
  const page = path.replace(/^\//, '')
  const tabs = source.embedded ? source.tabPages || [] : TABS
  return { method: tabs.includes(page) ? 'switchTab' : 'redirectTo', url: '/' + page }
}
function open(path) { const target = destination(path); wx[target.method]({url:target.url}) }
function pageData() { return {embedded:Boolean(origin.embedded),originHome:origin.home||'',originIsTab:Boolean(origin.isTab)} }
module.exports = {destination,open,pageData}
