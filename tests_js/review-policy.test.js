const test = require('node:test')
const assert = require('node:assert/strict')
const {connection, environment, respond, page} = require('./helpers.cjs')
const SCENE = {name:'My shop',robot_role:'Customer',student_role:'Shopkeeper',goal:'Sell two pencils',opening:'Welcome!'}
const USAGE = {day:'2026-10-21',attempts:2,successes:1,limit:20,remaining:18,successes_since_version:'0.3.4'}

test('model fallback starts disabled and only an explicit switch is submitted', async () => {
  const state=environment(o=>respond(o,{mode:'custom',...o.data}))
  const p=page('settings')
  assert.equal(p.data.allowPlatformFallback,false)
  p.data.llmForm={base_url:'https://model.example',model:'m1',api_key:'fixture-only-private-key'}
  await p.onSaveLlm()
  assert.equal(state.requests[0].data.allow_platform_fallback,false)
  p.onFallback({detail:{value:true}})
  await p.onSaveLlm()
  assert.equal(state.requests[1].data.allow_platform_fallback,true)
  assert.ok(!JSON.stringify(state.storage).includes('private-key'))
})

test('saved fallback choice and recent failed routing are shown in settings', async () => {
  environment(o=>respond(o,{mode:'custom',base_url:'https://model.example',model:'m1',allow_platform_fallback:true,
    last_status:'fallback',last_error:'自带模型额度不足',last_used_at:'2026-10-21T10:00:00+08:00'}))
  const p=page('settings');await p.loadLlm()
  assert.equal(p.data.allowPlatformFallback,true)
  assert.match(p.data.modelStatusText,/平台/)
  assert.match(p.data.modelStatusText,/额度不足/)
})

test('late model load cannot undo a newly selected fallback preference', async () => {
  const state=environment();const p=page('settings')
  const loading=p.loadLlm();p.onFallback({detail:{value:true}})
  respond(state.requests[0],{mode:'custom',allow_platform_fallback:false})
  await loading
  assert.equal(p.data.allowPlatformFallback,true)
})

test('clearing own model resets fallback choice and clears its status', async () => {
  environment(o=>respond(o,{mode:'platform',allow_platform_fallback:false}))
  const p=page('settings');p.data.allowPlatformFallback=true;p.data.modelStatusText='Old fallback'
  await p.onClearLlm()
  assert.equal(p.data.allowPlatformFallback,false)
  assert.equal(p.data.modelStatusText,'')
})

test('scene generation displays the actual fallback while preserving the five-field form', async () => {
  const state=environment((o,path)=>{
    if(path==='/api/scene/generate')return o.success({statusCode:200,data:SCENE,header:{'x-model-provider':'platform','x-model-fallback':'true'}})
    if(path==='/api/scene/usage')return respond(o,USAGE)
    assert.fail(path)
  })
  const p=page('scenes',{grade:'4'});p.data.description='我当文具店员，我想给顾客介绍铅笔'
  await p.onGenerate()
  assert.deepEqual(p.data.form,SCENE)
  assert.match(p.data.notice,/平台/)
  assert.match(p.data.notice,/回退/)
  assert.deepEqual(p.data.usage,USAGE)
  assert.equal(state.requests.filter(r=>r.url.includes('/generate')).length,1)
})

test('failed scene generation refreshes usage but leaves the edited scene intact', async () => {
  environment((o,path)=>respond(o,path==='/api/scene/usage'?USAGE:{detail:'自己的模型暂不可用'},path==='/api/scene/usage'?200:503))
  const p=page('scenes',{grade:'4'});p.data.description='我当文具店员，我想给顾客介绍铅笔';p.data.form={...SCENE}
  await p.onGenerate()
  assert.deepEqual(p.data.form,SCENE)
  assert.equal(p.data.usage.attempts,2)
  assert.match(p.data.error,/自己的模型/)
})

test('unavailable usage does not look like zero used or prevent manual scene editing', async () => {
  environment(o=>respond(o,{detail:'次数暂不可读'},503))
  const p=page('scenes',{grade:'4'});p.data.usage={...USAGE}
  await p.refreshUsage()
  assert.equal(p.data.usage,null)
  assert.match(p.data.usageError,/暂不可读/)
  p.onField({currentTarget:{dataset:{field:'name'}},detail:{value:'My new shop'}})
  assert.equal(p.data.form.name,'My new shop')
})

test('late usage response cannot cross classroom identity or hidden page', async () => {
  const state=environment();const p=page('scenes',{grade:'4'})
  const loading=p.refreshUsage();p.onHide();state.storage={...connection,studentId:'s002'}
  const updates=p.updates.length
  respond(state.requests[0],USAGE);await loading
  assert.equal(p.updates.length,updates)
  assert.equal(p.data.usage,null)
})

test('public API errors retain a safe support request id and stable code', async () => {
  environment(o=>o.success({statusCode:503,data:{detail:'模型暂不可用',error_code:'CustomModelUnavailable',request_id:'a'.repeat(32)},header:{'X-Request-ID':'a'.repeat(32)}}))
  const api=require('../miniprogram/utils/english-api')
  await assert.rejects(api.sceneGenerate('我的图书馆场景',4),e=>e.code==='CustomModelUnavailable'&&e.requestId==='a'.repeat(32)&&e.message.includes('反馈编号'))
})

for (const edit of ['description', 'field', 'template', 'example']) {
  test(`editing ${edit} during generation refreshes consumed usage without replacing the new draft`, async () => {
    const state=environment((o,path)=>{if(path==='/api/scene/usage')respond(o,USAGE)})
    const p=page('scenes',{grade:'4'});p.data.description='我当文具店员，我想给顾客介绍铅笔'
    p.data.templates=[{...SCENE,name:'Changed template'}];p.data.examples=['Changed example']
    const pending=p.onGenerate()
    if(edit==='description')p.onDescInput({detail:{value:'Changed description'}})
    if(edit==='field')p.onField({currentTarget:{dataset:{field:'name'}},detail:{value:'Changed field'}})
    if(edit==='template')p.onTemplate({currentTarget:{dataset:{index:0}}})
    if(edit==='example')p.onExample({currentTarget:{dataset:{index:0}}})
    const draft=JSON.stringify({form:p.data.form,description:p.data.description})
    respond(state.requests.find(r=>r.url.includes('/generate')),SCENE)
    await pending
    assert.equal(JSON.stringify({form:p.data.form,description:p.data.description}),draft)
    assert.equal(state.requests.filter(r=>r.url.includes('/usage')).length,1)
    assert.deepEqual(p.data.usage,USAGE)
  })
}

test('a generation finishing after the classroom changes must not refresh the new classroom usage', async () => {
  const state=environment();const p=page('scenes',{grade:'4'});p.data.description='我当文具店员，我想给顾客介绍铅笔'
  const pending=p.onGenerate();state.storage={...connection,studentId:'s002'}
  respond(state.requests[0],SCENE);await pending
  assert.equal(state.requests.length,1)
  assert.equal(p.data.usage,null)
})
