import test from 'node:test'
import assert from 'node:assert/strict'
import { createApp, h, nextTick } from 'vue'
import ProviderSettings from '../src/views/ProviderSettings.vue'
const settle = async () => { for (let i=0;i<5;i++) { await new Promise(resolve=>setTimeout(resolve,0)); await nextTick() } }
test('thinking controls save false, true and null without sending a key', async () => {
  const previous=globalThis.fetch
  const bodies: Record<string,unknown>[]=[]
  let refreshes=0
  const provider={id:'qwen',name:'千问',provider:'openai-compatible',baseUrl:'https://example.com/v1',apiKeyHint:'已填写',defaultModel:'qwen3.7-plus',isDefault:true,enableThinking:null}
  globalThis.fetch=async (_url,init)=>{const body=JSON.parse(String(init?.body)); bodies.push(body); return Response.json({id:'qwen',name:'千问',provider:provider.provider,base_url:provider.baseUrl,default_model:provider.defaultModel,api_key_hint:'已填写',is_default:true,enable_thinking:body.enable_thinking})}
  const host=document.createElement('div');document.body.append(host)
  const app=createApp({render:()=>h(ProviderSettings,{providers:[provider],refresh:async()=>{refreshes++}})})
  try {
    app.mount(host)
    const buttons=host.querySelectorAll<HTMLButtonElement>('.thinking-choices button')
    assert.equal(buttons[0]!.getAttribute('aria-pressed'),'true')
    for(const index of [2,1,0]) { buttons[index]!.click(); await settle() }
    assert.deepEqual(bodies.map(b=>b.enable_thinking),[false,true,null])
    assert.equal(refreshes,3)
    assert.ok(bodies.every(b=>!('api_key' in b)))
  } finally { app.unmount();host.remove();globalThis.fetch=previous }
})
