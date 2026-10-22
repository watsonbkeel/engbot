const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const {copy, config, catalog, environment, respond, page} = require('./helpers.cjs')

const DESCRIPTION = '我想在火星温室里扮演园艺助手，机器人扮演管理员，我想问怎么照顾植物。'
const SCENE = {
  name: '火星温室', robot_role: '温室管理员', student_role: '新来的园艺助手',
  goal: '问候管理员；询问植物；请管理员递水壶；给植物浇水并道谢', opening: 'Hello! Can I help?'
}
const EDITED_OPENING = 'Hello! May I help?'
const input = (field, value) => ({currentTarget: {dataset: {field}}, detail: {value}})
const pick = value => ({detail: {value: String(value)}})
let classroomNumber = 0

// Only the HTTP and WeChat boundary is substituted. Every transition below runs
// the shipped Page functions; the fake service retains the real config bodies.
function classroom(initial = config) {
  let saved = copy(initial)
  let model = {mode: 'platform'}
  const control = {generationError: null, saveError: null, configError: null, holdSave: false}
  delete global.getCurrentPages
  const state = environment((request, path) => {
    if (path === '/api/config') {
      if (request.method === 'GET' && control.configError) return respond(request, {detail: control.configError}, 503)
      if (request.method === 'PUT') {
        if (control.saveError) return respond(request, {detail: control.saveError}, 503)
        saved = copy(request.data)
        if (control.holdSave) return
      }
      return respond(request, saved)
    }
    if (path === '/api/words') return respond(request, catalog)
    if (path === '/api/status') return respond(request, {server_time: '2026-10-21T12:00:00Z'})
    if (path === '/api/llm') {
      if (request.method === 'PUT') {
        model = {mode: 'custom', base_url: request.data.base_url, model: request.data.model,
          thinking: request.data.thinking, key_hint: 'test-only'}
      }
      return respond(request, model)
    }
    if (path === '/api/scene/templates') return respond(request, {templates: [], examples: []})
    if (path === '/api/scene/usage') return respond(request, {day:'2026-10-21',attempts:0,successes:0,limit:20,remaining:20})
    if (path === '/api/scene/generate') {
      return control.generationError
        ? respond(request, {detail: control.generationError}, 503)
        : respond(request, SCENE)
    }
    assert.fail('Unexpected classroom path: ' + path)
  })
  state.storage.token += '-scene-flow-' + (++classroomNumber)
  return {state, control, saved: () => copy(saved)}
}

async function customDraft(service, grade = 6) {
  const today = page('today')
  await today.onShow()
  await today.onGrade(pick(grade - 1))
  today.onDuration(pick(2))
  today.onWordCount(pick(4))
  today.onDifficulty(pick(2))
  today.onChinese({detail: {value: false}})
  today.onMode({currentTarget: {dataset: {value: 'zh2en'}}})
  const editor = await openEditor(today, service.state)
  editor.onDescInput({detail: {value: DESCRIPTION}})
  await editor.onGenerate()
  editor.onField(input('opening', EDITED_OPENING))
  return {today, editor}
}

async function arrange(editor) {
  assert.equal(typeof editor.onSaveAndArrange, 'function', 'the scene editor must offer an explicit save-and-arrange action')
  await editor.onSaveAndArrange()
}

async function enterOwnModel() {
  const settings = page('settings')
  await settings.onShow()
  settings.onLlmInput(input('base_url', 'https://model.example/v1'))
  settings.onLlmInput(input('model', 'test-roleplay-model'))
  settings.onLlmInput(input('api_key', 'test-only-roleplay-api-key'))
  await settings.onSaveLlm()
  assert.equal(settings.data.llm.mode, 'custom')
  assert.equal(settings.data.llmForm.api_key, '')
  settings.onHide()
}

async function openEditor(today, state) {
  today.goScenes()
  const destination = new URL(state.navigations.at(-1).url, 'https://mini.example')
  assert.equal(destination.pathname, '/pages/scenes/index')
  today.onHide()
  const editor = page('scenes', Object.fromEntries(destination.searchParams))
  await editor.onShow()
  return editor
}

