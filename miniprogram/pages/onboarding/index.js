const navigation = require('../../utils/english-navigation')
const api=require('../../utils/english-api')
const life=require('../../utils/page-state')
Page({
  data:{step:1,connection:{baseUrl:'',studentId:'',token:''},busy:false,error:'',llmForm:{base_url:'',model:'',api_key:''},thinking:false,llmBusy:false,llmError:'',llmOk:''},
  onLoad(){this.setData({connection:Object.assign({},api.connection())})},
  onShow(){life.show(this)},
  onHide(){life.hide(this);this.setData({busy:false,llmBusy:false,'llmForm.api_key':''})},
  onUnload(){life.hide(this)},
  onConnInput(e){if(this.data.busy)return;const f=e.currentTarget.dataset.field;if(['baseUrl','studentId','token'].includes(f))this.setData({['connection.'+f]:e.detail.value.trim()})},
  async onTestConnection(){
    if(this.data.busy)return
    const active=life.begin(this,'connection');const candidate=Object.assign({},this.data.connection)
    this.setData({busy:true,error:''})
    try{await api.testConnection(candidate);if(!active())return;api.saveConnection(candidate);this.setData({step:2,busy:false})}
    catch(e){if(active())this.setData({error:e.message,busy:false})}
  },
  onLlmInput(e){if(this.data.llmBusy)return;const f=e.currentTarget.dataset.field;if(['base_url','model','api_key'].includes(f))this.setData({['llmForm.'+f]:e.detail.value.trim()})},
  onThinking(e){if(this.data.llmBusy)return;this.setData({thinking:Boolean(e.detail.value)})},
  async onSaveLlm(){
    if(this.data.llmBusy)return
    const f=Object.assign({},this.data.llmForm)
    if(!f.base_url||!f.model||!f.api_key){this.setData({llmError:'请填写接口地址、模型名和 API Key'});return}
    const active=life.begin(this,'llm');this.setData({llmBusy:true,llmError:''})
    try{await api.saveLlm({base_url:f.base_url,model:f.model,api_key:f.api_key,thinking:this.data.thinking});if(active())this.setData({llmBusy:false,llmOk:'自己的大模型测试通过',step:3,'llmForm.api_key':''})}
    catch(e){if(active())this.setData({llmError:e.message,llmBusy:false})}
  },
  async onSkipLlm(){
    if(this.data.llmBusy)return
    const active=life.begin(this,'llm');this.setData({llmBusy:true,llmError:''})
    try{await api.clearLlm();if(active())this.setData({step:3,llmOk:'已选择平台模型；请确认老师已配置可用的模型服务','llmForm.api_key':''})}
    catch(e){if(active())this.setData({llmError:e.message})}
    finally{if(active())this.setData({llmBusy:false})}
  },
  onFinish(){navigation.open('/pages/today/index')}
})
