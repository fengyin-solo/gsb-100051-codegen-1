<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>今日收口泳道</h2>
        <p class="page-desc">
          横向收口钻孔、岩心、地层、外业车辆四条泳道；从风险格退回补录时，处置结论同步到对应模块台账、待办清单和本看板。
          跨日资料按原始采集时间归属业务日，既有确认成果按原口径留档。
        </p>
      </div>
      <div class="page-actions closing-tools">
        <label class="tool-item">
          <span>业务日</span>
          <input type="date" v-model="businessDay" @change="reload" />
        </label>
        <label class="tool-item">
          <span>收口账号</span>
          <select v-model="operator" @change="syncOperator">
            <option v-for="name in operators" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <button class="btn" type="button" @click="reload">刷新看板</button>
        <button
          class="btn primary"
          type="button"
          :disabled="board?.frozen || closing"
          :title="board?.frozen ? '该业务日已收口，汇总缓存已冻结' : ''"
          @click="closeBatch"
        >
          {{ closing ? '提交中…' : '批次收口' }}
        </button>
      </div>
    </header>

    <div v-if="board" class="batch-banner" :class="board.frozen ? 'frozen' : 'open'">
      <template v-if="board.frozen">
        <strong>{{ businessDay }} 已收口</strong>
        <span>由 {{ board.closed_by }} 于 {{ formatTime(board.closed_at) }} 完成收口，汇总缓存已冻结；未办补录仍可跟进。</span>
      </template>
      <template v-else>
        <strong>{{ businessDay }} 收口中</strong>
        <span>待办 {{ board.totals.pending }} · 风险 {{ board.totals.risk }}
          · 已退回 {{ board.totals.send_back }} · 跨日资料 {{ board.totals.late }}（看板版本 {{ board.version }}）</span>
      </template>
    </div>
    <div v-if="notice" class="batch-banner conflict">
      <span>{{ notice }}</span>
      <button class="link" type="button" @click="reload">刷新看板后重试</button>
    </div>

    <div v-if="board" class="lane-row">
      <article v-for="lane in board.lanes" :key="lane.module" class="lane-card">
        <header class="lane-head">
          <h3>{{ lane.name }}</h3>
          <RouterLink class="link" :to="ledgerPath(lane.module)">模块台账 →</RouterLink>
        </header>
        <div class="lane-cells">
          <button
            class="lane-cell"
            :class="{ active: focus?.module === lane.module && focus?.kind === 'pending' }"
            type="button"
            @click="focus = { module: lane.module, kind: 'pending' }"
          >
            <span class="cell-label">待办</span>
            <strong>{{ lane.pending_count }}</strong>
          </button>
          <button
            class="lane-cell risk"
            :class="{ active: focus?.module === lane.module && focus?.kind === 'risk' }"
            type="button"
            @click="focus = { module: lane.module, kind: 'risk' }"
          >
            <span class="cell-label">风险</span>
            <strong>{{ lane.risk_count }}</strong>
            <em v-if="lane.send_back_count" class="cell-tag">退回 {{ lane.send_back_count }}</em>
          </button>
          <div class="lane-cell static" title="采集与入库不在同一业务日，按原始采集时间归属">
            <span class="cell-label">跨日资料</span>
            <strong>{{ lane.late_count }}</strong>
          </div>
        </div>
        <ul class="lane-codes">
          <li
            v-for="item in lane.risk_items"
            :key="String(item.entry_id)"
            class="risk-code"
            :class="{ closed: item.disposition === '现场核实闭环' }"
          >
            <button class="link" type="button" @click="focus = { module: lane.module, kind: 'risk' }">
              {{ item.code }}
            </button>
            <span v-if="item.disposition" class="inline-tag">{{ item.disposition }}</span>
          </li>
        </ul>
      </article>
    </div>

    <div v-if="board" class="closing-grid">
      <section class="closing-panel">
        <h3>{{ focusTitle }}</h3>
        <p v-if="!focusItems.length" class="empty-state">该格暂无记录</p>
        <ul v-else class="risk-list">
          <li v-for="item in focusItems" :key="`${item.module}-${item.entry_id}`" class="risk-item">
            <div class="risk-main">
              <div class="risk-line">
                <strong>{{ item.code }}</strong>
                <span class="muted">{{ item.lane }} · 当前状态 {{ item.status }}</span>
                <span v-if="item.late" class="badge warn">跨日</span>
                <span v-if="item.disposition" class="badge" :class="item.disposition === '退回补录' ? 'send-back' : 'closed'">
                  {{ item.disposition }}
                </span>
              </div>
              <div class="risk-time muted">
                采集 {{ formatTime(item.collected_at) }} ｜ 入库 {{ formatTime(item.received_at) }}
                <template v-if="!item.late">（同一业务日）</template>
              </div>
              <div v-if="item.disposition_note" class="risk-note">处置说明：{{ item.disposition_note }}</div>
            </div>
            <div v-if="item.kind === 'risk'" class="risk-ops">
              <textarea
                v-model="notes[riskKey(item)]"
                class="note-input"
                rows="2"
                placeholder="补录/核实说明（选填），结论会写回模块台账"
              ></textarea>
              <div class="op-row">
                <button
                  class="btn"
                  type="button"
                  :disabled="board.frozen || busyKey === riskKey(item)"
                  @click="dispose(item, '退回补录')"
                >
                  退回补录
                </button>
                <button
                  class="btn primary"
                  type="button"
                  :disabled="board.frozen || busyKey === riskKey(item)"
                  @click="dispose(item, '现场核实闭环')"
                >
                  现场核实闭环
                </button>
              </div>
            </div>
          </li>
        </ul>
      </section>

      <section class="closing-panel">
        <h3>退回补录待办</h3>
        <p v-if="!board.todos.length" class="empty-state">暂无退回补录待办</p>
        <ul v-else class="todo-list">
          <li v-for="todo in board.todos" :key="String(todo.id)" class="todo-item">
            <div>
              <strong>{{ todo.title }}</strong>
              <div class="muted">
                {{ todo.lane }} · {{ todo.operator }} 于 {{ formatTime(todo.created_at) }} 发起
              </div>
              <div v-if="todo.note" class="risk-note">{{ todo.note }}</div>
            </div>
            <button
              class="btn"
              type="button"
              :disabled="busyTodo === todo.id"
              @click="finishTodo(todo)"
            >
              {{ busyTodo === todo.id ? '提交中…' : '完成补录' }}
            </button>
          </li>
        </ul>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type RiskItem = {
  module: string
  lane: string
  entry_id: number
  code: string
  status: string
  collected_at: string
  received_at: string
  business_day: string
  late: boolean
  disposition: string | null
  disposition_note: string | null
  disposition_operator: string | null
  disposition_at: string | null
  kind?: 'risk' | 'pending'
}

