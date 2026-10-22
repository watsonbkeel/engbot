const test = require('node:test')
const assert = require('node:assert/strict')
const { copy, connection, config, catalog, environment, respond, page } = require('./helpers.cjs')

const oldScene = { name: 'Old library', robot_role: 'Librarian', student_role: 'Student', goal: 'Borrow a book', opening: 'Hello' }
const newScene = { ...oldScene, name: 'New shop', goal: 'Buy an apple' }
const oldItems = [{ id: 'g1_story_01', title: 'Grade 1 story', type: 'story', duration_seconds: 80 }]
const newItems = [{ id: 'g9_story_01', title: 'Grade 9 story', type: 'story', duration_seconds: 90 }]

test('a late initial scene read cannot replace a scene that has just been saved', async () => {
  const state = environment()
  const p = page('scenes')
  const loading = p.load()
  respond(state.requests[0], { ...config, scene: oldScene })
  for (const [field, value] of Object.entries(newScene)) {
    p.onField({ currentTarget: { dataset: { field } }, detail: { value } })
  }
  const saving = p.onSave()
  respond(state.requests[2], { ...config, scene: oldScene })
  await Promise.resolve()
  respond(state.requests[3], { ...config, scene: newScene })
  await saving
  assert.equal(p.data.current.name, 'New shop')
  respond(state.requests[1], { templates: [oldScene], examples: [] })
  await loading
  assert.equal(p.data.current.name, 'New shop')
  assert.equal(p.data.form.name, 'New shop')
  assert.equal(p.data.loading, false)
  assert.equal(p.data.saving, false)
})

test('a late initial scene read cannot restore a scene after confirmed clearing', async () => {
  const state = environment()
  const p = page('scenes')
  const loading = p.load()
  respond(state.requests[0], { ...config, scene: oldScene })
  p.setData({ current: oldScene, form: copy(oldScene) })
  const clearing = p.onClear()
  await Promise.resolve()
  respond(state.requests[2], { ...config, scene: oldScene })
  await Promise.resolve()
  respond(state.requests[3], { ...config, scene: null })
  await clearing
  respond(state.requests[1], { templates: [oldScene], examples: [] })
  await loading
  assert.equal(p.data.current, null)
  assert.equal(p.data.form.name, '')
  assert.equal(p.data.loading, false)
  assert.equal(p.data.saving, false)
})

test('scene generation follows the unsaved plan grade without saving the plan', async () => {
  const state = environment((o, path) => respond(o, path === '/api/words' ? catalog
    : path === '/api/scene/templates' ? { templates: [], examples: [] }
      : path === '/api/scene/generate' ? newScene : config))
  const today = page('today')
  await today.loadSaved()
  await today.onGrade({ detail: { value: '8' } })
  today.goScenes()
  const target = new URL(state.navigations[0].url, 'https://miniprogram.example')
  const scene = page('scenes', Object.fromEntries(target.searchParams))
  await scene.onShow()
  scene.onDescInput({ detail: { value: 'At a shop, buy an apple.' } })
  await scene.onGenerate()
  const generation = state.requests.find(x => x.url.includes('/api/scene/generate'))
  assert.equal(generation.data.grade, 9)
  assert.equal(today.data.form.grade, 9)
  assert.equal(scene.data.grade, 9)
  assert.equal(state.requests.filter(x => x.method === 'PUT').length, 0)
})

test('direct scene navigation and invalid draft grades use the saved grade', async () => {
  for (const options of [undefined, {}, { grade: '0' }, { grade: '13' }, { grade: '3.5' }, { grade: 'wrong' }]) {
    environment((o, path) => respond(o, path === '/api/scene/templates'
      ? { templates: [], examples: [] } : { ...config, grade: 6 }))
    const p = page('scenes', options)
    await p.onShow()
    assert.equal(p.data.grade, 6, JSON.stringify(options))
  }
})

test('direct scene generation waits for the saved grade instead of guessing grade one', async () => {
  const state = environment((o, path) => {
    if (path === '/api/scene/generate') respond(o, newScene)
  })
  const p = page('scenes')
  const loading = p.onShow()
  p.onDescInput({ detail: { value: 'At a shop, buy an apple.' } })
  await p.onGenerate()
  assert.equal(state.requests.filter(x => x.url.includes('/api/scene/generate')).length, 0)
  respond(state.requests.find(x=>new URL(x.url).pathname==='/api/config'), { ...config, grade: 6 })
  respond(state.requests.find(x=>new URL(x.url).pathname==='/api/scene/templates'), { templates: [], examples: [] })
  await loading
  await p.onGenerate()
  const generation = state.requests.find(x => x.url.includes('/api/scene/generate'))
  assert.equal(generation.data.grade, 6)
})

