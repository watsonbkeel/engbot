// Millisecond thresholds; all ages are measured against the server clock.
const BRAIN_MS = 60 * 1000
const EDGE_MS = 30 * 1000
const SSH_MS = 60 * 1000
function clock(data) {
  if (!data || typeof data !== 'object') return NaN
  return data.server_time ? Date.parse(data.server_time) : Date.now()
}
function age(now, iso) {
  if (!iso) return Infinity
  const value = now - Date.parse(iso)
  return Number.isFinite(value) && value >= 0 ? value : Infinity
}
function hm(iso) {
  const t = new Date(iso)
  if (!Number.isFinite(t.getTime())) return ''
  const pad = n => n < 10 ? '0' + n : String(n)
  return `${pad(t.getHours())}:${pad(t.getMinutes())}`
}
function computeStatus(data) {
  const now = clock(data)
  if (!Number.isFinite(now)) return {level:'red', text:'状态数据格式不正确，请刷新'}
  if (age(now, data.brain_last_seen) > BRAIN_MS) return {level:'red', text:'大脑服务未连接'}
  if (age(now, data.pi_last_seen) <= EDGE_MS) return {level:'green', text:'树莓派在线'}
  const last = hm(data.pi_last_seen)
  const suffix = last ? ` · 最后在线 ${last}` : ''
  const fresh = age(now, data.pi_ssh_checked_at) <= SSH_MS
  if (fresh && data.pi_ssh_ok === true) return {level:'yellow', text:`树莓派已开机，但练习程序没运行${suffix}`}
  if (!fresh && data.pi_ssh_ok !== null && data.pi_ssh_ok !== undefined) return {level:'gray', text:`状态待确认，开机探测已过期${suffix}`}
  return {level:'gray', text:`树莓派离线${suffix}`}
}
function computeRows(data) {
  const now = clock(data)
  if (!Number.isFinite(now)) throw new Error('状态数据格式不正确')
  const brain = age(now, data.brain_last_seen) <= BRAIN_MS
  const edge = age(now, data.pi_last_seen) <= EDGE_MS
  const fresh = age(now, data.pi_ssh_checked_at) <= SSH_MS
  let power = {label:'树莓派开机', ok:false, text:'未配置开机探测'}
  if (edge) power = {label:'树莓派开机', ok:true, text:'已开机（练习程序在线）'}
  else if (data.pi_ssh_ok !== null && data.pi_ssh_ok !== undefined) {
    power = {label:'树莓派开机', ok:fresh && data.pi_ssh_ok === true,
      text:!fresh ? '探测已过期，状态待确认' : data.pi_ssh_ok === true ? '已开机' : '未开机或不可达'}
  }
  return {public:{label:'公共服务',ok:true,text:'正常'}, brain:{label:'大脑服务',ok:brain,text:brain?'在线':'未连接'}, piPower:power,
    edge:{label:'练习程序',ok:edge,text:edge?'运行中':'没在运行'}}
}
module.exports = {computeStatus, computeRows}
