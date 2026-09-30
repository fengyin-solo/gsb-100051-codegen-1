<template>
  <section class="page" data-module="close-board">
    <header class="page-head">
      <div>
        <h2>今日收口泳道</h2>
        <p class="page-desc">
          按业务日 {{ board?.biz_date ?? '—' }} 横向汇总钻孔、岩心、地层、外业车辆的待办与风险；
          跨日资料按原始采集时间归属，既有确认成果按原口径留档。
        </p>
      </div>
      <div class="page-actions board-toolbar">
        <label class="operator-switch">
          <span>收口账号</span>
          <select :value="store.operator" @change="onSwitchOperator(($event.target as HTMLSelectElement).value)">
            <option v-for="op in OPERATORS" :key="op" :value="op">{{ op }}</option>
          </select>
        </label>
        <button class="btn" type="button" :disabled="loading" @click="loadBoard">刷新看板</button>
        <button
          class="btn primary"
          type="button"
          :disabled="loading || isClosed"
          :title="isClosed ? '该业务日已收口' : '提交今日收口'"
          @click="onCloseBatch"
        >
          提交收口
        </button>
      </div>
    </header>

    <div class="batch-bar" :class="{ closed: isClosed }">
      <div class="batch-state">
        <span class="batch-dot" />
        <span>批次状态：<strong>{{ batchStatusText }}</strong></span>
        <span class="batch-meta">版本 v{{ board?.batch.version ?? 0 }}</span>
        <span v-if="board?.batch.closed_by" class="batch-meta">
          收口人：{{ board.batch.closed_by }} · {{ board.batch.closed_at }}
        </span>
      </div>
      <div v-if="notice" class="batch-notice" :class="noticeKind">{{ notice }}</div>
    </div>

    <!-- 横向泳道：四条泳道，每格显示待办/风险数量 -->
    <div class="swimlanes">
      <article
        v-for="lane in board?.lanes ?? []"
        :key="lane.module"
        class="lane"
        :class="{ active: activeLane === lane.module }"
        @click="activeLane = lane.module"
      >
        <header class="lane-head">
          <span class="lane-title">{{ lane.title }}</span>
          <span class="lane-total">在收口 {{ lane.total }}</span>
        </header>
        <div class="lane-cells">
          <button
            type="button"
            class="lane-cell pending"
            :class="{ active: cellFilter(lane.module, 'pending') }"
            @click.stop="toggleCell(lane.module, 'pending')"
          >
            <span class="cell-label">待办</span>
            <strong class="cell-value">{{ lane.pending }}</strong>
          </button>
          <button
            type="button"
            class="lane-cell risk"
            :class="{ active: cellFilter(lane.module, 'risk'), zero: lane.risk === 0 }"
            @click.stop="toggleCell(lane.module, 'risk')"
          >
            <span class="cell-label">风险</span>
            <strong class="cell-value">{{ lane.risk }}</strong>
          </button>
        </div>
        <p class="lane-hint">点击数字格可在下方筛选{{ lane.title }}明细</p>
      </article>
    </div>

    <div class="stat-row board-totals">
      <article class="stat-card"><span class="stat-label">待办合计</span><strong class="stat-value">{{ board?.totals.pending ?? 0 }}</strong></article>
      <article class="stat-card"><span class="stat-label">风险合计</span><strong class="stat-value risk-text">{{ board?.totals.risk ?? 0 }}</strong></article>
      <article class="stat-card"><span class="stat-label">退回补录中</span><strong class="stat-value">{{ board?.totals.returned ?? 0 }}</strong></article>
      <article class="stat-card"><span class="stat-label">在收口资料</span><strong class="stat-value">{{ board?.totals.total ?? 0 }}</strong></article>
    </div>

    <div class="detail-grid">
      <!-- 待办清单 -->
      <section class="detail-col">
        <h3>待办清单 <em>{{ filteredPending.length }}</em></h3>
        <ul class="item-list">
          <li v-for="item in filteredPending" :key="`${item.module}-${item.id}`" class="item">
            <span class="item-tag">{{ item.lane }}</span>
            <div class="item-body">
              <strong>{{ item.code }}</strong>
              <p>{{ item.detail || item.status }}</p>
              <small>采集 {{ item.collected_at }} 归属 {{ item.biz_date }}</small>
            </div>
            <span v-if="item.returned" class="badge returned">退回补录</span>
          </li>
          <li v-if="!filteredPending.length" class="empty-inline">暂无待办</li>
        </ul>
      </section>

      <!-- 风险格：点击进入退回补录/现场整改 -->
      <section class="detail-col">
        <h3>风险格 <em>{{ filteredRisks.length }}</em></h3>
        <ul class="item-list">
          <li v-for="item in filteredRisks" :key="`${item.module}-${item.id}`" class="item risk-item">
            <span class="item-tag risk">{{ item.lane }}</span>
            <div class="item-body">
              <strong>{{ item.code }}</strong>
              <p>{{ item.detail || item.status }}</p>
              <small>采集 {{ item.collected_at }} 归属 {{ item.biz_date }}</small>
            </div>
            <div class="item-ops">
              <button class="link" type="button" @click="openDisposition(item)">退回补录</button>
            </div>
          </li>
          <li v-if="!filteredRisks.length" class="empty-inline">风险已清零，可提交收口</li>
        </ul>
      </section>
    </div>

    <!-- 风险处置弹层 -->
    <div v-if="disposeTarget" class="modal-mask" @click.self="closeDisposition">
      <div class="modal">
        <h3>风险处置 · {{ disposeTarget.lane }} {{ disposeTarget.code }}</h3>
        <p class="modal-desc">{{ disposeTarget.detail || disposeTarget.status }}（采集 {{ disposeTarget.collected_at }}）</p>
        <label class="form-row">
          <span>处置结论</span>
          <div class="conclusion-switch">
            <button
              type="button"
              class="btn"
              :class="{ primary: form.conclusion === '退回补录' }"
              @click="form.conclusion = '退回补录'"
            >退回补录</button>
            <button
              type="button"
              class="btn"
              :class="{ primary: form.conclusion === '现场整改' }"
              @click="form.conclusion = '现场整改'"
            >现场整改</button>
          </div>
        </label>
        <label class="form-row">
          <span>处置说明（写入台账留痕）</span>
          <textarea v-model="form.reason" rows="3" :placeholder="form.conclusion === '退回补录' ? '如：采取率低于规程，退回重新采样补录' : '如：定位设备重启后恢复正常'"></textarea>
        </label>
        <p class="form-hint">
          {{ form.conclusion === '退回补录'
            ? '退回后将同步：模块台账标记待补录、待办清单新增该记录、概览计数 -1 风险 +1 待办。'
            : '现场整改到位：风险清除，不进入待办，概览风险计数 -1。' }}
        </p>
        <footer class="modal-foot">
          <span v-if="disposeError" class="error-text">{{ disposeError }}</span>
          <button class="btn ghost" type="button" @click="closeDisposition">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitDisposition">
            {{ submitting ? '提交中…' : '确认处置' }}
          </button>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { ApiConflictError, ApiError, fetchJson, newRequestId, postJson } from '@/api/client'
