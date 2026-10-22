const api=require('../../utils/english-api')
const life=require('../../utils/page-state')
const navigation=require('../../utils/english-navigation')
const flow=require('./scene-flow')
const COPY='请把下面的场景写成给儿童英语陪练机器人的 JSON，字段：name（场景名，1–40字）、robot_role（机器人角色，1–40字）、student_role（孩子角色，1–40字）、goal（孩子要完成的小步骤，中文不超过180字）、opening（孩子的英文开场白，不超过60字）。适合15岁以下，不要血腥、伤亡、武器细节，不要索要个人信息。只输出 JSON。'
const EMPTY={name:'',robot_role:'',student_role:'',goal:'',opening:''}
const LIMITS={name:40,robot_role:40,student_role:40,goal:200,opening:60}
const FIELDS=[{key:'name',label:'场景名',limit:40},{key:'robot_role',label:'机器人扮演',limit:40},{key:'student_role',label:'我扮演',limit:40},{key:'opening',label:'我先说的英文',limit:60}]
function form(scene){const out={};Object.keys(EMPTY).forEach(k=>{out[k]=scene&&typeof scene[k]==='string'?scene[k]:''});return out}
Page({
  data:{loading:false,saving:false,busy:false,error:'',notice:'',usage:null,usageError:'',templates:[],examples:[],activeTemplate:'',current:null,form:Object.assign({},EMPTY),fields:FIELDS,description:'',grade:1,gradeReady:false,copyText:COPY,showForm:true},
  onLoad(options={}){
    const draft=flow.takeEditorDraft()
    const grade=Number(options.grade===undefined&&draft?draft.grade:options.grade)
    if(Number.isInteger(grade)&&grade>=1&&grade<=12){this._draftGrade={grade,identity:api.connectionIdentity()};this.setData({grade,gradeReady:true})}
    if(draft){this._dirty=Boolean(draft.dirty);this._identity=api.connectionIdentity();this.setData({description:draft.description||'',form:form(draft.form),activeTemplate:draft.activeTemplate||'',showForm:true})}
  },
  onShow(){life.show(this);this.setData({usage:null,usageError:''});this.refreshUsage();return this.load()},
  onHide(){life.hide(this);this.setData({loading:false,saving:false,busy:false})},
  onUnload(){life.hide(this)},
  async refreshUsage(){
    const active=life.begin(this,'usage')
    try{
      const usage=await api.sceneUsage()
      if(!usage||!['attempts','successes','limit','remaining'].every(k=>Number.isInteger(usage[k])&&usage[k]>=0))throw new Error('场景请求次数暂时无法读取')
      if(active())this.setData({usage,usageError:''})
    }catch(e){if(active())this.setData({usage:null,usageError:e.message})}
  },
  async load(){
    const active=life.begin(this,'load');const sceneActive=life.begin(this,'sceneRead');const identity=api.connectionIdentity()
    const draftGrade=this._draftGrade&&this._draftGrade.identity===identity?this._draftGrade.grade:null
    this.setData({loading:true,error:'',notice:'',gradeReady:draftGrade!==null})
    try{
      const results=await Promise.all([api.config(),api.sceneTemplates().then(value=>({value})).catch(error=>({error}))]);if(!active())return
      const cfg=results[0],tpl=results[1],scene=cfg.scene||null
      const patch={grade:draftGrade===null?cfg.grade:draftGrade,gradeReady:true,showForm:true}
      // Templates may finish after a save. Only the untouched scene read may replace saved content.
      if(sceneActive()){
        patch.current=scene
        if(!this._dirty||this._identity!==identity){patch.form=form(scene);this._dirty=false}
      }
      this._identity=identity
      if(tpl.error){patch.error='模板加载失败，可手动填写。'+tpl.error.message;patch.templates=[];patch.examples=[]}
      else{patch.templates=tpl.value.templates||[];patch.examples=tpl.value.examples||[];patch.copyText=tpl.value.copy_for_parent||COPY}
      this.setData(patch)
    }catch(e){if(active())this.setData({error:e.message})}
    finally{if(active())this.setData({loading:false})}
  },
  onTemplate(e){if(this.data.saving)return;const t=this.data.templates[Number(e.currentTarget.dataset.index)];if(t){life.begin(this,'generate');this._dirty=true;this._identity=api.connectionIdentity();this.setData({activeTemplate:t.key||t.name,showForm:true,form:form(t),busy:false})}},
  onExample(e){if(this.data.saving)return;life.begin(this,'generate');const x=this.data.examples[Number(e.currentTarget.dataset.index)];if(x)this.setData({description:x,busy:false})},
  onDescInput(e){life.begin(this,'generate');this.setData({description:e.detail.value,busy:false})},
  onField(e){if(this.data.saving)return;const f=e.currentTarget.dataset.field;if(Object.prototype.hasOwnProperty.call(EMPTY,f)){life.begin(this,'generate');this._dirty=true;this._identity=api.connectionIdentity();this.setData({['form.'+f]:e.detail.value,busy:false})}},
  toggleForm(){this.setData({showForm:!this.data.showForm})},
  async onGenerate(){
    if(this.data.busy||this.data.saving||!this.data.gradeReady)return
    const description=this.data.description.trim()
    if(description.length<5||description.length>200){this.setData({error:'描述需要5–200字：在哪、机器人是谁、我是谁、我想做什么'});return}
    const active=life.begin(this,'generate');const samePage=life.guard(this);this.setData({busy:true,error:'',notice:''})
    try{
      const response=await api.sceneGenerate(description,this.data.grade,true)
      if(active()){
        const headers={};Object.keys(response.headers).forEach(k=>{headers[k.toLowerCase()]=response.headers[k]})
        const routed=headers['x-model-fallback']==='true'?'本次已按你的设置回退到老师平台模型。':headers['x-model-provider']==='student'?'本次使用自己的模型生成。':headers['x-model-provider']==='platform'?'本次使用老师平台模型生成。':''
        this._dirty=true;this._identity=api.connectionIdentity();this.setData({form:form(response.data),showForm:true,activeTemplate:'',notice:routed+'已生成，请检查内容后保存。'})
      }
    }
    catch(e){if(active())this.setData({error:'生成失败，可手工填写。'+e.message})}
    finally{if(active())this.setData({busy:false});if(samePage())this.refreshUsage()}
  },
  onCopyPrompt(){
    const active=life.begin(this,'clipboard');const description=this.data.description.trim()
    const grade=this.data.gradeReady?'\n\n我的年级：'+this.data.grade+' 年级。':''
    const prompt=this.data.gradeReady?this.data.copyText.replace(/当前\s*年级/g,this.data.grade+' 年级'):this.data.copyText
    wx.setClipboardData({data:prompt+grade+(description?'\n\n场景描述：'+description:''),success:()=>{if(active())wx.showToast({title:'提示词已复制',icon:'none'})}})
  },
  goModelSettings(){
    if(this.data.saving||this.data.busy)return
    flow.keepEditorDraft({description:this.data.description,form:this.data.form,activeTemplate:this.data.activeTemplate,grade:this.data.gradeReady?this.data.grade:null,dirty:this._dirty})
    navigation.open('/pages/settings/index')
  },
  goToday(active){
    const fallback=()=>{if(active())navigation.open('/pages/today/index')}
    const pages=typeof getCurrentPages==='function'?getCurrentPages():[]
    const previous=pages.length>1?pages[pages.length-2]:null
    if(previous&&previous.route&&previous.route.replace(/^\//,'')==='pages/today/index'&&typeof wx.navigateBack==='function'){
      wx.navigateBack({delta:1,fail:fallback})
    }else fallback()
  },
  onSave(){return this.saveScene(false)},
  onSaveAndArrange(){return this.saveScene(true)},
  async saveScene(arrange){
    if(this.data.saving)return
    const value=form(this.data.form)
    for(const key of Object.keys(LIMITS)){value[key]=value[key].trim();if(!value[key]||value[key].length>LIMITS[key]){this.setData({error:`${key} 需要1–${LIMITS[key]}个字符`});return}}
    if(/[\u4e00-\u9fff]/.test(value.opening)){this.setData({error:'开场白请填写英文'});return}
    life.begin(this,'generate');life.begin(this,'sceneRead');const active=life.begin(this,'save');this.setData({busy:false,saving:true,error:'',notice:''})
    try{
      const cfg=await api.config();if(!active())return
      const saved=await api.saveConfig(Object.assign({},cfg,{scene:value}));if(!active())return
      const current=saved.scene||value
      this._dirty=false
      this.setData({current,form:form(current),notice:arrange?'场景已保存，去今日练习确认安排。':'场景已保存。要直接练角色对话，请点「保存并去安排练习」；完整练习会先练词汇，再使用这个场景。'})
      wx.showToast({title:'场景已保存',icon:'none'})
      if(arrange){flow.selectForPractice(current);this.goToday(active)}
      else flow.clearPracticeSelection()
    }
    catch(e){if(active())this.setData({error:e.message})}
    finally{if(active())this.setData({saving:false})}
  },
  async onClear(){
    if(this.data.saving)return
    const active=life.begin(this,'save');const go=await new Promise(resolve=>wx.showModal({title:'清除场景',content:'清除后，场景模式将使用普通单词对话。',success:r=>resolve(!!r.confirm),fail:()=>resolve(false)}))
    if(!go||!active())return
    life.begin(this,'sceneRead')
    this.setData({saving:true,error:'',notice:''})
    try{const cfg=await api.config();if(!active())return;await api.saveConfig(Object.assign({},cfg,{scene:null}));if(active()){flow.clearPracticeSelection();this._dirty=false;this.setData({current:null,form:Object.assign({},EMPTY),activeTemplate:'',showForm:true,notice:'场景已清除'});wx.showToast({title:'已清除',icon:'none'})}}
    catch(e){if(active())this.setData({error:e.message})}
    finally{if(active())this.setData({saving:false})}
  }
})
