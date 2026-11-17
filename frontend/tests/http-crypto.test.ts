import test from 'node:test'
import assert from 'node:assert/strict'
import { createId } from '../src/lib/id'
import { submitImport } from '../src/lib/api'
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/

test('HTTP crypto without randomUUID still produces distinct UUID v4 identifiers', () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto')!
  const provider = globalThis.crypto
  Object.defineProperty(globalThis, 'crypto', {configurable:true,value:{getRandomValues:provider.getRandomValues.bind(provider)}})
  try {
    assert.equal(typeof globalThis.crypto.randomUUID, 'undefined')
    const ids = Array.from({length:100},createId)
    ids.forEach(id=>assert.match(id,uuid))
    assert.equal(new Set(ids).size,100)
  } finally {Object.defineProperty(globalThis,'crypto',descriptor)}
})

test('native randomUUID is used when available',()=>{assert.match(createId(),uuid)})

test('HTTP upload preserves preview confirmation and multipart import without SubtleCrypto',async()=>{
  const descriptor=Object.getOwnPropertyDescriptor(globalThis,'crypto')!
  const provider=globalThis.crypto,previousFetch=globalThis.fetch
  Object.defineProperty(globalThis,'crypto',{configurable:true,value:{getRandomValues:provider.getRandomValues.bind(provider)}})
  const paths:string[]=[]
  globalThis.fetch=async(input,init)=>{
    paths.push(String(input));assert.ok(init?.body instanceof FormData)
    return String(input).endsWith('/preview')?Response.json({talent_records:0,fields:[],characters:5,duplicate_name_rows:0}):Response.json({reused:false,source_id:'new'})
  }
  try {
    let confirmed=false
    const result=await submitImport('base',new File(['hello'],'sample.txt'),()=>{confirmed=true;return true})
    assert.ok(confirmed);assert.equal(result.source_id,'new')
    assert.deepEqual(paths,['/api/imports/base/preview','/api/imports/base'])
    paths.length=0
    await assert.rejects(submitImport('base',new File(['hello'],'sample.txt'),()=>false),/已取消导入/)
    assert.deepEqual(paths,['/api/imports/base/preview'])
  }finally{globalThis.fetch=previousFetch;Object.defineProperty(globalThis,'crypto',descriptor)}
})
