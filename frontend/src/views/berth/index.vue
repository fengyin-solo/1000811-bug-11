<template>
  <section class="page" data-module="berth">
    <header class="page-head">
      <div>
        <h2>泊位计划管理</h2>
        <p class="page-desc">维护泊位计划，围绕计划编号、泊位编号、靠泊船舶、计划靠泊时间做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记泊位计划</button>
        <button class="btn" type="button" @click="exportRows">导出泊位计划清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="board">
      <h3 class="board-title">编排看板</h3>
      <p class="board-desc">与下方计划列表读取同一份数据，保存或筛选后一起刷新。</p>
      <div v-for="group in boardGroups" :key="group.berth" class="board-row">
        <span class="board-berth">{{ group.berth }}</span>
        <div class="board-plans">
          <span
            v-for="item in group.plans"
            :key="String(item.plan.id)"
            class="board-chip"
            :class="{ conflict: item.conflict }"
          >
            {{ item.plan['靠泊船舶'] }} · {{ item.plan['计划靠泊时间'] }} → {{ item.plan['计划离泊时间'] }} · {{ item.plan['计划状态'] }}
            <em v-if="item.conflict" class="conflict-tag">时间重叠</em>
          </span>
        </div>
      </div>
      <p v-if="!boardGroups.length" class="empty-state">当前筛选条件下暂无编排数据</p>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>计划编号</span>
        <input v-model="filters['计划编号']" placeholder="按计划编号检索" />
      </label>
      <label class="filter-item">
        <span>泊位编号</span>
        <input v-model="filters['泊位编号']" placeholder="按泊位编号检索" />
      </label>
      <label class="filter-item">
        <span>靠泊船舶</span>
        <input v-model="filters['靠泊船舶']" placeholder="按靠泊船舶检索" />
      </label>
      <label class="filter-item">
        <span>计划靠泊时间</span>
        <input v-model="filters['计划靠泊时间']" type="date" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openEdit(row)">编排</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无泊位计划数据，可先登记泊位计划</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条泊位计划记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="dialog.visible" class="modal-mask" @click.self="closeDialog">
      <form class="modal" @submit.prevent="saveDialog">
        <h3>{{ dialog.mode === 'create' ? '登记泊位计划' : `编排泊位计划 ${dialog.form['计划编号']}` }}</h3>
        <label v-for="field in dialogFields" :key="field.key" class="modal-field">
          <span>{{ field.label }}</span>
          <input
            v-model="dialog.form[field.key]"
            :type="field.type"
            :disabled="dialog.mode === 'edit' && field.key === '计划编号'"
          />
        </label>
        <p v-if="dialog.error" class="error-text">{{ dialog.error }}</p>
        <div class="modal-actions">
          <button class="btn primary" type="submit" :disabled="dialog.saving">{{ dialog.saving ? '保存中…' : '保存' }}</button>
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/berth'
const columns = ["计划编号", "泊位编号", "靠泊船舶", "计划靠泊时间", "计划离泊时间", "船长", "吃水深度", "计划状态"]
const actions = ["确认编排", "确认靠泊", "确认离泊"]
const dialogFields = [
  { key: '计划编号', label: '计划编号', type: 'text' },
  { key: '泊位编号', label: '泊位编号', type: 'text' },
  { key: '靠泊船舶', label: '靠泊船舶', type: 'text' },
  { key: '计划靠泊时间', label: '计划靠泊时间', type: 'datetime-local' },
  { key: '计划离泊时间', label: '计划离泊时间', type: 'datetime-local' },
  { key: '船长', label: '船长', type: 'text' },
  { key: '吃水深度', label: '吃水深度', type: 'text' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const emptyFilters = (): Record<string, string> => ({
  '计划编号': '',
  '泊位编号': '',
  '靠泊船舶': '',
  '计划靠泊时间': '',
})
const filters = ref<Record<string, string>>(emptyFilters())
const dialog = ref<{
  visible: boolean
  saving: boolean
  mode: 'create' | 'edit'
  id: number | null
  form: Record<string, string>
  error: string
}>({ visible: false, saving: false, mode: 'create', id: null, form: {}, error: '' })

const stats = computed(() => {
  const now = new Date()
  const todayText = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  return [
    { label: '今日靠泊计划', value: rows.value.filter((row) => String(row['计划靠泊时间'] ?? '').startsWith(todayText)).length },
    { label: '待编排计划', value: rows.value.filter((row) => row['status'] === '待编排').length },
    { label: '在泊船舶数', value: rows.value.filter((row) => row['status'] === '已靠泊').length },
  ]
})

function parseTime(value: unknown): number {
  const time = new Date(String(value ?? '').replace(' ', 'T')).getTime()
  return Number.isNaN(time) ? 0 : time
}

function windowsOverlap(a: Row, b: Row): boolean {
  if (a['status'] === '已离泊' || b['status'] === '已离泊') {
    return false
  }
  const startA = parseTime(a['计划靠泊时间'])
  const endA = parseTime(a['计划离泊时间'])
  const startB = parseTime(b['计划靠泊时间'])
  const endB = parseTime(b['计划离泊时间'])
  if (!startA || !endA || !startB || !endB) {
    return false
  }
  return startA < endB && startB < endA
}

const boardGroups = computed(() => {
  const groups = new Map<string, Row[]>()
  for (const row of rows.value) {
    const berth = String(row['泊位编号'] ?? '') || '未指定泊位'
    const list = groups.get(berth) ?? []
    list.push(row)
    groups.set(berth, list)
  }
  return [...groups.entries()].map(([berth, plans]) => {
    const sorted = [...plans].sort(
      (a, b) => parseTime(a['计划靠泊时间']) - parseTime(b['计划靠泊时间']),
    )
    return {
      berth,
      plans: sorted.map((plan, index) => ({
        plan,
        conflict: sorted.some((other, otherIndex) => otherIndex !== index && windowsOverlap(plan, other)),
      })),
    }
  })
})

function resetFilters() {
  filters.value = emptyFilters()
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function toInputTime(value: unknown): string {
  return String(value ?? '').replace(' ', 'T').slice(0, 16)
}

function openCreate() {
  const form: Record<string, string> = {}
  for (const field of dialogFields) {
    form[field.key] = ''
  }
  dialog.value = { visible: true, saving: false, mode: 'create', id: null, form, error: '' }
}

function openEdit(row: Row) {
  const form: Record<string, string> = {}
  for (const field of dialogFields) {
    const value = row[field.key]
    form[field.key] = field.type === 'datetime-local' ? toInputTime(value) : String(value ?? '')
  }
  dialog.value = { visible: true, saving: false, mode: 'edit', id: Number(row.id), form, error: '' }
}

function closeDialog() {
  dialog.value = { ...dialog.value, visible: false, saving: false, error: '' }
}

async function saveDialog() {
  const { mode, id, form } = dialog.value
  const isCreate = mode === 'create'
  dialog.value = { ...dialog.value, error: '', saving: true }
  try {
    const response = await request(isCreate ? ENDPOINT : `${ENDPOINT}/${id}`, {
      method: isCreate ? 'POST' : 'PUT',
      body: JSON.stringify({ values: form }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      dialog.value = {
        ...dialog.value,
        saving: false,
        error: payload.message ?? payload.detail ?? '泊位计划保存失败',
      }
      return
    }
    closeDialog()
    await reload()
  } catch (error) {
    dialog.value = {
      ...dialog.value,
      saving: false,
      error: error instanceof Error ? error.message : '泊位计划保存失败',
    }
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '泊位计划动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '泊位计划操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.value['计划编号']) {
    params.set('keyword', filters.value['计划编号'])
  }
  if (filters.value['泊位编号']) {
    params.set('berth', filters.value['泊位编号'])
  }
  if (filters.value['靠泊船舶']) {
    params.set('vessel', filters.value['靠泊船舶'])
  }
  if (filters.value['计划靠泊时间']) {
    params.set('date', filters.value['计划靠泊时间'])
  }
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('泊位计划列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '泊位计划列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.board {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.board-title { margin: 0 0 4px; font-size: 14px; }
.board-desc { margin: 0 0 8px; font-size: 12px; color: var(--muted); }
.board-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 6px 0;
  border-top: 1px dashed var(--border);
}
.board-row:first-of-type { border-top: none; }
.board-berth { min-width: 72px; font-weight: 600; font-size: 13px; padding-top: 4px; }
.board-plans { display: flex; flex-wrap: wrap; gap: 6px; }
.board-chip {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 12px;
  background: #f8fafc;
}
.board-chip.conflict { border-color: #b42318; color: #b42318; background: #fef3f2; }
.conflict-tag { font-style: normal; margin-left: 4px; font-weight: 600; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10;
}
.modal {
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  width: 360px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.modal h3 { margin: 0; font-size: 15px; }
.modal-field span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 2px; }
.modal-field input { width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; }
.modal-field input:disabled { background: #f1f5f9; color: var(--muted); }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
