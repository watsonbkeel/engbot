const navigation = require('../../utils/english-navigation')
const api=require('../../utils/english-api')
const life=require('../../utils/page-state')
const statusPoller=require('../../utils/status-poller')
const {computeRows}=require('../../utils/pi-status')
function modelStatus(llm){
  if(llm.mode!=='custom')return ''
  if(llm.last_status==='fallback')return '最近一次调用已按你的设置回退到老师平台模型。'+(llm.last_error||'')
  if(llm.last_status==='error')return '最近一次模型调用未成功。'+(llm.last_error||'')
  return llm.last_status==='ok'?'最近一次模型测试或调用成功。':''
}
Page({
  data:{connection:{baseUrl:'',studentId:'',token:''},savingConn:false,connMsg:'',
    llm:{mode:'platform'},llmForm:{base_url:'',model:'',api_key:''},thinking:false,allowPlatformFallback:false,modelStatusText:'',llmBusy:false,llmError:'',llmOk:'',rows:null,statusError:false},
  onShow() {
    life.show(this); this.setData(navigation.pageData())
    const c=api.connection();if(!api.isConfigured(c)){statusPoller.stop(this);wx.reLaunch({url:'/pages/onboarding/index'});return}
    this.setData({connection:Object.assign({},c)})
    return Promise.all([statusPoller.start(this),this.loadLlm()])
  },
  onHide() {life.hide(this);statusPoller.stop(this);this.setData({savingConn:false,llmBusy:false,'llmForm.api_key':''})},
  onUnload() {life.hide(this);statusPoller.stop(this)},
  async refreshStatus() {
    const active=life.begin(this,'status')
    try {const rows=computeRows(await api.status());if(!active())return false;this.setData({rows,statusError:false});return true}
    catch(e){if(active())this.setData({rows:null,statusError:true});return false}
  },
  onConnInput(e) {if(this.data.savingConn)return;const f=e.currentTarget.dataset.field;if(['baseUrl','studentId','token'].includes(f))this.setData({['connection.'+f]:e.detail.value.trim()})},
  async onSaveConnection() {
    if(this.data.savingConn)return
    const active=life.begin(this,'connection');const candidate=Object.assign({},this.data.connection)
    this.setData({savingConn:true,connMsg:''})
    try {
      await api.testConnection(candidate);if(!active())return
      api.saveConnection(candidate)
      // A committed classroom starts a new request generation, including busy state.
      // The previous model request must neither lock this classroom nor clear its next save.
      life.show(this)
      this.setData({savingConn:false,connection:candidate,connMsg:'已保存，连接正常',rows:null,statusError:false,llm:{mode:'platform'},llmForm:{base_url:'',model:'',api_key:''},thinking:false,allowPlatformFallback:false,modelStatusText:'',llmBusy:false,llmError:'',llmOk:''})
      statusPoller.start(this);this.loadLlm()
    } catch(e){if(active())this.setData({savingConn:false,connMsg:e.message})}
  },
  async loadLlm() {
    const active=life.begin(this,'llm')
    try {const llm=await api.llm();if(active())this.setData({llm,llmError:'',llmOk:'',llmForm:{base_url:llm.base_url||'',model:llm.model||'',api_key:''},thinking:Boolean(llm.thinking),allowPlatformFallback:llm.allow_platform_fallback===true,modelStatusText:modelStatus(llm)})}
    catch(e){if(active())this.setData({llmError:e.message})}
  },
  onLlmInput(e){if(this.data.llmBusy)return;const f=e.currentTarget.dataset.field;if(['base_url','model','api_key'].includes(f)){life.begin(this,'llm');this.setData({['llmForm.'+f]:e.detail.value.trim()})}},
  onThinking(e){if(this.data.llmBusy)return;life.begin(this,'llm');this.setData({thinking:Boolean(e.detail.value)})},
  onFallback(e){if(this.data.llmBusy)return;life.begin(this,'llm');this.setData({allowPlatformFallback:e.detail.value===true})},
  async onSaveLlm() {
    if(this.data.llmBusy)return
    const f=Object.assign({},this.data.llmForm)
    if(!f.base_url||!f.model){this.setData({llmError:'请填写接口地址和模型名；仅更换 Key 时才需要填写新 Key'});return}
    const active=life.begin(this,'llm');this.setData({llmBusy:true,llmError:'',llmOk:''})
    try {
      const llm=await api.saveLlm({base_url:f.base_url,model:f.model,api_key:f.api_key||null,thinking:this.data.thinking,allow_platform_fallback:this.data.allowPlatformFallback});if(!active())return
      this.setData({llm,llmForm:{base_url:llm.base_url||f.base_url,model:llm.model||f.model,api_key:''},thinking:Boolean(llm.thinking),allowPlatformFallback:llm.allow_platform_fallback===true,modelStatusText:modelStatus(llm),llmOk:'测试通过，已改用自己的模型'})
    } catch(e){if(active())this.setData({llmError:e.message})}
    finally{if(active())this.setData({llmBusy:false})}
  },
  async onClearLlm() {
    if(this.data.llmBusy)return
    const active=life.begin(this,'llm');this.setData({llmBusy:true,llmError:'',llmOk:''})
    try{const llm=await api.clearLlm();if(active())this.setData({llm,llmForm:{base_url:'',model:'',api_key:''},thinking:false,allowPlatformFallback:false,modelStatusText:'',llmOk:'已删除保存的 Key 并改用平台模型，请确认老师已配置可用模型'})}
    catch(e){if(active())this.setData({llmError:e.message})}
    finally{if(active())this.setData({llmBusy:false})}
  },
  onReonboard() {
    const active=life.begin(this,'modal')
    wx.showModal({title:'重新打开引导',content:'重新验证课堂连接和大模型；验证失败会保留原有连接。',success:r=>{if(r.confirm&&active())wx.reLaunch({url:'/pages/onboarding/index'})}})
  }
})
