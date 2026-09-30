import { defineStore } from 'pinia'

// 收口演示用到两个值班账号：可在看板顶部切换，模拟两个账号同时提交。
export const OPERATORS = ['值班管理员', '收口复核员'] as const
export type Operator = (typeof OPERATORS)[number]

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员' as Operator,
    shiftLabel: '白班 08:00-20:00',
    scope: '地质勘探数据管理平台',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setOperator(operator: Operator) {
      this.operator = operator
    },
  },
})
