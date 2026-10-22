// Every async effect belongs to one visible page, request lane, and classroom.
const api = require('./english-api')
function show(page) { page._hidden = false; page._life = (page._life || 0) + 1; page._lanes = {} }
function hide(page) { page._hidden = true; page._life = (page._life || 0) + 1; page._lanes = {} }
function visible(page) { return page._hidden !== true }
// Keep a page/classroom boundary without invalidating sibling request lanes.
function guard(page) {
  const life = page._life || 0
  const identity = api.connectionIdentity()
  return () => visible(page) && (page._life || 0) === life && api.connectionIdentity() === identity
}
function begin(page, lane) {
  const active = guard(page)
  const lanes = page._lanes || (page._lanes = {})
  const serial = lanes[lane] = (lanes[lane] || 0) + 1
  return () => active() && page._lanes[lane] === serial
}
module.exports = { show, hide, begin, visible, guard }
