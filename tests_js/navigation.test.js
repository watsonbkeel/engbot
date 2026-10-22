const test=require('node:test'); const assert=require('node:assert/strict')
test('standalone and merged app choose navigation supported by their actual tabBar',()=>{
  const nav=require('../miniprogram/utils/english-navigation')
  assert.deepEqual(nav.destination('/pages/today/index'),{method:'switchTab',url:'/pages/today/index'})
  const origin={embedded:true,tabPages:['pages/learn/index'],home:'pages/learn/index',isTab:true}
  assert.deepEqual(nav.destination('/pages/today/index',origin),{method:'redirectTo',url:'/pages/today/index'})
  assert.deepEqual(nav.destination('/pages/learn/index',origin),{method:'switchTab',url:'/pages/learn/index'})
})
