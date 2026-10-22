const test = require('node:test')
const assert = require('node:assert/strict')
const {connection, config, catalog, environment, respond, page} = require('./helpers.cjs')

const ONLINE = {
  server_time:'2026-10-21T12:00:00Z',brain_last_seen:'2026-10-21T12:00:00Z',
  pi_last_seen:'2026-10-21T12:00:00Z',pi_ssh_ok:null,pi_ssh_checked_at:null
}
async function settle() {
  // Drain promise continuations without waiting for real time.
  for (let turn=0;turn<6;turn++) await Promise.resolve()
}
function fakeClock() {
  const original={setTimeout,clearTimeout,setInterval,clearInterval}
  const timers=new Map()
  let now=0,nextId=0
  function schedule(callback,delay,repeat) {
    const id=nextId++ // WeChat-style numeric handles, including zero.
    timers.set(id,{callback,delay,due:now+delay,repeat})
    return id
  }
  global.setTimeout=(callback,delay)=>schedule(callback,delay,false)
  global.setInterval=(callback,delay)=>schedule(callback,delay,true)
  global.clearTimeout=global.clearInterval=id=>timers.delete(id)
  return {
    pending:()=>timers.size,
    async advance(milliseconds) {
      const end=now+milliseconds
      for (;;) {
        const next=[...timers.entries()].filter(([,timer])=>timer.due<=end).sort((a,b)=>a[1].due-b[1].due)[0]
        if(!next)break
        const [id,timer]=next;now=timer.due
        if(timer.repeat)timer.due+=timer.delay
        else timers.delete(id)
        timer.callback();await settle()
      }
      now=end;await settle()
    },
    restore(){Object.assign(global,original)}
  }
}
function fixture(t,name) {
  const clock=fakeClock()
  let subject
  t.after(()=>{try{if(subject)subject.onUnload()}finally{clock.restore()}})
  const state=environment((options,path)=>{
    if(path==='/api/status')return // Each real Page request is settled by the test.
    respond(options,path==='/api/words'?catalog:path==='/api/llm'?{mode:'platform'}:options.method==='PUT'?options.data:config)
  })
  subject=page(name)
  return {subject,state,clock,status:()=>state.requests.filter(options=>new URL(options.url).pathname==='/api/status')}
}

for (const name of ['settings','today']) {
  test(name+' waits for settlement before the next ten-second status delay',async t=>{
    const {subject:p,clock,status}=fixture(t,name)
    const showing=p.onShow()
    assert.equal(status().length,1)
    await clock.advance(30000)
    assert.equal(status().length,1,'an unresolved request must not overlap another poll')
    respond(status()[0],ONLINE);await showing;await settle()
    await clock.advance(9999);assert.equal(status().length,1)
    await clock.advance(1);assert.equal(status().length,2)
    await clock.advance(60000);assert.equal(status().length,2,'the second unresolved request also owns its entire poll')
  })

  test(name+' backs off 20/40/60 seconds, caps failures, and recovers to ten seconds',async t=>{
    const {subject:p,clock,status}=fixture(t,name)
    p.onShow()
    for (const [index,delay] of [20000,40000,60000,60000].entries()) {
      if(index%2)respond(status().at(-1),{detail:'暂不可用'},503)
      else status().at(-1).fail({})
      await settle()
      await clock.advance(delay-1)
      assert.equal(status().length,index+1,'no poll before the current backoff expires')
      await clock.advance(1);assert.equal(status().length,index+2)
    }
    respond(status().at(-1),ONLINE);await settle()
    if(name==='settings')assert.equal(p.data.statusError,false)
    else assert.equal(p.data.statusLevel,'green')
    await clock.advance(9999);assert.equal(status().length,5)
    await clock.advance(1);assert.equal(status().length,6)
  })

  test(name+' ignores an in-flight completion after hide and does not restart timers',async t=>{
    const {subject:p,clock,status}=fixture(t,name)
    p.onShow();await settle();p.onHide()
    const updates=p.updates.length
    respond(status()[0],ONLINE);await settle()
    assert.equal(p.updates.length,updates)
    assert.equal(clock.pending(),0)
    await clock.advance(120000);assert.equal(status().length,1)
  })

  for (const event of ['onHide','onUnload']) {
    test(name+' clears a scheduled status timer on '+event,async t=>{
      const {subject:p,clock,status}=fixture(t,name)
      p.onShow();respond(status()[0],ONLINE);await settle()
      assert.equal(clock.pending(),1)
      p[event]();assert.equal(clock.pending(),0)
      await clock.advance(60000);assert.equal(status().length,1)
    })
  }

  test(name+' reopening resets failures and an older classroom cannot write or schedule',async t=>{
    const {subject:p,state,clock,status}=fixture(t,name)
    p.onShow();status()[0].fail({});await settle()
    await clock.advance(20000)
    const old=status().at(-1)
    p.onHide();state.storage={...connection,studentId:'s002'};p.onShow()
    const fresh=status().at(-1)
    assert.notEqual(fresh,old);assert.match(fresh.url,/student_id=s002/)
    fresh.fail({});await settle()
    const updates=p.updates.length,count=status().length
    respond(old,ONLINE);await settle()
    assert.equal(p.updates.length,updates,'old classroom completion must not replace the new error')
    assert.equal(clock.pending(),1,'old classroom completion must not create another timer')
    await clock.advance(19999);assert.equal(status().length,count)
    await clock.advance(1);assert.equal(status().length,count+1,'first failure after reopening uses 20 seconds')
    assert.match(status().at(-1).url,/student_id=s002/)
  })

  test(name+' an identity change invalidates the old scheduled poll until the next show',async t=>{
    const {subject:p,state,clock,status}=fixture(t,name)
    p.onShow();respond(status()[0],ONLINE);await settle()
    state.storage={...connection,studentId:'s002'}
    await clock.advance(60000)
    assert.equal(status().length,1,'the old page generation must not poll a different classroom')
    assert.equal(clock.pending(),0)
    p.onShow();assert.equal(status().length,2);assert.match(status()[1].url,/student_id=s002/)
  })
}

test('settings connection commit clears old backoff and immediately polls the new classroom',async t=>{
  const {subject:p,clock,status}=fixture(t,'settings')
  p.onShow();status()[0].fail({});await settle();await clock.advance(5000)
  p.data.connection={...connection,studentId:'s002'}
  await p.onSaveConnection()
  assert.equal(status().length,2);assert.match(status()[1].url,/student_id=s002/)
  status()[1].fail({});await settle()
  await clock.advance(19999);assert.equal(status().length,2,'neither the old timer nor old backoff survives a commit')
  await clock.advance(1);assert.equal(status().length,3)
})

test('settings connection commit during a request rejects the old completion and keeps one new timer',async t=>{
  const {subject:p,clock,status}=fixture(t,'settings')
  p.onShow();const old=status()[0]
  p.data.connection={...connection,studentId:'s002'};await p.onSaveConnection()
  assert.equal(status().length,2)
  respond(status()[1],ONLINE);await settle()
  const updates=p.updates.length
  old.fail({});await settle()
  assert.equal(p.updates.length,updates);assert.equal(clock.pending(),1)
  await clock.advance(9999);assert.equal(status().length,2)
  await clock.advance(1);assert.equal(status().length,3);assert.match(status()[2].url,/student_id=s002/)
})
