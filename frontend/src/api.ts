export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const isFile = options.body instanceof FormData
  const response = await fetch('/api' + path, {
    ...options, credentials: 'same-origin',
    headers: { 'X-Workspace-Request': '1', ...(isFile ? {} : { 'Content-Type': 'application/json' }), ...options.headers },
  })
  if (!response.ok) {
    if (response.status === 401 && path !== '/login') window.dispatchEvent(new Event('session-expired'))
    const error = await response.json().catch(() => ({ detail: '请求失败，请检查网络后重试' }))
    throw new Error(typeof error.detail === 'string' ? error.detail : '提交的信息格式不正确')
  }
  return response.json()
}
export const post = (body: unknown = {}) => ({ method: 'POST', body: JSON.stringify(body) })
export const labels: Record<string, string> = {
  civil: '民事争议', labor: '劳动争议', queued: '等待处理', processing: '正在解析', ready: '已就绪',
  needs_vision: '待图片识别', running: '分析中', completed: '草稿已生成', needs_review: '待复核',
  failed: '处理失败', cancelled: '已取消', interrupted: '任务中断',
  intake: '材料与证据', research: '法律研究', draft: '分析与起草', review: '结论复核', done: '草稿完成',
  linked: '已关联原文', unverified: '未关联', supported: '模型认为有支持', contradicted: '与原文矛盾',
  insufficient: '依据不足', fact: '事实', inference: '推论', legal: '法律判断',
}
export const date = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'