type Todo = {
  id: number
  business_day: string
  module: string
  lane: string
  entry_id: number
  code: string
  title: string
  note: string | null
  operator: string
  created_at: string
  done: boolean
}

type Lane = {
  module: string
  name: string
  pending_count: number
  risk_count: number
  send_back_count: number
  late_count: number
  risk_items: RiskItem[]
  pending_items: RiskItem[]
}

type Board = {
  business_day: string
  batch_status: string
  version: number
  frozen: boolean
  closed_at?: string
  closed_by?: string
  lanes: Lane[]
  todos: Todo[]
  totals: { pending: number; risk: number; send_back: number; late: number }
}

const session = useSessionStore()
const operators = ['值班管理员甲', '值班管理员乙']

function today() {
  return new Date().toISOString().slice(0, 10)
}

const businessDay = ref(today())
const operator = ref(session.operator)
const board = ref<Board | null>(null)
const focus = ref<{ module: string; kind: 'risk' | 'pending' } | null>(
  { module: 'borehole', kind: 'risk' },
)
const notes = ref<Record<string, string>>({})
const notice = ref('')
const busyKey = ref('')
const busyTodo = ref(0)
const closing = ref(false)

const LEDGER_PATHS: Record<string, string> = {
  borehole: '/borehole',
  core: '/core',
  stratigraphy: '/stratigraphy',
  vehicle: '/vehicle',
}

function ledgerPath(module: string) {
  return LEDGER_PATHS[module] ?? '/'
}

function syncOperator() {
  session.setOperator(operator.value)
}

function riskKey(item: RiskItem) {
  return `${item.module}:${item.entry_id}`
}

function formatTime(value?: string | null) {
  if (!value) return '—'
  return value.replace('T', ' ')
}

