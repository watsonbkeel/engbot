const test=require('node:test'); const assert=require('node:assert/strict')
const {computeStatus,computeRows}=require('../miniprogram/utils/pi-status')
const now=Date.parse('2026-10-21T12:00:00Z'); const time=seconds=>new Date(now-seconds*1000).toISOString()
const state=(brain=0,pi=0,ssh=true,checked=0)=>({server_time:time(0),brain_last_seen:time(brain),pi_last_seen:time(pi),pi_ssh_ok:ssh,pi_ssh_checked_at:time(checked)})
test('brain expires after sixty seconds, including settings row',()=>{
  assert.equal(computeStatus(state(60,40)).level,'yellow'); assert.equal(computeStatus(state(61,40)).level,'red')
  assert.equal(computeRows(state(61,40)).brain.ok,false)
})
test('future and malformed heartbeat timestamps never report online',()=>{
  assert.equal(computeStatus(state(-1,0)).level,'red'); assert.equal(computeRows(state(-1,0)).brain.ok,false)
  assert.equal(computeRows({...state(),pi_last_seen:'bad date'}).edge.ok,false)
})
test('SSH results expire and stale success does not claim the Pi is on',()=>{
  assert.equal(computeStatus(state(0,40,true,61)).level,'gray'); assert.equal(computeRows(state(0,40,true,61)).piPower.ok,false)
  assert.match(computeRows(state(0,40,true,61)).piPower.text,/过期|待确认/)
})
test('fresh active edge proves Pi power even when SSH is not configured',()=>{
  assert.equal(computeRows(state(0,0,null)).piPower.ok,true)
})
