const path = require('node:path')
const root = path.resolve(__dirname, '../miniprogram')
const copy = x => JSON.parse(JSON.stringify(x))
const connection = { baseUrl: 'https://class.example', studentId: 's001', token: 'test-only-parent-credential' }
const config = { grade: 1, semester: 1, unit: 0, duration_minutes: 10, practice_words: 3, chinese_help: true, difficulty: 'basic', mode: 'full', scene: null }
const catalog = { units: [{value: 0, label: '本学期全部词汇'}], words: [{word: 'apple'}] }
function environment(responder = () => {}) {
  const state = { storage: copy(connection), requests: [], toasts: [], navigations: [], downloads: [], audio: [], loading: 0 }
  global.wx = {
    getStorageSync: () => state.storage, setStorageSync: (_key, value) => {state.storage = copy(value)},
    showToast: value => state.toasts.push(value), stopPullDownRefresh() {},
    reLaunch: value => state.navigations.push(value), navigateTo: value => state.navigations.push(value),
    switchTab: value => state.navigations.push(value), redirectTo: value => state.navigations.push(value),
    showModal: options => options.success({confirm: true}),
    showLoading: () => state.loading++, hideLoading: () => {state.loading = Math.max(0, state.loading - 1)},
    request: options => {state.requests.push(options); responder(options, new URL(options.url).pathname, state); return {abort() {}}},
    downloadFile: options => {const task = {options, aborted: false, abort() {this.aborted = true}}; state.downloads.push(task); return task},
    createInnerAudioContext: () => {
      const events = {}; const audio = {currentTime: 0, duration: 90, plays: 0, stops: 0, destroyed: false,
        play() {this.plays++; if (events.play) events.play()}, stop() {this.stops++}, pause() {if (events.pause) events.pause()},
        seek(value) {this.currentTime = value}, destroy() {this.destroyed = true}}
      for (const event of ['TimeUpdate','Play','Pause','Ended','Error']) audio['on'+event] = callback => {events[event[0].toLowerCase()+event.slice(1)] = callback}
      audio.emit = (event, arg) => {if (events[event]) events[event](arg)}
      state.audio.push(audio); return audio
    },
    setClipboardData: options => {if (options.success) options.success()}
  }
  return state
}
function respond(options, data, statusCode = 200) {options.success({statusCode, data: copy(data)})}
function page(name, options) {
  let definition; global.Page = value => {definition = value}
  const filename = path.join(root, 'pages', name, 'index.js')
  delete require.cache[require.resolve(filename)]; require(filename)
  const instance = {data: copy(definition.data), updates: []}
  instance.setData = patch => {
    instance.updates.push(patch)
    for (const [key,value] of Object.entries(patch)) {
      const parts = key.split('.'); let target = instance.data
      for (const part of parts.slice(0,-1)) target = target[part]
      target[parts.at(-1)] = value
    }
  }
  for (const [key,value] of Object.entries(definition)) if (typeof value === 'function') instance[key] = value.bind(instance)
  if (instance.onShow) {
    const show=instance.onShow
    instance.onShow=()=>{const result=show(); if (instance._timer && instance._timer.unref) instance._timer.unref(); return result}
  }
  if (instance.onLoad) instance.onLoad(options)
  return instance
}
module.exports = {root, copy, connection, config, catalog, environment, respond, page}
