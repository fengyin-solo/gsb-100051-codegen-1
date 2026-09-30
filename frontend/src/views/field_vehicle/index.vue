<template>
  <section class="page" data-module="field_vehicle">
    <header class="page-head">
      <div>
        <h2>外业车辆管理</h2>
        <p class="page-desc">维护外业车辆派车、归队与待检台账；风险格处置为“退回补录”的结论会同步回这里，并带上采集时间与所属业务日。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记车辆</button>
        <button class="btn" type="button" @click="exportRows">导出台账</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="{ 'risk-text': item.risk }">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>车牌/编号</span>
        <input v-model="keyword" placeholder="按车牌或车辆编号检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="status">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>业务日</span>
        <input v-model="bizDate" type="date" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>采集时间</th>
          <th>业务日</th>
          <th>收口处置</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-risk': row.abnormal, 'row-returned': row.returned }">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.collected_at ?? '—' }}</td>
          <td>{{ row.biz_date ?? '—' }}</td>
          <td>
            <span v-if="row.returned" class="badge returned">退回补录</span>
            <span v-else-if="row.settled" class="badge settled">现场已整改</span>
            <span v-else-if="row.abnormal" class="badge risk">风险待处置</span>
            <span v-else-if="row.confirmed" class="badge muted">确认留档</span>
            <span v-else>—</span>
          </td>
          <td class="row-actions">
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
          <td :colspan="columns.length + 4" class="empty-state">暂无外业车辆数据，可先登记车辆</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条外业车辆记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/field_vehicle'
const columns = ['车辆编号', '车牌号', '车辆类型', '责任司机', '所在勘探区', '出车时间', '预计归队', '车辆状态']
const actions = ['派车外业', '归队待检', '确认归队']
const statuses = ['待命', '外业执行中', '归队待检', '已归队', '停用']
const stats = ref([
  { label: '外业执行中', value: 0, risk: false },
  { label: '归队待检', value: 0, risk: false },
  { label: '风险车辆', value: 0, risk: true },
])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const status = ref('')
const bizDate = ref('')

function resetFilters() {
  keyword.value = ''
  status.value = ''
  bizDate.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '车辆登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('外业车辆动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '外业车辆操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value) params.set('keyword', keyword.value)
  if (status.value) params.set('status', status.value)
  if (bizDate.value) params.set('biz_date', bizDate.value)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('车辆台账读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value[0].value = rows.value.filter((r) => r.status === '外业执行中').length
    stats.value[1].value = rows.value.filter((r) => r.status === '归队待检').length
    stats.value[2].value = rows.value.filter((r) => r.abnormal).length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '外业车辆台账读取失败'
  }
}

onMounted(reload)
</script>
