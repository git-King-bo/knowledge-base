<script setup lang="ts">
import { ref,onMounted,onBeforeUnmount } from 'vue'
import { request } from '../lib/api'
import { currentUser } from '../lib/auth'
type Job={id:string;source_id:string;status:string;stage:string;completed:number;total:number;attempts:number;error:string|null}
const jobs=ref<Job[]>([]),error=ref('');let timer:ReturnType<typeof setInterval>|undefined
const labels:Record<string,string>={queued:'排队中',running:'处理中',done:'完成',failed:'失败',cancelled:'已取消',parsing:'解析与入库',embedding:'生成向量',complete:'完成'}
async function load(){try{jobs.value=await request('/jobs');error.value=''}catch(e){error.value=String(e)}}
async function action(j:Job,a:string){try{await request(`/jobs/${j.id}/${a}`,{method:'POST'});await load()}catch(e){error.value=String(e)}}
onMounted(()=>{void load();timer=setInterval(load,3000)});onBeforeUnmount(()=>clearInterval(timer))
</script>
<template><section class="panel jobs-panel"><p>任务保存在服务器，关闭页面后仍会继续处理。失败任务重试时复用已完成的向量批次。</p><p v-if="error" class="notice error">{{error}}</p><p v-if="!jobs.length">暂无导入任务。</p><article v-for="j in jobs" :key="j.id"><div><strong>{{labels[j.status]||j.status}}</strong> · {{labels[j.stage]||j.stage}}<small>{{j.source_id}} · 尝试 {{j.attempts}} 次</small><progress v-if="j.total" :value="j.completed" :max="j.total"/><span v-if="j.total"> {{j.completed}} / {{j.total}}</span><p v-if="j.error" class="notice error">{{j.error}}</p></div><div v-if="currentUser?.role!=='viewer'"><button v-if="['failed','cancelled'].includes(j.status)" @click="action(j,'retry')">重试</button><button v-if="['queued','running'].includes(j.status)" @click="action(j,'cancel')">取消</button></div></article></section></template>
<style scoped>.jobs-panel{padding:24px}article{display:flex;justify-content:space-between;gap:16px;padding:20px 0;border-bottom:1px solid #eee}small{display:block;color:#777;margin:8px 0}progress{width:260px}</style>
