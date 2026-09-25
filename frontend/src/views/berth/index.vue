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

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>计划编号</span>
        <input v-model="filters.keyword" placeholder="按计划编号检索" />
      </label>
      <label class="filter-item">
        <span>泊位编号</span>
        <input v-model="filters.berth" placeholder="按泊位编号检索" />
      </label>
      <label class="filter-item">
        <span>占用日期</span>
        <input v-model="filters.date" type="date" />
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
            <button class="link" type="button" @click="openEdit(row)">编辑</button>
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

    <div v-if="editing" class="modal-mask" @click.self="closeEditor">
      <form class="modal" @submit.prevent="submitEditor">
        <h3>{{ editing.id ? '编辑泊位计划' : '登记泊位计划' }}</h3>
        <p v-if="editing.id" class="modal-hint">编排信息保存后会立即同步到列表与编排看板。</p>
        <label v-for="field in formFields" :key="field" class="form-item">
          <span>{{ field }}</span>
          <input
            v-model="editing.values[field]"
            :type="dateFields.includes(field) ? 'datetime-local' : 'text'"
            :required="requiredFields.includes(field)"
            :placeholder="`请输入${field}`"
          />
        </label>
        <p v-if="formError" class="error-text">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeEditor">取消</button>
          <button class="btn primary" type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type FormState = {
  id: number | null
  values: Record<string, string>
}

const ENDPOINT = '/api/berth'
const columns = ["计划编号", "泊位编号", "靠泊船舶", "计划靠泊时间", "计划离泊时间", "船长", "吃水深度", "计划状态"]
const formFields = ["计划编号", "泊位编号", "靠泊船舶", "计划靠泊时间", "计划离泊时间", "船长", "吃水深度"]
const requiredFields = ["计划编号", "泊位编号", "靠泊船舶"]
const dateFields = ["计划靠泊时间", "计划离泊时间"]
const actions = ["确认编排", "确认靠泊", "确认离泊"]
const statuses = ["待编排", "已编排", "已靠泊", "已离泊"]
const stats = [{"label": "今日靠泊计划", "value": 0}, {"label": "待编排计划", "value": 0}, {"label": "在泊船舶数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({ keyword: '', berth: '', date: '' })
const editing = ref<FormState | null>(null)
const formError = ref('')
const saving = ref(false)

function resetFilters() {
  filters.value = { keyword: '', berth: '', date: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function toInputValue(row: Row, field: string): string {
  const raw = String(row[field] ?? '')
  // 后端落库的是 'YYYY-MM-DD HH:MM:SS'，datetime-local 需要 'YYYY-MM-DDTHH:MM'。
  return raw.replace(' ', 'T').slice(0, 16)
}

function toStoredValue(value: string): string {
  // datetime-local 回传带 T，统一成空格分隔，便于按字典序比较区间。
  return value.replace('T', ' ')
}

function openCreate() {
  formError.value = ''
  editing.value = {
    id: null,
    values: Object.fromEntries(formFields.map((field) => [field, ''])),
  }
}

function openEdit(row: Row) {
  formError.value = ''
  editing.value = {
    id: Number(row.id),
    values: Object.fromEntries(formFields.map((field) => [field, toInputValue(row, field)])),
  }
}

function closeEditor() {
  editing.value = null
  formError.value = ''
}

async function submitEditor() {
  if (!editing.value) {
    return
  }
  saving.value = true
  formError.value = ''
  const values = Object.fromEntries(
    formFields.map((field) => [field, toStoredValue(editing.value!.values[field] ?? '').trim()])
  )
  const form = editing.value
  const url = form.id === null ? ENDPOINT : `${ENDPOINT}/${form.id}`
  try {
    const response = await request(url, {
      method: form.id === null ? 'POST' : 'PUT',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      formError.value = payload.message || '泊位计划保存失败，请稍后重试'
      return
    }
    closeEditor()
    // 以服务端落库后的记录为准重新拉取，保证列表/看板与编排结果一致，不靠手动刷新。
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '泊位计划保存失败'
  } finally {
    saving.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      errorMessage.value = payload.message || '泊位计划动作未生效，请稍后重试'
      return
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '泊位计划操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.value.keyword) {
    params.set('keyword', filters.value.keyword)
  }
  if (filters.value.berth) {
    params.set('berth', filters.value.berth)
  }
  if (filters.value.date) {
    params.set('date', filters.value.date)
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
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}

.modal {
  width: 480px;
  max-width: calc(100vw - 32px);
  background: #fff;
  border-radius: 8px;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.modal-hint {
  color: #667085;
  font-size: 12px;
}

.form-item {
  display: flex;
  align-items: center;
  gap: 12px;
}

.form-item span {
  width: 96px;
  flex-shrink: 0;
}

.form-item input {
  flex: 1;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}
</style>
