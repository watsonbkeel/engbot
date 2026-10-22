const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const {root, copy, connection, config, catalog, environment, respond, page} = require('./helpers.cjs')

test('shipped today page loads and saves the complete v3 contract only after success', async () => {
  const state = environment((o, path) => respond(o, path === '/api/words' ? catalog : o.method === 'PUT' ? o.data : config))
  const p = page('today'); await p.loadSaved()
  assert.equal(p.data.ready, true); assert.equal(p.data.wordPreview, 'apple')
  p.onDifficulty({detail:{value:'2'}}); await p.onSave()
  const body = state.requests.find(x => x.method === 'PUT').data
  assert.deepEqual(Object.keys(body).sort(), Object.keys(config).sort())
  assert.equal(body.difficulty, 'challenge'); assert.equal(body.mode, 'full'); assert.equal(body.scene, null)
  assert.equal(state.toasts.length, 1); assert.equal(p.data.wordPreview, 'apple')
})
test('shipped grade picker has nine grades and maps index eight to grade nine', async () => {
  const state = environment(o => respond(o, catalog)); const p = page('today')
  assert.equal(p.data.grades.length, 9); assert.equal(p.data.grades[8], '初三')
  await p.onGrade({detail:{value:'8'}})
  assert.equal(p.data.form.grade, 9); assert.match(state.requests[0].url, /grade=9(&|$)/)
})
test('settings sends thinking and clears successful model key without storing it locally', async () => {
  const state = environment(o => respond(o, {mode:'custom',base_url:'https://model.example/v1',model:'m1',thinking:true}))
  const p = page('settings'); p.data.llmForm={base_url:'https://model.example/v1',model:'m1',api_key:'test-only-model-key'}; p.data.thinking=true
  await p.onSaveLlm(); const req=state.requests[0]
  assert.equal(req.data.thinking, true); assert.equal(req.data.api_key, 'test-only-model-key')
  assert.equal(p.data.llmForm.api_key, ''); assert.equal(p.data.llm.mode, 'custom')
  assert.ok(!JSON.stringify(state.storage).includes('model-key'))
})
test('failed arrangement and model saves never display success', async () => {
  const state = environment(o => respond(o, {detail:'保存失败'}, 503))
  const p = page('today'); p.data.ready=true; await p.onSave()
  assert.equal(p.data.error, '保存失败'); assert.equal(state.toasts.length, 0); assert.equal(p.data.saving, false)
  const settings=page('settings'); settings.data.llmForm={base_url:'https://model.example',model:'m1',api_key:''}
  await settings.onSaveLlm(); assert.equal(settings.data.llmError,'保存失败'); assert.equal(settings.data.llmBusy,false)
})
test('result page distinguishes empty successful history from network failure', async () => {
  let failure=true
  environment((o,path) => failure ? o.fail({}) : respond(o,path==='/api/progress'?{today:'2026-10-21',words:[]}:config))
  const p=page('english-result'); await p.refresh(); assert.equal(p.data.loaded,false); assert.ok(p.data.error)
  failure=false; await p.refresh(); assert.equal(p.data.loaded,true); assert.equal(p.data.error,''); assert.deepEqual(p.data.todayWords,[])
})
test('empty classroom connection opens onboarding without sending requests', () => {
  const state=environment(); state.storage={}; const p=page('today'); p.onShow()
  assert.equal(state.requests.length,0); assert.equal(state.navigations[0].url,'/pages/onboarding/index')
})
test('model save retains longer timeout than normal classroom requests', async () => {
  const state=environment(o=>respond(o,{})); const api=require('../miniprogram/utils/english-api')
  await api.progress(); await api.saveLlm({base_url:'https://model.example',model:'m1',api_key:'test-key-long'})
  assert.equal(state.requests[0].timeout,15000); assert.equal(state.requests[1].timeout,30000)
})
test('classroom and model forms live in settings, outside today practice form', () => {
  const today=fs.readFileSync(root+'/pages/today/index.wxml','utf8'); const settings=fs.readFileSync(root+'/pages/settings/index.wxml','utf8')
  assert.match(today,/bindtap="onSave"/); assert.doesNotMatch(today,/bindinput="onLlmInput"/)
  assert.match(settings,/bindtap="onSaveConnection"/); assert.match(settings,/bindtap="onSaveLlm"/)
})
test('failed candidate connection leaves the prior working connection unchanged', async () => {
  const state=environment(o=>o.fail({})); const p=page('settings')
  p.data.connection={...connection,baseUrl:'https://bad.example'}; await p.onSaveConnection()
  assert.deepEqual(state.storage,connection); assert.ok(p.data.connMsg)
  assert.match(state.requests[0].url,/^https:\/\/bad\.example\//)
})
test('successful connection commits only after verification and ignores success after hiding', async () => {
  const state=environment(); const p=page('settings'); p.data.connection={...connection,baseUrl:'https://new.example'}
  const saving=p.onSaveConnection(); assert.deepEqual(state.storage,connection)
  p.onHide(); const updates=p.updates.length; respond(state.requests[0],config); await saving
  assert.deepEqual(state.storage,connection); assert.equal(p.updates.length,updates)
})
test('onboarding does not commit an invalid candidate or advance on a hidden response', async () => {
  const state=environment(); const p=page('onboarding'); p.data.connection={...connection,baseUrl:'https://new.example'}
  const pending=p.onTestConnection(); assert.deepEqual(state.storage,connection)
  p.onHide(); respond(state.requests[0],config); await pending
  assert.deepEqual(state.storage,connection); assert.equal(p.data.step,1)
})
test('scene navigation preserves unsaved plan fields and merges newly saved scene', async () => {
  let current=copy(config)
  environment((o,path)=>respond(o,path==='/api/words'?catalog:current))
  const p=page('today'); await p.loadSaved(); p.onMode({currentTarget:{dataset:{value:'scene'}}}); p.onDuration({detail:{value:'2'}})
  p.goScenes(); p.onHide(); current.scene={name:'Library',robot_role:'Librarian',student_role:'Student',goal:'Borrow a book',opening:'Hello'}
  await p.onShow(); p.onHide()
  assert.equal(p.data.form.mode,'scene'); assert.equal(p.data.form.duration_minutes,15); assert.equal(p.data.form.scene.name,'Library')
})
test('draft plan never crosses classroom connection boundaries', async () => {
  const state=environment((o,path)=>respond(o,path==='/api/words'?catalog:config)); const p=page('today'); await p.loadSaved()
  p.onDuration({detail:{value:'2'}}); p.onHide(); state.storage={...connection,studentId:'s002'}; await p.onShow(); p.onHide()
  assert.equal(p.data.form.duration_minutes,10)
})
test('late today status and save responses have no hidden-page effects', async () => {
  const state=environment(); const p=page('today'); p.data.ready=true
  const saving=p.onSave(); const status=p.refreshStatus(); p.onHide(); const updates=p.updates.length
  respond(state.requests[0],config); respond(state.requests[1],{server_time:'2026-10-21T10:00:00Z'})
  await Promise.all([saving,status]); assert.equal(state.toasts.length,0); assert.equal(p.updates.length,updates)
})
test('late settings model response cannot change a hidden page', async () => {
  const state=environment(); const p=page('settings'); const loading=p.loadLlm(); p.onHide(); const count=p.updates.length
  respond(state.requests[0],{mode:'platform'}); await loading; assert.equal(p.updates.length,count)
})
test('late scene generation does not replace a hidden scene', async () => {
  const state=environment(); const p=page('scenes',{grade:'1'}); p.data.description='At a library, borrow a book.'
  const pending=p.onGenerate(); p.onHide(); const count=p.updates.length
  respond(state.requests[0],{name:'Old result'}); await pending; assert.equal(p.updates.length,count)
})
test('scene template failure still loads the saved scene for editing', async () => {
  const saved={name:'Library',robot_role:'Librarian',student_role:'Student',goal:'Borrow a book',opening:'Hello'}
  environment((o,path)=>path==='/api/scene/templates'?respond(o,{detail:'missing'},404):respond(o,{...config,scene:saved}))
  const p=page('scenes'); await p.load(); assert.equal(p.data.form.name,'Library'); assert.equal(p.data.showForm,true)
})
test('scene form rejects oversized and blank values before writing config', async () => {
  const state=environment(o=>respond(o,o.method==='PUT'?o.data:config)); const p=page('scenes')
  p.data.form={name:'x'.repeat(41),robot_role:'Teacher',student_role:'Student',goal:'Read a book',opening:'Hello'}
  await p.onSave(); assert.equal(state.requests.length,0); assert.ok(p.data.error)
  p.data.form.name='  '; await p.onSave(); assert.equal(state.requests.length,0)
})
test('report never starts a config fetch after leaving during progress request', async()=>{
  const state=environment(); const p=page('english-result'); const pending=p.refresh(); p.onHide(); const count=p.updates.length
  respond(state.requests[0],{today:'2026-10-21',words:[]}); await pending
  assert.equal(state.requests.length,1); assert.equal(p.updates.length,count)
})
test('validation detail arrays become readable field messages', async()=>{
  environment(o=>respond(o,{detail:[{loc:['body','scene','name'],msg:'Too long'}]},422))
  const api=require('../miniprogram/utils/english-api'); await assert.rejects(api.saveConfig(config),e=>e.statusCode===422&&e.message==='scene.name：Too long')
})
test('skip model explicitly switches to platform and cannot advance after failure or hide', async()=>{
  const state=environment(); const p=page('onboarding'); p.data.step=2
  const pending=p.onSkipLlm(); assert.equal(state.requests[0].method,'DELETE'); assert.equal(p.data.step,2)
  respond(state.requests[0],{detail:'Unavailable'},503); await pending; assert.equal(p.data.step,2); assert.ok(p.data.llmError)
  const next=p.onSkipLlm(); p.onHide(); respond(state.requests[1],{mode:'platform'}); await next; assert.equal(p.data.step,2)
})
test('editing model configuration while its load is pending keeps typed input', async()=>{
  const state=environment(); const p=page('settings'); const pending=p.loadLlm()
  p.onLlmInput({currentTarget:{dataset:{field:'model'}},detail:{value:'my-new-model'}})
  respond(state.requests[0],{mode:'custom',model:'old-model'}); await pending
  assert.equal(p.data.llmForm.model,'my-new-model')
})
test('editing scene while initial load is pending keeps the typed form', async()=>{
  const state=environment(); const p=page('scenes'); const pending=p.load()
  p.onField({currentTarget:{dataset:{field:'name'}},detail:{value:'My new scene'}})
  respond(state.requests[0],{...config,scene:{name:'Old scene'}}); respond(state.requests[1],{templates:[],examples:[]}); await pending
  assert.equal(p.data.form.name,'My new scene')
})
test('pending arrangement save freezes every editor and accepts edits again after completion', async()=>{
  const state=environment((o,path)=>{if(o.method==='GET')respond(o,path==='/api/words'?catalog:config)})
  const p=page('today');await p.loadSaved();const pending=p.onSave();const submitted=state.requests.find(x=>x.method==='PUT')
  p.onMode({currentTarget:{dataset:{value:'zh2en'}}});p.onChinese({detail:{value:false}})
  p.onDuration({detail:{value:'2'}});p.onWordCount({detail:{value:'4'}});p.onDifficulty({detail:{value:'2'}})
  p.onGrade({detail:{value:'8'}});p.onSemester({detail:{value:'1'}});p.onGroup({detail:{value:'0'}});p.goScenes()
  const during={form:copy(p.data.form),dirty:copy(p._dirty),durationIndex:p.data.durationIndex,wordCountIndex:p.data.wordCountIndex,difficultyIndex:p.data.difficultyIndex,requests:state.requests.length,navigations:state.navigations.length}
  respond(submitted,config);await pending
  assert.deepEqual(during.form,config);assert.deepEqual(during.dirty,{})
  assert.deepEqual([during.durationIndex,during.wordCountIndex,during.difficultyIndex],[1,2,0])
  assert.equal(during.requests,3);assert.equal(during.navigations,0);assert.equal(p.data.saving,false)
  p.onMode({currentTarget:{dataset:{value:'zh2en'}}});p.onChinese({detail:{value:false}})
  assert.equal(p.data.form.mode,'zh2en');assert.equal(p.data.form.chinese_help,false)
  assert.deepEqual(p._dirty,{mode:true,chinese_help:true})
})
test('missing-scene save confirmation can still open scene editor while general editing is frozen',async()=>{
  const state=environment();const p=page('today');p.data.ready=true;p.data.form.mode='scene'
  await p.onSave();assert.equal(state.requests.length,0);assert.equal(state.navigations.length,1)
  assert.equal(state.navigations[0].url,'/pages/scenes/index?grade=1');assert.equal(p.data.saving,false)
})
test('switching classroom releases prior model busy state and old completion cannot release a newer save',async()=>{
  const state=environment();const p=page('settings')
  p.data.llmForm={base_url:'https://model.example',model:'old-model',api_key:''}
  const oldSave=p.onSaveLlm();assert.equal(p.data.llmBusy,true)
  p.data.connection={...connection,studentId:'s002'};p.data.llmError='Old classroom error';p.data.llmOk='Old classroom notice'
  const switching=p.onSaveConnection();respond(state.requests[1],config);await switching
  assert.equal(state.storage.studentId,'s002');assert.equal(p.data.llmBusy,false);assert.equal(p.data.llmError,'');assert.equal(p.data.llmOk,'')
  respond(state.requests[2],{server_time:'2026-10-21T10:00:00Z'});respond(state.requests[3],{mode:'platform'});await Promise.resolve()
  p.onLlmInput({currentTarget:{dataset:{field:'base_url'}},detail:{value:'https://new-model.example'}})
  p.onLlmInput({currentTarget:{dataset:{field:'model'}},detail:{value:'new-model'}})
  const newSave=p.onSaveLlm();assert.equal(p.data.llmBusy,true)
  const newRequest=state.requests[4];assert.match(newRequest.url,/student_id=s002/)
  respond(state.requests[0],{mode:'custom',base_url:'https://model.example',model:'old-model'});await oldSave
  assert.equal(p.data.llmBusy,true);assert.equal(p.data.llmForm.model,'new-model');assert.equal(p.data.llmOk,'')
  respond(newRequest,{mode:'custom',base_url:'https://new-model.example',model:'new-model'});await newSave
  assert.equal(p.data.llmBusy,false);assert.equal(p.data.llm.model,'new-model')
})
test('failed classroom switch leaves original in-flight model save active',async()=>{
  const state=environment();const p=page('settings');p.data.llmForm={base_url:'https://model.example',model:'original-model',api_key:''}
  const saving=p.onSaveLlm();p.data.connection={...connection,studentId:'s002'}
  const switching=p.onSaveConnection();respond(state.requests[1],{detail:'Invalid classroom'},401);await switching
  assert.equal(state.storage.studentId,'s001');assert.equal(p.data.llmBusy,true)
  respond(state.requests[0],{mode:'custom',base_url:'https://model.example',model:'original-model'});await saving
  assert.equal(p.data.llmBusy,false);assert.equal(p.data.llm.model,'original-model')
})