for (const grade of [1, 6, 9]) {
  test(`grade ${grade} learner can configure own model, design and edit a scene, and save an explicit role-play plan`, async () => {
    const service = classroom()
    await enterOwnModel()
    assert.ok(!JSON.stringify(service.state.storage).includes('test-only-roleplay-api-key'))
    const today = page('today')
    await today.onShow()
    await today.onGrade(pick(grade - 1))
    today.onDuration(pick(2))
    const editor = await openEditor(today, service.state)
    editor.onDescInput({detail: {value: DESCRIPTION}})
    await editor.onGenerate()
    const generate = service.state.requests.find(request => request.url.includes('/api/scene/generate'))
    assert.deepEqual(generate.data, {description: DESCRIPTION, grade})
    assert.deepEqual(editor.data.form, SCENE)
    assert.equal(service.state.requests.filter(request => request.url.includes('/api/config') && request.method === 'PUT').length, 0)
    editor.onField(input('opening', EDITED_OPENING))
    await editor.onSave()
    assert.deepEqual(service.saved().scene, {...SCENE, opening: EDITED_OPENING})
    assert.deepEqual(editor.data.current, service.saved().scene)
    editor.onHide()

    // The shipped UI requires this separate explicit mode choice after return.
    // This control case proves creation works; the audit records the missing handoff.
    await today.onShow()
    today.onMode({currentTarget: {dataset: {value: 'scene'}}})
    await today.onSave()
    today.onHide()
    assert.equal(service.saved().mode, 'scene')
    assert.equal(service.saved().grade, grade)
    assert.equal(service.saved().duration_minutes, 15)
    assert.equal(service.saved().scene.opening, EDITED_OPENING)
    assert.ok(service.state.requests.every(request => new URL(request.url).searchParams.get('student_id') === 's001'))
    assert.ok(service.state.requests.filter(request => !request.url.includes('/api/llm'))
      .every(request => !JSON.stringify(request.data || {}).includes('test-only-roleplay-api-key')))
  })
}

test('a failed scene generation leaves the learner able to finish and save their own design manually', async () => {
  const service = classroom()
  service.control.generationError = '模型暂不可用，请检查自己的模型设置'
  const editor = page('scenes', {grade: '6'})
  await editor.onShow()
  editor.onDescInput({detail: {value: DESCRIPTION}})
  await editor.onGenerate()
  assert.match(editor.data.error, /生成失败/)
  assert.equal(editor.data.description, DESCRIPTION)
  assert.equal(editor.data.busy, false)
  assert.equal(service.saved().scene, null)
  for (const [field, value] of Object.entries(SCENE)) editor.onField(input(field, value))
  await editor.onSave()
  assert.deepEqual(service.saved().scene, SCENE)
  assert.equal(editor.data.error, '')
  editor.onHide()
})

test('a failed scene save preserves the edited design and cannot report it as saved', async () => {
  const service = classroom()
  const editor = page('scenes', {grade: '6'})
  await editor.onShow()
  editor.onDescInput({detail: {value: DESCRIPTION}})
  await editor.onGenerate()
  editor.onField(input('opening', EDITED_OPENING))
  service.control.saveError = '场景暂时无法保存，请重试'
  await editor.onSave()
  assert.equal(service.saved().scene, null)
  assert.equal(editor.data.current, null)
  assert.equal(editor.data.form.opening, EDITED_OPENING)
  assert.equal(editor.data.notice, '')
  assert.equal(editor.data.error, service.control.saveError)
  assert.equal(service.state.toasts.length, 0)
  service.control.saveError = null
  await editor.onSave()
  assert.equal(service.saved().scene.opening, EDITED_OPENING)
  editor.onHide()
})

test('save-and-arrange selects role-play in the same learner draft without saving other unconfirmed plan fields', async () => {
  const service = classroom()
  const {today, editor} = await customDraft(service)
  global.getCurrentPages = () => [{route: 'pages/today/index'}, {route: 'pages/scenes/index'}]
  const back = []
  wx.navigateBack = options => back.push(options)
  await arrange(editor)
  assert.equal(back.length, 1)
  assert.equal(back[0].delta, 1)
  assert.deepEqual(service.saved(), {...config, scene: {...SCENE, opening: EDITED_OPENING}})
  editor.onHide()
  await today.onShow()
  assert.equal(today.data.form.mode, 'scene')
  assert.equal(today.data.form.grade, 6)
  assert.equal(today.data.form.duration_minutes, 15)
  assert.equal(today.data.form.practice_words, 5)
  assert.equal(today.data.form.difficulty, 'challenge')
  assert.equal(today.data.form.chinese_help, false)
  assert.equal(today.data.form.scene.opening, EDITED_OPENING)
  assert.match(today.data.notice, /已选场景对话.*保存今日安排/)
  await today.onSave()
  assert.equal(service.saved().mode, 'scene')
  assert.equal(service.saved().grade, 6)
  assert.equal(service.saved().practice_words, 5)
  assert.equal(today.data.notice, '')
  today.onHide()
  delete global.getCurrentPages
})