const focusLane = computed<Lane | null>(() => {
  if (!board.value || !focus.value) return null
  return board.value.lanes.find((lane) => lane.module === focus.value?.module) ?? null
})

const focusTitle = computed(() => {
  if (!focusLane.value || !focus.value) return '泳道明细'
  return focus.value.kind === 'risk'
    ? `${focusLane.value.name} · 风险格（${focusLane.value.risk_count}）`
    : `${focusLane.value.name} · 待办格（${focusLane.value.pending_count}）`
})

const focusItems = computed<RiskItem[]>(() => {
  if (!focusLane.value || !focus.value) return []
  const items = focus.value.kind === 'risk'
    ? focusLane.value.risk_items
    : focusLane.value.pending_items
  return items.map((item) => ({ ...item, kind: focus.value!.kind }))
})

async function reload() {
  notice.value = ''
  try {
    const response = await request(`/api/closing/board?business_day=${businessDay.value}`)
    if (!response.ok) throw new Error('收口看板读取失败')
    board.value = (await response.json()) as Board
    if (!focus.value) focus.value = { module: 'borehole', kind: 'risk' }
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '收口看板读取失败'
  }
}

function newRequestId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

async function dispose(item: RiskItem, conclusion: string) {
  if (!board.value) return
  notice.value = ''
  busyKey.value = riskKey(item)
  try {
    const response = await request('/api/closing/dispositions', {
      method: 'POST',
      body: JSON.stringify({
        business_day: businessDay.value,
        module: item.module,
        entry_id: item.entry_id,
        conclusion,
        note: notes.value[riskKey(item)] || null,
        operator: operator.value,
        request_id: newRequestId(),
        // 带上看板版本：两个账号同时处置时，后发起者只会看到冲突提示
        version: board.value.version,
      }),
    })
    if (response.status === 409) {
      const detail = await response.json().catch(() => ({ detail: '数据已被其他账号更新' }))
      notice.value = detail.detail ?? '泳道数据已被其他账号更新'
      await reload()
      return
    }
    if (!response.ok) {
      const detail = await response.json().catch(() => null)
      throw new Error(detail?.detail ?? '处置结论未生效，请稍后重试')
    }
    board.value = (await response.json()) as Board
    if (conclusion === '退回补录') notes.value[riskKey(item)] = ''
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '处置结论提交失败'
  } finally {
    busyKey.value = ''
  }
}

async function finishTodo(todo: Todo) {
  notice.value = ''
  busyTodo.value = todo.id
  try {
    const response = await request(`/api/closing/todos/${todo.id}/complete`, {
      method: 'POST',
      body: JSON.stringify({ operator: operator.value, request_id: newRequestId() }),
    })
    if (response.status === 409) {
      const detail = await response.json().catch(() => ({ detail: '该待办状态已变化' }))
      notice.value = detail.detail ?? '该待办已被其他账号处理'
      await reload()
      return
    }
    if (!response.ok) throw new Error('待办完成状态未生效，请稍后重试')
    await reload()
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '待办完成提交失败'
  } finally {
    busyTodo.value = 0
  }
}

async function closeBatch() {
  if (!board.value) return
  notice.value = ''
  if (board.value.totals.risk > 0) {
    notice.value = `仍有 ${board.value.totals.risk} 条风险未闭环，无法收口`
    return
  }
  closing.value = true
  try {
    const response = await request(`/api/closing/batch/${businessDay.value}/close`, {
      method: 'POST',
      body: JSON.stringify({
        operator: operator.value,
        request_id: newRequestId(),
        version: board.value.version,
      }),
    })
    if (response.status === 409) {
      const detail = await response.json().catch(() => ({ detail: '收口状态已变化' }))
      notice.value = detail.detail ?? '其他账号已先完成收口'
      await reload()
      return
    }
    if (!response.ok) {
      const detail = await response.json().catch(() => null)
      throw new Error(detail?.detail ?? '批次收口未成功，请稍后重试')
    }
    board.value = (await response.json()) as Board
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '批次收口失败'
  } finally {
    closing.value = false
  }
}

onMounted(() => {
  if (!operators.includes(session.operator)) session.setOperator(operators[0])
  operator.value = session.operator
  void reload()
})
</script>
