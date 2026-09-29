import test from 'node:test'
import assert from 'node:assert/strict'
import { createApp, h, nextTick } from 'vue'
import LoginPanel from '../src/components/LoginPanel.vue'
import TalentWorkspace from '../src/views/TalentWorkspace.vue'
import { currentUser } from '../src/lib/auth'
import { submitImport } from '../src/lib/api'
const settle=async()=>{for(let i=0;i<4;i++){await new Promise(r=>setTimeout(r,0));await nextTick()}}

test('login sets authenticated user and sends CSRF request header',async()=>{
 const previous=globalThis.fetch;let headers:Headers|undefined
 globalThis.fetch=async (_input,init)=>{headers=new Headers(init?.headers);return Response.json({id:'u',username:'admin',role:'admin',enabled:true})}
 const host=document.createElement('div');document.body.append(host);const app=createApp(LoginPanel)
 try{app.mount(host);const inputs=host.querySelectorAll('input');inputs[1]!.value='test-password';inputs[1]!.dispatchEvent(new Event('input',{bubbles:true}));host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await settle();assert.equal(currentUser.value?.id,'u');assert.equal(headers?.get('X-Requested-With'),'knowledge-base')}
 finally{app.unmount();host.remove();globalThis.fetch=previous;currentUser.value=undefined}
})

test('hash hit reuses file without multipart upload',async()=>{
 const previous=globalThis.fetch;const paths:string[]=[]
 globalThis.fetch=async(input,init)=>{paths.push(String(input));assert.equal(init?.method,'POST');const data=JSON.parse(String(init?.body));assert.match(data.sha256,/^[a-f0-9]{64}$/);return Response.json({reused:true,source_id:'existing'})}
 try{const file=new File(['same file'],'sample.txt');const result=await submitImport('base',file);assert.equal(result.reused,true);assert.deepEqual(paths,['/api/imports/base/reuse'])}
 finally{globalThis.fetch=previous}
})

test('talent list uses structured records and supports named filters',async()=>{
 const previous=globalThis.fetch;const urls:URL[]=[]
 globalThis.fetch=async input=>{urls.push(new URL(String(input),'http://localhost'));return Response.json({total:1,items:[{id:'t',name:'测试人才',organization:'测试机构',position:'工程师',domain:'AI',location:'北京'}]})}
 const host=document.createElement('div');document.body.append(host);const app=createApp({render:()=>h(TalentWorkspace,{bases:[]})})
 try{app.mount(host);await settle();assert.match(host.textContent||'',/测试人才/);const org=host.querySelector<HTMLInputElement>('input[aria-label="机构"]')!;org.value='测试机构';org.dispatchEvent(new Event('input',{bubbles:true}));host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await settle();assert.equal(urls.at(-1)?.searchParams.get('organization'),'测试机构')}
 finally{app.unmount();host.remove();globalThis.fetch=previous}
})
