/** 统一请求封装：拼后端地址、抛网络错误、给页脚留一句可读的说明。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiConflictError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ApiConflictError'
  }
}

export class ApiError extends Error {
  detail: unknown

  constructor(message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.detail = detail
  }
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new ApiError(`接口请求失败：${detail}`)
  })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new ApiError(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}

/** 提交类请求：把后端 409 收敛成 ApiConflictError，其余非 2xx 抛 ApiError。 */
export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
  const data = response.status === 204 ? null : await response.json().catch(() => null)
  if (response.status === 409) {
    const detail = (data as { detail?: string } | null)?.detail ?? '数据已被他人更新，请刷新后重试'
    throw new ApiConflictError(detail)
  }
  if (!response.ok) {
    const detail = (data as { detail?: string } | null)?.detail ?? `接口返回 ${response.status}`
    throw new ApiError(detail)
  }
  return data as T
}

/** 生成幂等号：同一动作重复提交/重试时后端据此回放，不重复计数。 */
export function newRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}