import { OPERATORS, useSessionStore, type Operator } from '@/stores/session'

type CardItem = {
  module: string
  lane: string
  id: number
  code: string
  status: string
  detail: string
  collected_at: string
  biz_date: string
  returned: boolean
}

type Board = {
  biz_date: string
  lanes: { module: string; title: string; pending: number; risk: number; total: number }[]
  totals: { pending: number; risk: number; returned: number; total: number }
  pending_items: CardItem[]
  risk_items: CardItem[]
  batch: { biz_date: string; status: string; version: number; closed_by: string | null; closed_at: string | null }
  generated_at: string
}

const store = useSessionStore()
const board = ref<Board | null>(null)
const loading = ref(false)
const notice = ref('')
const noticeKind = ref<'ok' | 'err'>('ok')

// 点击数字格后的明细筛选：null 表示该泳道不过滤
const activeLane = ref<string | null>(null)
const cellSelection = reactive<Record<string, 'pending' | 'risk'>>({})

const isClosed = computed(() => board.value?.batch.status === '已收口')
const batchStatusText = computed(() => {
  if (!board.value) return '加载中'
  return board.value.batch.status === '已收口' ? '已收口（已锁定）' : '收口中'
})

const filteredPending = computed<CardItem[]>(() => {
  if (!board.value) return []
  const lane = activeLane.value
  const kind = lane ? cellSelection[lane] : undefined
  return board.value.pending_items.filter((it) => {
    if (lane && it.module !== lane) return false
    if (lane && kind === 'risk') return false
    return true
  })
})

