const test=require('node:test'); const assert=require('node:assert/strict'); const fs=require('node:fs')
const {root,environment,respond,page}=require('./helpers.cjs')
const items=[{id:'s1',title:'A story',type:'story',duration_seconds:91,transcript:'Story text'},{id:'d1',title:'A dialogue',type:'dialogue',duration_seconds:110,transcript:'Dialogue text'}]
test('listening differentiates network, authentication, missing API, server failure, and empty content', async()=>{
  for (const code of [0,401,404,503]) {
    environment(o=>code?respond(o,{detail:'failure'},code):o.fail({})); const p=page('listening'); await p.loadList()
    assert.ok(p.data.error,`failure ${code} must be visible`); assert.equal(p.data.notReady,false)
  }
  environment(o=>respond(o,{items:[]})); const p=page('listening'); await p.loadList(); assert.equal(p.data.error,''); assert.equal(p.data.notReady,true)
  const markup=fs.readFileSync(root+'/pages/listening/index.wxml','utf8')
  assert.doesNotMatch(markup,/<block wx:if="\{\{!notReady\}\}">\s*<!-- 年级/)
})
test('real tap filter selects story and dialogue without an exception', async()=>{
  environment(o=>respond(o,{items})); const p=page('listening'); await p.loadList()
  p.onType({currentTarget:{dataset:{index:1}},detail:{x:20,y:10}}); assert.deepEqual(p.data.shown.map(x=>x.id),['s1'])
  p.onType({currentTarget:{dataset:{index:2}},detail:{x:20,y:10}}); assert.deepEqual(p.data.shown.map(x=>x.id),['d1'])
  assert.equal(p.data.shown[0].durationLabel,'1:50')
})
test('late audio download is aborted and cannot play after hiding',async()=>{
  const state=environment(); const p=page('listening'); p.data.shown=items
  await p.onPlay({currentTarget:{dataset:{index:0}}}); p.onHide(); const count=p.updates.length
  state.downloads[0].options.success({statusCode:200,tempFilePath:'/fake-s1.mp3'})
  assert.equal(state.downloads[0].aborted,true); assert.equal(state.audio.reduce((n,a)=>n+a.plays,0),0); assert.equal(p.updates.length,count)
})
test('newer audio choice wins when older downloads complete last',async()=>{
  const state=environment(); const p=page('listening'); p.data.shown=items
  await p.onPlay({currentTarget:{dataset:{index:0}}}); await p.onPlay({currentTarget:{dataset:{index:1}}})
  state.downloads[1].options.success({statusCode:200,tempFilePath:'/fake-d1.mp3'})
  state.downloads[0].options.success({statusCode:200,tempFilePath:'/fake-s1.mp3'})
  assert.equal(p.data.currentTitle,'A dialogue'); assert.equal(state.audio.reduce((n,a)=>n+a.plays,0),1)
})
test('unload destroys audio and stops late events from touching the page',async()=>{
  const state=environment(); const p=page('listening'); p.data.shown=items; await p.onPlay({currentTarget:{dataset:{index:0}}})
  state.downloads[0].options.success({statusCode:200,tempFilePath:'/fake-s1.mp3'}); const audio=state.audio.at(-1)
  p.onUnload(); const count=p.updates.length; audio.emit('timeUpdate'); audio.emit('error')
  assert.equal(audio.destroyed,true); assert.equal(p.updates.length,count)
})
test('pending grade lookup does not update or fetch another list after hiding',async()=>{
  const state=environment(); const p=page('listening'); const pending=p.loadGradeThenList(); p.onHide(); const count=p.updates.length
  respond(state.requests[0],{grade:9}); await pending; assert.equal(p.updates.length,count); assert.equal(state.requests.length,1)
})
test('next track uses identifiers when titles are duplicated',async()=>{
  const state=environment(); const p=page('listening'); p.data.shown=[{...items[0],title:'Same'},{...items[1],title:'Same'}]
  await p.onPlay({currentTarget:{dataset:{index:1}}}); state.downloads[0].options.success({statusCode:200,tempFilePath:'/second.mp3'}); p.onNext()
  assert.match(state.downloads[1].options.url,/\/s1\/audio\?/)
})
