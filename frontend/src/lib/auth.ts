import { ref } from 'vue'
import { request } from './api'
export interface User { id: string; username: string; role: 'admin' | 'editor' | 'viewer'; enabled: boolean }
export const currentUser = ref<User>()
export async function restoreLogin() { try { currentUser.value = await request<User>('/auth/me') } catch { currentUser.value = undefined } }
export async function logout() { await request('/auth/logout', { method: 'POST' }); currentUser.value = undefined; window.location.reload() }

if (typeof window !== 'undefined') window.addEventListener('kb-session-expired', () => { currentUser.value = undefined })