const filteredRisks = computed<CardItem[]>(() => {
  if (!board.value) return []
  const lane = activeLane.value
  const kind = lane ? cellSelection[lane] : undefined
  return board.value.risk_items.filter((it) => {
    if (lane && it.module !== lane) return false
    if (lane && kind === 'pending') return false
    return true
  })
})

function cellFilter(module: string, kind: 'pending' | 'risk') {
  return activeLane.value === module && cellSelection[module] === kind
}

function toggleCell(module: string, kind: 'pending' | 'risk') {
  if (cellFilter(module, kind)) {
    activeLane.value = null
    delete cellSelection[module]
    return
  }
  activeLane.value = module
  cellSelection[module] = kind
}

function flash(message: string, kind: 'ok' | 'err' = 'ok') {
  notice.value = message
  noticeKind.value = kind
}

async function loadBoard() {
  loading.value = true
  try {
    board.value = await fetchJson<Board>('/api/close/board')
  } catch (error) {
    flash(error instanceof ApiError ? error.message : '看板加载失败', 'err')
  } finally {
    loading.value = false
  }
}

function onSwitchOperator(value: string) {
  store.setOperator(value as Operator)
  flash(`已切换为收口账号：${value}，请基于最新看板操作`, 'ok')
}

// ---------------- 风险处置 ----------------
const disposeTarget = ref<CardItem | null>(null)
const submitting = ref(false)
const disposeError = ref('')
const form = reactive({ conclusion: '退回补录' as '退回补录' | '现场整改', reason: '' })

function openDisposition(item: CardItem) {
  disposeTarget.value = item
  disposeError.value = ''
  form.conclusion = '退回补录'
  form.reason = ''
}

function closeDisposition() {
  disposeTarget.value = null
}

async function submitDisposition() {
  const target = disposeTarget.value
  const version = board.value?.batch.version
  if (!target || version === undefined) return
  submitting.value = true
  disposeError.value = ''
  try {
    const result = await postJson<{ message: string }>(
      `/api/close/lanes/${target.module}/risks/${target.id}/dispose`,
      {
        conclusion: form.conclusion,
        reason: form.reason,
        operator: store.operator,
        request_id: newRequestId(),
        expected_version: version,
      },
    )
    await loadBoard()
    flash(result.message, 'ok')
    closeDisposition()
  } catch (error) {
    if (error instanceof ApiConflictError) {
      disposeError.value = `冲突：${error.message}。已为你刷新看板，请重新进入风险格处理（不会重复计数）`
      await loadBoard()
    } else {
      disposeError.value = error instanceof ApiError ? error.message : '处置失败'
    }
  } finally {
    submitting.value = false
  }
}

// ---------------- 业务日收口 ----------------
async function onCloseBatch() {
  const version = board.value?.batch.version
  if (version === undefined) return
  try {
    const result = await postJson<{ ok: boolean; message: string; blocked?: boolean }>(
      '/api/close/batch',
      { operator: store.operator, request_id: newRequestId(), expected_version: version, force: false },
    )
    // 仍有未清风险时后端拦截（不推进版本、不计数），提示先处置风险。
    await loadBoard()
    flash(result.message, result.blocked ? 'err' : 'ok')
  } catch (error) {
    if (error instanceof ApiConflictError) {
      // 后发起者只能看到冲突提示；刷新后可见已收口状态，同号重试也不会重复计数。
      flash(`收口冲突：${error.message}`, 'err')
      await loadBoard()
    } else {
      flash(error instanceof ApiError ? error.message : '收口失败', 'err')
    }
  }
}

onMounted(loadBoard)
</script>
