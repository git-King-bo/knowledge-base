import test from 'node:test'
import assert from 'node:assert/strict'
import { createApp, effectScope, h, nextTick, ref } from 'vue'
import { createVersionChecker } from '../src/lib/versionCheck'
import { draftKey, writeQuestionDraft, takeQuestionDraft } from '../src/lib/updateDraft'
import { activeTasks, dirtyGuards, updateBusy, canSaveDrafts, saveUpdateDrafts, useFormUpdateGuard, useUpdateGuard } from '../src/lib/updateSafety'
import UpdateNotice from '../src/components/UpdateNotice.vue'
const settle = async () => { for (let i = 0; i < 5; i++) { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() } }

test('version checker ignores offline, HTTP errors, HTML fallbacks and invalid versions; detects rollback as well as upgrades', async () => {
  const versions: string[] = []
  for (const response of [Response.json({version:'old'}),Response.json({version:'new'}),Response.json({version:'current'}),Response.json({version:'x y'}),new Response('<html>'),new Response('',{status:503})]) {
    const checker = createVersionChecker('current', next => versions.push(next), async (_url, init) => { assert.equal(init?.cache,'no-store');return response })
    await checker.check();checker.stop()
  }
  const failed = createVersionChecker('current', next=>versions.push(next), async()=>{throw new Error('offline')})
  await failed.check();failed.stop()
  assert.deepEqual(versions,['old','new',''])
})

test('checks do not overlap and completion after disposal does not notify', async () => {
  let finish!: (r: Response) => void;let calls=0;const versions:string[]=[]
  const checker=createVersionChecker('old',v=>versions.push(v),async()=>{calls++;return new Promise(resolve=>{finish=resolve})})
  const first=checker.check();await checker.check();assert.equal(calls,1)
  checker.stop();finish(Response.json({version:'new'}));await first;assert.deepEqual(versions,[])
})

test('form change tracking resets for each opening, retains sensitive forms only in memory, cleans on disposal', () => {
  const scope=effectScope();const open=ref(false),secret=ref(''),busy=ref(false)
  scope.run(()=>{
    useFormUpdateGuard('model secret',()=>open.value,()=>({secret:secret.value}))
    useUpdateGuard({label:'upload',dirty:()=>false,busy:()=>busy.value})
  })
  open.value=true;assert.equal(dirtyGuards.value.length,0)
  secret.value='sensitive';assert.equal(dirtyGuards.value.length,1);assert.equal(canSaveDrafts.value,false)
  busy.value=true;assert.equal(updateBusy.value,true)
  open.value=false;assert.equal(dirtyGuards.value.length,0)
  open.value=true;assert.equal(dirtyGuards.value.length,0)
  scope.stop();assert.equal(updateBusy.value,false);assert.equal(dirtyGuards.value.length,0)
})

test('drafts isolate user/mode, expire, consume once and fail safely when storage is unavailable', () => {
  const data=new Map<string,string>()
  const storage={getItem:(k:string)=>data.get(k)??null,setItem:(k:string,v:string)=>data.set(k,v),removeItem:(k:string)=>data.delete(k)} as Storage
  const key=draftKey('alice','chat')
  assert.ok(writeQuestionDraft(storage,key,'my question',100))
  assert.equal(takeQuestionDraft(storage,draftKey('bob','chat'),200),undefined)
  assert.equal(takeQuestionDraft(storage,draftKey('alice','retrieval'),200),undefined)
  assert.equal(takeQuestionDraft(storage,key,200),'my question')
  assert.equal(takeQuestionDraft(storage,key,200),undefined)
  writeQuestionDraft(storage,key,'expired',100);assert.equal(takeQuestionDraft(storage,key,100+86400000),undefined)
  assert.equal(writeQuestionDraft({setItem(){throw Error('blocked')}} as unknown as Storage,key,'text'),false)
})

test('failed draft saving prevents success; unsafe operation is globally visible until completion', () => {
  const scope=effectScope();scope.run(()=>useUpdateGuard({label:'question',dirty:()=>true,saveDraft:()=>false}))
  assert.equal(saveUpdateDrafts(),false)
  activeTasks.value++;assert.equal(updateBusy.value,true);activeTasks.value--
  scope.stop()
})

test('update UI warns about dirty form, blocks refresh during upload, can defer, and warns on manual browser unload', async () => {
  const previous=globalThis.fetch
  globalThis.fetch=async()=>Response.json({version:'release-new'})
  Object.defineProperty(document,'hidden',{configurable:true,value:false})
  const busy=ref(true),dirty=ref(true)
  const host=document.createElement('div');document.body.append(host)
  const app=createApp({setup(){useUpdateGuard({label:'knowledge form',dirty:()=>dirty.value,busy:()=>busy.value});return()=>h(UpdateNotice)}})
  try {
    app.mount(host);await settle();assert.match(host.textContent||'',/新版本已发布/)
    const click=(text:string)=>{const button=[...host.querySelectorAll('button')].find(b=>b.textContent===text);assert.ok(button);button.click()}
    click('立即更新');await settle();assert.match(host.textContent||'',/操作正在进行/)
    assert.match(host.textContent||'',/knowledge form/)
    assert.equal([...host.querySelectorAll('button')].find(b=>b.textContent?.includes('放弃'))?.disabled,true)
    const unload=new Event('beforeunload',{cancelable:true});window.dispatchEvent(unload);assert.equal(unload.defaultPrevented,true)
    busy.value=false;await settle();assert.equal([...host.querySelectorAll('button')].find(b=>b.textContent?.includes('放弃'))?.disabled,false)
    click('稍后');await settle();assert.equal(host.querySelector('[aria-label="应用更新"]'),null)
  } finally {app.unmount();host.remove();globalThis.fetch=previous}
})

test('refresh waits for work and dirty content; failed draft writes block reload while successful writes allow it', async () => {
  const previousFetch=globalThis.fetch, previousWindow=globalThis.window
  let reloads=0
  globalThis.window=new Proxy(previousWindow,{get(target,key){
    if(key==='location')return {reload(){reloads++}}
    const value=Reflect.get(target,key,target)
    return typeof value==='function'?value.bind(target):value
  }})
  globalThis.fetch=async()=>Response.json({version:'release-new'})
  Object.defineProperty(document,'hidden',{configurable:true,value:false})
  const busy=ref(true),dirty=ref(true),writable=ref(false)
  const host=document.createElement('div');document.body.append(host)
  const app=createApp({setup(){useUpdateGuard({label:'input',dirty:()=>dirty.value,busy:()=>busy.value,saveDraft:()=>writable.value});return()=>h(UpdateNotice)}})
  const click=(prefix:string)=>{const button=[...host.querySelectorAll('button')].find(b=>b.textContent?.startsWith(prefix));assert.ok(button);button.click()}
  try {
    app.mount(host);await settle();click('立即更新');await settle()
    click('完成后更新');busy.value=false;await settle();assert.equal(reloads,0,'unsaved content must prevent scheduled reload')
    click('保存问答草稿并更新');await settle();assert.equal(reloads,0);assert.match(host.textContent||'',/草稿保存失败/)
    writable.value=true;click('保存问答草稿并更新');await settle();assert.equal(reloads,1)
  } finally {app.unmount();host.remove();globalThis.fetch=previousFetch;globalThis.window=previousWindow}
})
