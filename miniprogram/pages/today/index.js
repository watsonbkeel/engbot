const navigation = require('../../utils/english-navigation')
const api = require('../../utils/english-api')
const life = require('../../utils/page-state')
const statusPoller = require('../../utils/status-poller')
const sceneFlow = require('../scenes/scene-flow')
const { computeStatus } = require('../../utils/pi-status')
const DIFFICULTIES = ['basic','standard','challenge']
const MODES = [
  {value:'full',name:'完整练习',desc:'听词 → 说词 → 必要时跟读 → 对话'},
  {value:'en2zh',name:'听词说中文',desc:'机器人念英文，你说中文意思'},
  {value:'zh2en',name:'听中文说英文',desc:'机器人念中文，你说英文单词'},
  {value:'scene',name:'场景对话',desc:'和机器人扮演角色聊天（需先设场景）'}
]
const CONFIG_FIELDS = ['grade','semester','unit','duration_minutes','practice_words','chinese_help','difficulty','mode','scene']
function configBody(form) { const out={}; CONFIG_FIELDS.forEach(k=>{out[k]=form[k]}); return out }
Page({
  data:{
    connection:{},unconfigured:false,ready:false,loading:false,saving:false,error:'',notice:'',
    form:{grade:1,semester:1,unit:0,duration_minutes:10,practice_words:3,chinese_help:true,difficulty:'basic',mode:'full',scene:null},
    grades:['一年级','二年级','三年级','四年级','五年级','六年级','初一','初二','初三'],semesters:['上学期','下学期'],
    durations:[5,10,15,20,30],wordCounts:[1,2,3,4,5,6,7,8,9,10],
    difficulties:['起步：短问题，允许单词回答','巩固：尝试简单完整句','挑战：增加简短追问'],modes:MODES,
    groups:[],groupIndex:0,durationIndex:1,wordCountIndex:2,difficultyIndex:0,wordPreview:'',statusLevel:'gray',statusText:'正在获取状态…'
  },
  onLoad() { this._dirty = {}; this.setData({connection:api.connection()}) },
  onShow() {
    life.show(this); this.setData(navigation.pageData())
    if (!api.isConfigured(api.connection())) {statusPoller.stop(this);wx.reLaunch({url:'/pages/onboarding/index'});return}
    statusPoller.start(this)
    return this.loadSaved()
  },
  onHide() { this.keepDraft(); life.hide(this); statusPoller.stop(this); this.setData({loading:false,saving:false}) },
  onUnload() { life.hide(this); statusPoller.stop(this) },
  keepDraft() {
    if (Object.keys(this._dirty || {}).length) this._draft={identity:this._formIdentity,form:Object.assign({},this.data.form),fields:Object.keys(this._dirty)}
  },
  mark(patch) {
    if(this.data.saving)return
    this._dirty=this._dirty || {}; Object.keys(patch).forEach(k=>{this._dirty[k]=true})
    const changes={}; Object.keys(patch).forEach(k=>{changes['form.'+k]=patch[k]}); this.setData(changes)
  },
  async refreshStatus() {
    const active=life.begin(this,'status')
    try {const result=computeStatus(await api.status());if(!active())return false;this.setData({statusLevel:result.level,statusText:result.text});return true}
    catch(e) {if(active())this.setData({statusLevel:'red',statusText:'获取状态失败，检查网络和课堂连接'});return false}
  },
  async loadSaved() {
    const active=life.begin(this,'form'); const identity=api.connectionIdentity()
    if(this._formIdentity!==identity)this.setData({notice:''})
    const navigationDraft=sceneFlow.takePlanDraft()
    if(navigationDraft&&(!this._draft||this._draft.identity!==identity)){
      this._draft=navigationDraft;this._dirty={};navigationDraft.fields.forEach(key=>{this._dirty[key]=true})
    }
    if (!api.isConfigured(api.connection())) {this.setData({unconfigured:true,ready:false,loading:false,error:''});return}
    this.setData({loading:true,error:'',ready:false,unconfigured:false})
    try {
      let form=await api.config(); if(!active())return
      form=Object.assign({practice_words:3,mode:'full',scene:null},form)
      if(this._draft && this._draft.identity===identity) this._draft.fields.forEach(k=>{if(k!=='scene')form[k]=this._draft.form[k]})
      else if(this._formIdentity!==identity) {this._draft=null;this._dirty={}}
      const catalog=await api.words(form); if(!active())return
      const selectedScene=sceneFlow.takePracticeSelection(form.scene)
      if(selectedScene){form.mode='scene';this._dirty.mode=true}
      this._formIdentity=identity;this.showForm(form,catalog);this.setData({connection:api.connection(),ready:true})
      if(selectedScene){this.keepDraft();this.setData({notice:'已选场景对话，请保存今日安排后开始练习'})}
      else if(form.mode!=='scene')this.setData({notice:''})
    } catch(e) {if(active())this.setData({error:e.message})}
    finally {if(active())this.setData({loading:false})}
  },
  showForm(form,catalog) {
    this._catalog=catalog
    this.setData({form:Object.assign({practice_words:3,mode:'full',scene:null},form),groups:catalog.units,
      groupIndex:Math.max(0,catalog.units.findIndex(x=>x.value===form.unit)),
      durationIndex:Math.max(0,this.data.durations.indexOf(form.duration_minutes)),
      wordCountIndex:Math.max(0,this.data.wordCounts.indexOf(form.practice_words || 3)),
      difficultyIndex:Math.max(0,DIFFICULTIES.indexOf(form.difficulty)),wordPreview:catalog.words.slice(0,12).map(x=>x.word).join(' · ')})
  },
  async changeRange(patch) {
    if(this.data.saving)return
    this.mark(patch);const form=Object.assign({},this.data.form);const active=life.begin(this,'form')
    this.setData({loading:true,error:'',ready:false})
    try {const catalog=await api.words(form);if(active()){this.showForm(form,catalog);this.setData({ready:true})}}
    catch(e) {if(active())this.setData({error:e.message})}
    finally {if(active())this.setData({loading:false})}
  },
  onGrade(e) {return this.changeRange({grade:Number(e.detail.value)+1,unit:0})},
  onSemester(e) {return this.changeRange({semester:Number(e.detail.value)+1,unit:0})},
  onGroup(e) {const group=this.data.groups[Number(e.detail.value)];if(group)return this.changeRange({unit:group.value})},
  onDuration(e) {if(this.data.saving)return;const i=Number(e.detail.value);this.mark({duration_minutes:this.data.durations[i]});this.setData({durationIndex:i})},
  onWordCount(e) {if(this.data.saving)return;const i=Number(e.detail.value);this.mark({practice_words:this.data.wordCounts[i]});this.setData({wordCountIndex:i})},
  onDifficulty(e) {if(this.data.saving)return;const i=Number(e.detail.value);this.mark({difficulty:DIFFICULTIES[i]});this.setData({difficultyIndex:i})},
  onChinese(e) {this.mark({chinese_help:Boolean(e.detail.value)})},
  onMode(e) {if(this.data.saving)return;const mode=e.currentTarget.dataset.value;if(MODES.some(x=>x.value===mode)){this.mark({mode});if(mode!=='scene')this.setData({notice:''})}},
  goScenes() {if(this.data.saving)return;this.keepDraft();sceneFlow.keepPlanDraft(this._draft);const grade=this.data.form.grade;wx.navigateTo({url:'/pages/scenes/index'+(Number.isInteger(grade)&&grade>=1&&grade<=12?'?grade='+grade:'')})},
  goOnboard() {wx.reLaunch({url:'/pages/onboarding/index'})},
  async onSave() {
    if(this.data.loading || this.data.saving || !this.data.ready)return
    const active=life.begin(this,'save');this.setData({saving:true,error:''})
    try {
      if(this.data.form.mode==='scene' && !this.data.form.scene) {
        const go=await new Promise(resolve=>wx.showModal({title:'还没有设置场景',content:'只练场景需要先设场景。也可先保存，机器人会按普通单词对话开课。',confirmText:'去设场景',cancelText:'仍要保存',success:r=>resolve(!!r.confirm),fail:()=>resolve(null)}))
        if(!active() || go===null)return
        if(go){this.setData({saving:false});this.goScenes();return}
      }
      const saved=await api.saveConfig(configBody(this.data.form));if(!active())return
      this._dirty={};this._draft=null;this.showForm(saved,this._catalog || {units:this.data.groups,words:[]})
      this.setData({notice:''})
      wx.showToast({title:'已保存，下次唤醒生效',icon:'none'})
    } catch(e) {if(active())this.setData({error:e.message})}
    finally {if(active())this.setData({saving:false})}
  }
})
