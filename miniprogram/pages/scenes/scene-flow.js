const api = require('../../utils/english-api')
const SCENE_FIELDS = ['name', 'robot_role', 'student_role', 'goal', 'opening']
let practiceSelection = null
let editorDraft = null
let planDraft = null
function sceneKey(scene) { return JSON.stringify(SCENE_FIELDS.map(key => scene && scene[key])) }
function currentIdentity() {
  const identity = api.connectionIdentity()
  if (practiceSelection && practiceSelection.identity !== identity) practiceSelection = null
  if (editorDraft && editorDraft.identity !== identity) editorDraft = null
  if (planDraft && planDraft.identity !== identity) planDraft = null
  return identity
}

// This is an unsaved navigation intention, never a server config or local Key.
// Consume it only after Today has loaded the same classroom and saved scene.
function selectForPractice(scene) {
  practiceSelection = {identity: currentIdentity(), scene: sceneKey(scene)}
}
function takePracticeSelection(scene) {
  currentIdentity()
  const selection = practiceSelection
  practiceSelection = null
  return Boolean(selection && selection.scene === sceneKey(scene))
}
function clearPracticeSelection() { practiceSelection = null }

// A fallback navigation or an embedded page can create a new Today instance.
// Carry the originating unsaved plan through that one navigation as well.
function keepPlanDraft(draft) { currentIdentity(); planDraft = draft ? JSON.parse(JSON.stringify(draft)) : null }
function takePlanDraft() {
  currentIdentity()
  const draft = planDraft
  planDraft = null
  return draft
}

// Switching to the Settings tab closes a non-tab scene page. Keep only this
// explicit detour's draft in memory, and discard it at a classroom boundary.
function keepEditorDraft(draft) {
  editorDraft = {identity: currentIdentity(), value: JSON.parse(JSON.stringify(draft))}
}
function takeEditorDraft() {
  currentIdentity()
  const draft = editorDraft
  editorDraft = null
  return draft ? draft.value : null
}
module.exports = {selectForPractice, takePracticeSelection, clearPracticeSelection, keepPlanDraft, takePlanDraft, keepEditorDraft, takeEditorDraft}