test('a failed saved-grade lookup cannot silently generate a first-grade scene', async () => {
  const state = environment((o, path) => {
    if (path === '/api/config') respond(o, { detail: 'Classroom config is unavailable' }, 503)
    else respond(o, path === '/api/scene/generate' ? newScene : { templates: [], examples: [] })
  })
  const p = page('scenes')
  await p.onShow()
  p.onDescInput({ detail: { value: 'At a shop, buy an apple.' } })
  await p.onGenerate()
  assert.ok(p.data.error)
  assert.equal(state.requests.filter(x => x.url.includes('/api/scene/generate')).length, 0)
})

test('a draft grade belongs only to the classroom that opened the scene editor', async () => {
  const state = environment((o, path) => respond(o, path === '/api/scene/templates'
    ? { templates: [], examples: [] } : { ...config, grade: 6 }))
  const p = page('scenes', { grade: '9' })
  state.storage = { ...connection, studentId: 's002' }
  await p.onShow()
  assert.equal(p.data.grade, 6)
})

test('listening cannot play the previous grade list while the new grade is loading', async () => {
  const state = environment()
  const p = page('listening')
  p.setData({ items: copy(oldItems), shown: copy(oldItems) })
  const loading = p.onGrade({ detail: { value: '8' } })
  p.onPlay({ currentTarget: { dataset: { index: 0 } } })
  assert.equal(state.downloads.length, 0)
  assert.deepEqual(p.data.shown, [])
  assert.equal(p.data.loading, true)
  assert.match(state.requests[0].url, /grade=9(?:&|$)/)
  respond(state.requests[0], { grade: 9, items: newItems })
  await loading
  p.onPlay({ currentTarget: { dataset: { index: 0 } } })
  assert.match(state.downloads[0].options.url, /\/g9_story_01\/audio\?/)
  p.onHide()
})

test('returning to listening clears the old classroom list before the grade lookup completes', async () => {
  const state = environment()
  const p = page('listening')
  p.setData({ items: copy(oldItems), shown: copy(oldItems), notReady: true })
  p.onHide()
  state.storage = { ...connection, studentId: 's002' }
  const loading = p.onShow()
  assert.equal(p.data.loading, true)
  assert.equal(p.data.notReady, false)
  assert.deepEqual(p.data.shown, [])
  p.onPlay({ currentTarget: { dataset: { index: 0 } } })
  assert.equal(state.downloads.length, 0)
  respond(state.requests[0], { detail: 'Cannot read classroom grade' }, 503)
  await loading
  assert.equal(p.data.loading, false)
  assert.ok(p.data.error)
  assert.deepEqual(p.data.shown, [])
})

test('the report labels history and cumulative evidence without presenting today as new mastery', async () => {
  environment((o, path) => respond(o, path === '/api/progress'
    ? { today: '2026-10-21', words: [
      { word_id: 'a', word: 'apple', status: 2, last_practiced_date: '2026-10-21', unclear_count: 1, used_word_count: 7, imitated_count: 2 },
      { word_id: 'b', word: 'book', status: 1, last_practiced_date: '2026-10-21', unclear_count: 0 },
      { word_id: 'c', word: 'cat', status: 2, last_practiced_date: '2026-10-20', unclear_count: 0 }
    ] } : { ...config, mode: 'zh2en' }))
  const p = page('english-result')
  await p.refresh()
  assert.equal(p.data.loaded, true)
  assert.equal(p.data.todayWords.length, 2)
  assert.equal(p.data.todayWords[0].status, 2)
  assert.equal(p.data.todayWords[0].stateText, '曾独立说出')
  assert.equal(p.data.todayWords[1].stateText, '曾听懂')
  assert.equal(p.data.todayWords[0].evidenceText, '累计回答含目标词 7 次；累计跟读/模仿记录 2 次（不代表独立表达）')
  assert.equal(p.data.speakingCount, 1)
  assert.equal(p.data.listeningCount, 1)
  assert.equal(p.data.modeScene, '听中文说英文')
})