test('direct scene entry can arrange the saved scene through the correct Today navigation', async () => {
  const service = classroom({...config, grade: 9})
  const editor = page('scenes')
  await editor.onShow()
  for (const [field, value] of Object.entries(SCENE)) editor.onField(input(field, value))
  await arrange(editor)
  assert.equal(service.state.navigations.at(-1).url, '/pages/today/index')
  editor.onHide()
  const today = page('today')
  await today.onShow()
  assert.equal(today.data.form.mode, 'scene')
  assert.equal(today.data.form.grade, 9)
  assert.equal(service.saved().mode, 'full')
  today.onHide()
})

test('a new Today page after navigation fallback retains the originating learner unsaved plan', async () => {
  const service = classroom()
  const {editor} = await customDraft(service)
  await arrange(editor)
  editor.onHide()
  const replacement = page('today')
  await replacement.onShow()
  assert.equal(replacement.data.form.mode, 'scene')
  assert.equal(replacement.data.form.grade, 6)
  assert.equal(replacement.data.form.duration_minutes, 15)
  assert.equal(replacement.data.form.practice_words, 5)
  assert.equal(replacement.data.form.difficulty, 'challenge')
  assert.equal(replacement.data.form.chinese_help, false)
  assert.equal(service.saved().grade, 1)
  assert.equal(service.saved().mode, 'full')
  replacement.onHide()
})

test('a delayed native-back failure cannot navigate after the learner has already left the editor', async () => {
  const service = classroom()
  const {today, editor} = await customDraft(service)
  global.getCurrentPages = () => [{route: 'pages/today/index'}, {route: 'pages/scenes/index'}]
  let backOptions
  wx.navigateBack = options => {backOptions = options}
  await arrange(editor)
  assert.ok(backOptions)
  const navigations = service.state.navigations.length
  editor.onHide()
  backOptions.fail({errMsg: 'navigation already changed'})
  assert.equal(service.state.navigations.length, navigations)
  await today.onShow()
  assert.equal(today.data.form.mode, 'scene')
  today.onHide()
  delete global.getCurrentPages
})

test('a failed save-and-arrange stays in the editor and cannot activate an unsaved scene', async () => {
  const service = classroom()
  const {today, editor} = await customDraft(service)
  service.control.saveError = '场景保存失败，请重试'
  const navigations = service.state.navigations.length
  await arrange(editor)
  assert.equal(service.state.navigations.length, navigations)
  assert.equal(editor.data.form.opening, EDITED_OPENING)
  assert.equal(editor.data.current, null)
  assert.equal(editor.data.error, service.control.saveError)
  editor.onHide()
  await today.onShow()
  assert.equal(today.data.form.mode, 'zh2en')
  assert.equal(today.data.form.scene, null)
  today.onHide()
})

test('a late save completion after the editor is hidden cannot navigate or select scene mode', async () => {
  const service = classroom()
  const {today, editor} = await customDraft(service)
  service.control.holdSave = true
  assert.equal(typeof editor.onSaveAndArrange, 'function')
  const pending = editor.onSaveAndArrange()
  await new Promise(resolve => setImmediate(resolve))
  const request = service.state.requests.find(request => request.method === 'PUT')
  assert.ok(request)
  const navigations = service.state.navigations.length
  editor.onHide()
  respond(request, request.data)
  await pending
  assert.equal(service.state.navigations.length, navigations)
  await today.onShow()
  assert.equal(today.data.form.mode, 'zh2en')
  assert.equal(today.data.form.scene.opening, EDITED_OPENING)
  today.onHide()
})

test('scene activation cannot cross a classroom change or be revived after switching back', async () => {
  const service = classroom()
  const {today, editor} = await customDraft(service)
  await arrange(editor)
  editor.onHide()
  const originalConnection = copy(service.state.storage)
  service.state.storage = {...originalConnection, studentId: 's002'}
  await today.onShow()
  assert.equal(today.data.form.mode, 'full')
  assert.equal(today.data.form.grade, 1)
  assert.equal(today.data.notice, '')
  today.onHide()
  service.state.storage = originalConnection
  await today.onShow()
  assert.equal(today.data.form.mode, 'full')
  assert.equal(today.data.notice, '')
  today.onHide()
})

test('an unsuccessful visit to another classroom still discards an older scene activation', async () => {
  const service = classroom()
  const {today, editor} = await customDraft(service)
  await arrange(editor)
  editor.onHide()
  const originalConnection = copy(service.state.storage)
  service.state.storage = {...originalConnection, studentId: 's002'}
  service.control.configError = '另一个课堂暂时无法读取'
  await today.onShow()
  assert.equal(today.data.ready, false)
  today.onHide()
  service.state.storage = originalConnection
  service.control.configError = null
  await today.onShow()
  assert.equal(today.data.form.mode, 'zh2en')
  assert.equal(today.data.notice, '')
  today.onHide()
})

test('a scene selection becomes stale if another scene replaces it before Today loads', async () => {
  const service = classroom()
  const {today, editor} = await customDraft(service)
  await arrange(editor)
  editor.onHide()
  const api = require('../miniprogram/utils/english-api')
  await api.saveConfig({...service.saved(), scene: {...SCENE, name: '后来保存的场景'}})
  await today.onShow()
  assert.equal(today.data.form.mode, 'zh2en')
  assert.equal(today.data.form.scene.name, '后来保存的场景')
  assert.equal(today.data.notice, '')
  today.onHide()
})

test('the model-settings detour preserves the learner own idea and editable fields for their classroom', async () => {
  const service = classroom()
  const {today, editor} = await customDraft(service)
  assert.equal(typeof editor.goModelSettings, 'function')
  editor.goModelSettings()
  assert.equal(service.state.navigations.at(-1).url, '/pages/settings/index')
  editor.onUnload()
  await enterOwnModel()
  await today.onShow()
  const reopened = await openEditor(today, service.state)
  assert.equal(reopened.data.description, DESCRIPTION)
  assert.equal(reopened.data.form.opening, EDITED_OPENING)
  assert.equal(reopened.data.grade, 6)
  assert.equal(reopened.data.current, null)
  reopened.onHide()
})

test('the model-settings detour cannot turn an unread grade into an assumed first-grade draft', async () => {
  const service = classroom({...config, grade: 9})
  const editor = page('scenes')
  assert.equal(editor.data.gradeReady, false)
  editor.goModelSettings()
  editor.onUnload()
  const reopened = page('scenes')
  assert.equal(reopened.data.gradeReady, false)
  await reopened.onShow()
  assert.equal(reopened.data.grade, 9)
  reopened.onHide()
})

test('a saved model-settings detour draft is discarded when the classroom changes', async () => {
  const service = classroom()
  const {editor} = await customDraft(service)
  editor.goModelSettings()
  editor.onUnload()
  service.state.storage = {...service.state.storage, studentId: 's002'}
  const reopened = page('scenes')
  await reopened.onShow()
  assert.equal(reopened.data.description, '')
  assert.equal(reopened.data.form.opening, '')
  assert.equal(reopened.data.grade, 1)
  reopened.onHide()
})

test('the external-AI prompt names the selected grade and preserves the learner own description', async () => {
  const service = classroom()
  const {today, editor} = await customDraft(service, 9)
  let copied = ''
  wx.setClipboardData = options => {copied = options.data; if (options.success) options.success()}
  editor.onCopyPrompt()
  assert.match(copied, /9\s*年级/)
  assert.ok(copied.includes(DESCRIPTION))
  editor.setData({copyText: '孩子现在读 当前 年级。请按五字段生成。'})
  editor.onCopyPrompt()
  assert.doesNotMatch(copied, /当前\s*年级/)
  assert.match(copied, /9\s*年级/)
  editor.onHide()
  today.onHide()
})

test('student-visible scene actions distinguish planning from storing a scene for full practice', () => {
  const scenes = fs.readFileSync(require('node:path').join(__dirname, '../miniprogram/pages/scenes/index.wxml'), 'utf8')
  const today = fs.readFileSync(require('node:path').join(__dirname, '../miniprogram/pages/today/index.wxml'), 'utf8')
  assert.match(scenes, /bindtap="onSaveAndArrange"[^>]*>保存并去安排练习</)
  assert.match(scenes, /bindtap="onSave"[^>]*>仅保存场景</)
  assert.match(scenes, /bindtap="goModelSettings"/)
  assert.match(scenes, /\{\{grade\}\}.*年级/)
  assert.match(scenes, /完整练习.*词汇/)
  assert.match(today, /\{\{notice\}\}/)
  assert.match(today, /自己设计场景/)
})
