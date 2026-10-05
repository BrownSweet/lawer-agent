<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Scale, Plus, FolderOpen, Settings, ArrowUpRight, ArrowRight, UploadCloud, FileText,
  Search, Layers, ShieldCheck, ChevronRight, X, LogOut, Download, RefreshCw, CircleHelp, BookOpen, Clock3,
  Check, AlertCircle, Calculator, PanelLeftClose } from 'lucide-vue-next'
import { api, post, labels, date } from './api'
import SettingsView from './SettingsView.vue'

const authenticated = ref(false), initializing = ref(true), password = ref('')
const username = ref(''), accountName = ref('')
const cases = ref<any[]>([]), current = ref<any>(null), run = ref<any>(null)
const config = ref<any>(null), view = ref('workspace'), tab = ref('materials')
const busy = ref(''), error = ref(''), toast = ref(''), search = ref(''), mobileNav = ref(false)
const newCase = ref(false), sourceModal = ref(false), feeModal = ref(false)
const caseForm = ref({ title: '', category: 'civil', description: '' })
const sourceForm = ref({ title: '', content: '', version: '', url: '', effective_date: '' })
const question = ref(''), mode = ref('analysis'), selected = ref<string[]>([]), selectedSources = ref<string[]>([])
const sourceURL = ref(''), sourceMode = ref('paste'), amount = ref(''), fee = ref<any>(null)
const evidence = ref<any>(null), previewPages = ref<any[]>([]), previewMaterial = ref<any>(null)
const events = ref<any[]>([]), fileInput = ref<HTMLInputElement | null>(null)
let stream: EventSource | null = null, poll: ReturnType<typeof setInterval> | null = null
let detailGeneration = 0, runGeneration = 0
let previousFocus: HTMLElement | null = null
const modalOpen = computed(() => !!(newCase.value || sourceModal.value || feeModal.value || evidence.value))
watch(modalOpen, async opened => {
  if (opened) {
    previousFocus = document.activeElement as HTMLElement
    await nextTick()
    document.querySelector<HTMLElement>('.modal input, .modal button')?.focus()
  } else previousFocus?.focus()
})
function modalKeyboard(event: KeyboardEvent) {
  if (!modalOpen.value) return
  if (event.key === 'Escape') {
    evidence.value = null; feeModal.value = false; sourceModal.value = false; newCase.value = false
  }
  if (event.key === 'Tab') {
    const elements = [...document.querySelectorAll<HTMLElement>('.modal button:not(:disabled), .modal input, .modal select, .modal textarea, .modal a[href]')].filter(e => e.getClientRects().length)
    const first = elements[0], last = elements.at(-1)
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
}
const filteredCases = computed(() => cases.value.filter(c => c.title.toLowerCase().includes(search.value.toLowerCase())))
const active = computed(() => run.value && ['queued', 'running'].includes(run.value.status))
const modelReady = computed(() => config.value?.providers[config.value.provider]?.has_key && config.value?.providers[config.value.provider]?.model)
const roles = [
  { key: 'intake', name: '案件与证据', detail: '事实 · 时间线 · 材料缺口' },
  { key: 'research', name: '法律研究', detail: '法规 · 类案 · 适用范围' },
  { key: 'draft', name: '策略与起草', detail: '争议分析 · 文书草稿' },
  { key: 'review', name: '结论复核', detail: '原文支持 · 矛盾 · 引用' },
]
const safeURL = (url: string) => /^https?:\/\//i.test(url || '') ? url : undefined
async function loadConfig() { config.value = await api('/settings') }
async function refreshCases() { cases.value = await api('/cases') }
async function login() {
  busy.value = 'login'; error.value = ''
  try { const session = await api('/login', post({ username: username.value.trim(), password: password.value })); accountName.value = session.username; password.value = ''; authenticated.value = true; await initialize() }
  catch (e: any) { error.value = e.message } finally { busy.value = '' }
}
async function initialize() {
  await Promise.all([refreshCases(), loadConfig()])
  if (cases.value.length) await chooseCase(cases.value[0].id)
}
function expire() { ++detailGeneration; ++runGeneration; authenticated.value = false; stream?.close(); current.value = null; run.value = null; newCase.value = false; sourceModal.value = false; feeModal.value = false; evidence.value = null }
async function logout() { await api('/logout', post()); expire() }
onMounted(async () => {
  window.addEventListener('session-expired', expire)
  window.addEventListener('keydown', modalKeyboard)
  try { const session = await api('/session'); accountName.value = session.username; authenticated.value = true; await initialize() }
  catch { authenticated.value = false }
  finally { initializing.value = false }
  poll = setInterval(async () => {
    if (!authenticated.value || !current.value) return
    if (current.value.materials.some((m: any) => ['queued', 'processing'].includes(m.status))) {
      try { await refreshDetail() } catch { /* Explicit actions display request errors. */ }
    }
  }, 2500)
})
onUnmounted(() => { stream?.close(); if (poll) clearInterval(poll); window.removeEventListener('session-expired', expire); window.removeEventListener('keydown', modalKeyboard) })
async function refreshDetail() {
  if (!current.value) return
  const identity = current.value.id
  const data = await api('/cases/' + identity)
  if (current.value?.id === identity) current.value = data
}
async function chooseCase(id: string) {
  const generation = ++detailGeneration
  ++runGeneration
  error.value = ''; mobileNav.value = false; view.value = 'workspace'; stream?.close(); events.value = []
  run.value = null
  try {
    const data = await api('/cases/' + id)
    if (generation !== detailGeneration) return
    current.value = data
    selected.value = data.materials.map((m: any) => m.id)
    selectedSources.value = data.sources.map((s: any) => s.id)
    question.value = data.description || ''; tab.value = 'materials'
    if (data.runs.length) await chooseRun(data.runs[0].id)
  } catch (e: any) { error.value = e.message }
}
async function createCase() {
  busy.value = 'case'; error.value = ''
  try {
    const row = await api('/cases', post(caseForm.value)); newCase.value = false
    caseForm.value = { title: '', category: 'civil', description: '' }
    await refreshCases(); await chooseCase(row.id)
  } catch (e: any) { error.value = e.message } finally { busy.value = '' }
}
async function uploadFiles(files: FileList | File[] | null) {
  if (!files?.length || !current.value) return
  busy.value = 'upload'; error.value = ''
  const identity = current.value.id
  try {
    for (const file of Array.from(files)) {
      const form = new FormData(); form.append('file', file)
      const m = await api(`/cases/${identity}/materials`, { method: 'POST', body: form })
      if (current.value?.id === identity) selected.value.push(m.id)
    }
    await refreshDetail(); await refreshCases(); toast.value = '上传完成，后台正在解析素材'
  } catch (e: any) { error.value = e.message; await refreshDetail() }
  finally { busy.value = ''; if (fileInput.value) fileInput.value.value = '' }
}
function onDrop(event: DragEvent) { event.preventDefault(); if (!busy.value && !active.value) void uploadFiles(event.dataTransfer?.files || null) }
async function reparse(id: string, vision = false) {
  busy.value = id; error.value = ''
  try { await api(`/materials/${id}/reparse?vision=${vision}`, post()); await refreshDetail() }
  catch (e: any) { error.value = e.message } finally { busy.value = '' }
}
async function preview(material: any) {
  error.value = ''
  try {
    previewPages.value = await api(`/materials/${material.id}/pages`); previewMaterial.value = material
    if (previewPages.value.length) setPreviewPage(previewPages.value[0])
    else evidence.value = { name: material.name, text: '尚未完成解析，请稍后刷新。', material_id: material.id }
  } catch (e: any) { error.value = e.message }
}
function setPreviewPage(page: any) {
  evidence.value = { name: previewMaterial.value.name, text: page.text, page: page.number,
    material_id: previewMaterial.value.id, warning: page.warning, has_image: !!page.image_key }
}
function showEvidence(ref: string) {
  previewPages.value = []; previewMaterial.value = null
  evidence.value = run.value?.result?.evidence[ref] || { name: '引用不可用', text: '此引用未在本次来源中找到。' }
}
async function previewSource(id: string) {
  try { const row = await api('/sources/' + id); previewPages.value = []; evidence.value = { ...row, name: row.title, text: row.content } }
  catch (e: any) { error.value = e.message }
}
async function addSource() {
  busy.value = 'source'; error.value = ''
  try {
    const row = sourceMode.value === 'url'
      ? await api(`/cases/${current.value.id}/sources/fetch`, post({ url: sourceURL.value }))
      : await api(`/cases/${current.value.id}/sources`, post(sourceForm.value))
    selectedSources.value.push(row.id); sourceModal.value = false
    sourceForm.value = { title: '', content: '', version: '', url: '', effective_date: '' }
    sourceURL.value = ''; await refreshDetail()
  } catch (e: any) { error.value = e.message } finally { busy.value = '' }
}
async function startRun() {
  busy.value = 'run'; error.value = ''; toast.value = ''
  try {
    const result = await api(`/cases/${current.value.id}/runs`, post({ question: question.value, mode: mode.value,
      material_ids: selected.value, source_ids: selectedSources.value }))
    tab.value = 'analysis'; await refreshDetail(); await chooseRun(result.id)
  } catch (e: any) { error.value = e.message } finally { busy.value = '' }
}
async function chooseRun(id: string) {
  const generation = ++runGeneration
  stream?.close(); events.value = []
  let row
  try { row = await api('/runs/' + id) }
  catch (e: any) { if (generation === runGeneration) error.value = e.message; return }
  if (generation !== runGeneration || current.value?.id !== row.case_id) return
  run.value = row
  const currentStream = new EventSource(`/api/runs/${id}/events`)
  stream = currentStream
  currentStream.addEventListener('progress', async e => {
    if (generation !== runGeneration) return
    const data = JSON.parse((e as MessageEvent).data)
    if (!events.value.some(x => x.id === data.id)) events.value.push(data)
    try { const latest = await api('/runs/' + id); if (run.value?.id === id) run.value = latest }
    catch { currentStream.close() }
  })
  currentStream.addEventListener('finished', async () => {
    currentStream.close()
    if (generation !== runGeneration) return
    try { const latest = await api('/runs/' + id); if (run.value?.id === id) run.value = latest; await refreshDetail() }
    catch (e: any) { error.value = e.message }
  })
  currentStream.onerror = () => { /* EventSource reconnects and supplies Last-Event-ID. */ }
}
async function cancel() {
  try { await api(`/runs/${run.value.id}/cancel`, post()); toast.value = '已请求取消；当前模型调用结束后停止' }
  catch (e: any) { error.value = e.message }
}
async function calculate() {
  try { fee.value = await api('/fees?amount=' + encodeURIComponent(amount.value)) }
  catch (e: any) { error.value = e.message }
}
</script>

<template>
  <div v-if="initializing" class="boot">正在连接律序工作台…</div>
  <main v-else-if="!authenticated" class="login-page">
    <div class="login-story"><div class="brand"><span class="brand-mark"><Scale :size="23" /></span><b>律序</b><span>LEGAL WORKSPACE</span></div><div><p class="eyebrow">EVERY ARGUMENT, GROUNDED.</p><h1>让每一个判断，<br>都有据可循。</h1><p>从纷繁材料到清晰脉络。<br>一个连接事实、法律研究与文书草稿的工作台。</p><div class="story-line"></div><span class="small">材料整理 / 法律研究 / 多角色复核</span></div><span class="small">以证据为起点，以审慎为尺度。</span></div>
    <section class="login-form"><div class="mini-label">YOUR PRIVATE WORKSPACE</div><h2>回到你的工作台</h2><p class="muted">使用你的账号和密码登录，继续处理案件材料。</p><form @submit.prevent="login"><label>账号<input v-model="username" name="username" autocomplete="username" required autofocus maxlength="64" placeholder="请输入账号"></label><label>密码<input v-model="password" name="password" type="password" autocomplete="current-password" required placeholder="请输入密码"></label><p v-if="error" class="alert error" role="alert">{{ error }}</p><button class="primary full" :disabled="!!busy">{{ busy ? '正在登录…' : '进入工作台' }}<ArrowRight :size="17" /></button></form><p class="hint">请使用管理员提供的账号和密码。</p><div class="login-foot"><ShieldCheck :size="17" />私有工作空间 · 文件与来源可追溯</div></section>
  </main>
  <div v-else class="app-shell">
    <aside class="sidebar" :class="{ open: mobileNav }">
      <a class="brand" href="#" @click.prevent="view = 'workspace'"><span class="brand-mark"><Scale :size="23" /></span><b>律序</b><span>法律工作台</span></a>
      <button class="new-case" @click="newCase = true"><Plus :size="18" />新建案件</button>
      <div class="nav-label">工作空间 <span>{{ cases.length }}</span></div>
      <div class="sidebar-search"><Search :size="15" /><input v-model="search" aria-label="搜索案件" placeholder="搜索案件"></div>
      <nav class="case-nav" aria-label="案件列表"><button v-for="c in filteredCases" :key="c.id" :class="{ selected: current?.id === c.id && view === 'workspace' }" @click="chooseCase(c.id)"><FolderOpen :size="17" /><span>{{ c.title }}<small>{{ labels[c.category] }} · {{ c.material_count }} 份素材</small></span><ChevronRight :size="14" /></button><p v-if="!filteredCases.length" class="hint">{{ search ? '没有匹配的案件' : '新建第一个案件，开始整理材料。' }}</p></nav>
      <div class="sidebar-bottom"><div class="private-note"><ShieldCheck :size="17" /><div>{{ accountName }}<small>已登录 · 案件工作空间</small></div></div><button :class="{ selected: view === 'settings' }" @click="view = 'settings'; mobileNav = false"><Settings :size="17" />工作台设置</button><button @click="logout"><LogOut :size="17" />退出登录</button></div>
    </aside>
    <div v-if="mobileNav" class="nav-overlay" @click="mobileNav = false"></div>
    <div class="main-shell">
      <header class="topbar"><div><button class="icon-button mobile-only" aria-label="打开导航" @click="mobileNav = !mobileNav"><PanelLeftClose :size="19" /></button><span class="muted">工作空间</span><ChevronRight :size="14" /><span>{{ view === 'settings' ? '设置' : current?.title || '案件工作台' }}</span></div><span class="connection"><i :class="{ ready: modelReady }"></i>{{ modelReady ? '模型已配置' : '待配置模型' }}</span></header>
      <div class="content">
        <div v-if="error" class="alert error" role="alert"><AlertCircle :size="17" />{{ error }}<button class="icon-button" aria-label="关闭错误" @click="error = ''"><X :size="16" /></button></div>
        <div v-if="toast" class="alert success" role="status"><Check :size="17" />{{ toast }}<button class="icon-button" aria-label="关闭提示" @click="toast = ''"><X :size="16" /></button></div>
        <SettingsView v-if="view === 'settings'" @saved="loadConfig" />
        <template v-else-if="!current">
          <section class="welcome"><p class="eyebrow">A CLEARER WAY TO WORK</p><h1>从一份材料，<br>开始理清案件。</h1><p class="muted">将合同、聊天截图、PDF 与相关依据放在一起，<br>让事实、争议和下一步逐渐清晰。</p><button class="primary" @click="newCase = true"><Plus :size="18" />建立第一个案件</button><div class="welcome-cards"><div><FileText /><h3>整理材料</h3><p>上传原件，按页提取与引用。</p></div><div><BookOpen /><h3>建立依据</h3><p>保留来源、原文与版本。</p></div><div><ShieldCheck /><h3>复核判断</h3><p>区分事实、推论与未核验项。</p></div></div></section>
        </template>
        <template v-else>
          <div class="page-heading"><div><p class="eyebrow">CASE WORKSPACE <span class="dot-divider">/</span> {{ labels[current.category] }}</p><h1>{{ current.title }}</h1><p class="muted small">创建于 {{ date(current.created_at) }}<span class="dot-divider">·</span>每条分析保留材料与来源记录</p></div><button @click="feeModal = true"><Calculator :size="16" />诉讼费估算</button></div>
          <div class="stat-row"><div><span class="stat-icon"><FileText :size="19" /></span><span><strong>{{ current.materials.length }}</strong><small>案件素材</small></span></div><div><span class="stat-icon"><BookOpen :size="19" /></span><span><strong>{{ current.sources.length }}</strong><small>依据来源</small></span></div><div><span class="stat-icon"><Layers :size="19" /></span><span><strong>{{ current.runs.length }}</strong><small>分析记录</small></span></div><div class="stat-last"><ShieldCheck :size="22" /><p>让结论回到原文<small>引用关联与法律判断分开核验</small></p></div></div>
          <nav class="tabs" aria-label="案件内容"><button :class="{ active: tab === 'materials' }" @click="tab = 'materials'">案件素材 <span>{{ current.materials.length }}</span></button><button :class="{ active: tab === 'sources' }" @click="tab = 'sources'">法律依据 <span>{{ current.sources.length }}</span></button><button :class="{ active: tab === 'analysis' }" @click="tab = 'analysis'">分析与草稿 <span v-if="active" class="live-dot"></span></button></nav>
          <div class="workspace-grid">
            <div class="workspace-main">
              <template v-if="tab === 'materials'">
                <div class="section-heading"><div><h2>案件素材</h2><p class="muted small">选择本次分析使用的文件，保留原始文件与页码。</p></div><button class="text-button" @click="refreshDetail"><RefreshCw :size="15" />刷新</button></div>
                <div class="dropzone" @dragover.prevent @drop="onDrop"><span class="upload-symbol"><UploadCloud :size="27" /></span><h3>{{ busy === 'upload' ? '正在上传材料…' : '将案件材料拖到这里' }}</h3><p>或 <button class="inline-button" :disabled="!!busy || !!active" @click="fileInput?.click()">选择文件上传</button></p><small>PDF / PNG / JPG / WebP / TXT / MD · 单文件 20MB · PDF 最多 80 页</small><input ref="fileInput" type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.md" hidden @change="uploadFiles(($event.target as HTMLInputElement).files)"></div>
                <div v-if="!current.materials.length" class="empty-inline"><FileText :size="21" /><div>材料还未加入<p>先上传合同、沟通记录或证据，让分析有据可依。</p></div></div>
                <div v-else class="material-list"><article v-for="m in current.materials" :key="m.id" class="material-item"><input type="checkbox" v-model="selected" :value="m.id" :aria-label="'选择 ' + m.name"><span class="file-icon"><FileText :size="21" /></span><div class="material-info"><button class="file-name" @click="preview(m)">{{ m.name }}</button><p>{{ (m.size / 1024).toFixed(1) }} KB · {{ m.page_count || '—' }} 页 · {{ date(m.created_at) }}</p><p v-if="m.error" class="error-text">{{ m.error }}</p></div><div class="material-actions"><span class="badge" :class="['ready'].includes(m.status) ? 'green' : 'neutral'">{{ labels[m.status] }}</span><div v-if="!['queued', 'processing'].includes(m.status)"><button class="text-button" :disabled="!!active || !!busy" @click="reparse(m.id)">重新解析</button><button v-if="m.mime === 'application/pdf' || m.mime.startsWith('image/')" class="text-button" :disabled="!!active || !!busy" @click="reparse(m.id, true)">全页视觉识别</button></div></div></article></div>
                <p class="hint"><CircleHelp :size="14" />扫描页需配置图片模型；全页视觉识别会按页调用模型。关键金额、日期、签章需对照原件复核。</p>
              </template>
              <template v-else-if="tab === 'sources'">
                <div class="section-heading"><div><h2>法律依据与来源</h2><p class="muted small">原文按版本保存，导入不等于效力已核实。</p></div><button @click="sourceModal = true"><Plus :size="16" />添加来源</button></div>
                <div class="source-note"><BookOpen :size="20" /><div>建立可以回看的依据<p>粘贴法规或案例正文，也可读取官方网页。付费检索可在设置中按需开启。</p></div></div>
                <div v-if="!current.sources.length" class="empty-block"><BookOpen :size="32" /><h3>还没有导入来源</h3><p>没有外部依据时，分析会明确标出研究缺口。</p><button @click="sourceModal = true">导入第一份依据<ArrowUpRight :size="15" /></button></div>
                <article v-for="s in current.sources" :key="s.id" class="source-item"><input type="checkbox" v-model="selectedSources" :value="s.id" :aria-label="'选择 ' + s.title"><div><button class="file-name" @click="previewSource(s.id)">{{ s.title }}</button><p class="muted small">版本：{{ s.version || '未标明' }} · {{ date(s.created_at) }}</p><a v-if="safeURL(s.url)" :href="safeURL(s.url)" target="_blank" rel="noopener noreferrer" class="source-link">查看原始网页 <ArrowUpRight :size="12" /></a></div><span class="badge neutral">效力未核验</span></article>
              </template>
              <template v-else>
                <div class="section-heading"><div><h2>分析与草稿</h2><p class="muted small">每次分析独立留档，草稿可回看引用与复核结果。</p></div><select v-if="current.runs.length" aria-label="选择历史分析" :value="run?.id" @change="chooseRun(($event.target as HTMLSelectElement).value)"><option v-for="r in current.runs" :key="r.id" :value="r.id">{{ date(r.created_at) }} · {{ labels[r.status] }}</option></select></div>
                <div v-if="!run" class="empty-block"><Layers :size="33" /><h3>准备开始第一次分析</h3><p>选择材料，在右侧写下需要解决的问题。</p></div>
                <template v-else>
                  <div class="run-header"><span class="badge" :class="run.status === 'failed' ? 'red' : 'neutral'">{{ labels[run.status] }}</span><span class="small muted">{{ run.model_info.provider }} / {{ run.model_info.model }}</span><button v-if="active" class="text-button danger" @click="cancel">取消任务</button><a v-if="run.result?.draft" class="button" :href="`/api/runs/${run.id}/export`"><Download :size="15" />导出草稿</a></div>
                  <div v-if="run.error" class="alert error">{{ run.error }}</div>
                  <div v-if="events.length" class="activity"><div v-for="ev in events" :key="ev.id"><span class="activity-dot"></span><time>{{ date(ev.created_at) }}</time><span>{{ ev.message }}</span></div></div>
                  <article v-if="run.result?.draft" class="report"><p class="eyebrow">ANALYSIS DRAFT</p><h2>{{ run.result.draft.title }}</h2><p>{{ run.result.draft.summary }}</p><div class="scope-note"><ShieldCheck :size="18" /><div>{{ run.result.coverage.note }}<p v-for="gap in run.result.coverage.unreadable_pages" :key="gap">{{ gap }}</p></div></div>
                    <section v-for="(section, i) in run.result.draft.sections" :key="i"><h3>{{ section.title }}</h3><p>{{ section.summary }}</p><div v-for="(claim, j) in section.claims" :key="j" class="claim"><p>{{ claim.text }}</p><div class="citation-row"><span class="claim-kind">{{ labels[claim.kind] }}</span><button v-for="ref in claim.citations" :key="ref" @click="showEvidence(ref)"><FileText :size="12" />{{ run.result.evidence[ref]?.name || '未找到引用' }}{{ run.result.evidence[ref]?.page ? ' · 第' + run.result.evidence[ref].page + '页' : '' }}</button><span v-if="!claim.citations.length" class="small error-text">缺少原文引用</span></div></div><ul v-if="section.gaps.length"><li v-for="gap in section.gaps" :key="gap">待补充：{{ gap }}</li></ul></section>
                    <section class="review-section"><h3><ShieldCheck :size="19" />独立复核</h3><p>{{ run.result.review_summary }}</p><div v-for="claim in run.result.claims" :key="claim.index" class="review-item"><div><span class="badge" :class="claim.support === 'supported' ? 'green' : 'red'">{{ labels[claim.support] }}</span><span class="small muted">{{ labels[claim.association] }}{{ claim.validity === 'needs_review' ? ' · 法律效力待核验' : '' }}</span></div><p>{{ claim.text }}</p><small>{{ claim.reason }}</small></div><p v-for="issue in run.result.issues" :key="issue" class="error-text">{{ issue }}</p></section>
                    <section><h3>下一步</h3><ol><li v-for="step in run.result.draft.next_steps" :key="step">{{ step }}</li></ol><p v-for="limit in run.result.draft.limitations" :key="limit" class="hint">{{ limit }}</p></section>
                    <p class="report-footer">草稿供复核使用。来源关联、模型复核与法律效力是不同维度。</p>
                  </article>
                </template>
              </template>
            </div>
            <aside class="analysis-side"><section class="panel analysis-card"><div class="section-title"><span class="small-logo"><Scale :size="18" /></span><h2>协作分析</h2></div><p class="muted small">四个角色，共同围绕你的问题工作。</p><div class="role-list"><div v-for="(role, i) in roles" :key="role.key" :class="{ working: active && run.stage === role.key, finished: !!run?.outputs?.[role.key] }"><span>{{ run?.outputs?.[role.key] ? '✓' : '0' + (i + 1) }}</span><div><strong>{{ role.name }}</strong><small>{{ role.detail }}</small></div><span v-if="active && run.stage === role.key" class="live-dot"></span></div></div>
              <form @submit.prevent="startRun"><label>这次需要完成什么？<select v-model="mode"><option value="analysis">案件分析与诉前评估</option><option value="complaint">民事起诉状草稿</option><option value="defense">民事答辩状草稿</option></select></label><label>你的问题<textarea v-model="question" rows="5" required minlength="2" placeholder="例如：梳理争议事实，指出证据缺口，并给出下一步建议。"></textarea></label><div class="selection-summary">已选 {{ selected.length }} 份素材 · {{ selectedSources.length }} 份依据</div><button class="primary full" :disabled="!!busy || !!active || !modelReady || (!selected.length && !selectedSources.length)"><Layers :size="16" />{{ active ? '角色正在协作…' : '开始分析' }}<ArrowRight :size="16" /></button></form>
              <button v-if="!modelReady" class="configure-link" @click="view = 'settings'">先配置模型，再开始分析<ArrowUpRight :size="14" /></button><p class="hint">分析会将所选材料发送给配置的模型服务。未接入检索时保留依据缺口。</p>
            </section><div class="aside-note"><ShieldCheck :size="18" /><p>原文在旁，判断有据。<small>点击草稿中的引用，随时回看来源。</small></p></div></aside>
          </div>
        </template>
      </div><footer class="app-footer">律序 · 法律工作台 <span>事实 / 依据 / 判断</span></footer>
    </div>
    <div v-if="newCase" class="modal-backdrop" @click.self="newCase = false"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="case-modal-title"><div class="modal-head"><h2 id="case-modal-title">建立新的案件工作区</h2><button class="icon-button" aria-label="关闭" @click="newCase = false"><X :size="20" /></button></div><p class="muted small">将相关材料和分析放在同一个案件中。</p><form @submit.prevent="createCase"><label>案件名称<input v-model="caseForm.title" required maxlength="200" autofocus placeholder="例如：劳动合同解除争议"></label><label>案件类型<select v-model="caseForm.category"><option value="civil">中国民事争议</option><option value="labor">中国劳动争议</option></select></label><label>背景与需要解决的问题<textarea v-model="caseForm.description" rows="4" placeholder="描述已知事实和你的目标，稍后可以在分析问题中补充。"></textarea></label><button class="primary full" :disabled="!!busy">{{ busy === 'case' ? '创建中…' : '创建案件' }}<ArrowRight :size="16" /></button></form></section></div>
    <div v-if="sourceModal" class="modal-backdrop" @click.self="sourceModal = false"><section class="modal large" role="dialog" aria-modal="true" aria-labelledby="source-modal-title"><div class="modal-head"><h2 id="source-modal-title">添加依据来源</h2><button class="icon-button" aria-label="关闭" @click="sourceModal = false"><X :size="20" /></button></div><div class="tabs"><button :class="{ active: sourceMode === 'paste' }" @click="sourceMode = 'paste'">粘贴原文</button><button :class="{ active: sourceMode === 'url' }" @click="sourceMode = 'url'">读取官方网页</button></div><form @submit.prevent="addSource"><template v-if="sourceMode === 'paste'"><label>来源标题<input v-model="sourceForm.title" required></label><div class="two-columns"><label>版本说明<input v-model="sourceForm.version" placeholder="例如：2023 年修正"></label><label>施行日期<input type="date" v-model="sourceForm.effective_date"></label></div><label>来源链接（可选）<input v-model="sourceForm.url" type="url"></label><label>完整原文<textarea v-model="sourceForm.content" rows="8" required placeholder="保留条号、上下文和出处；不要只粘贴搜索摘要。"></textarea></label></template><template v-else><label>官方 HTML 网页 URL<input type="url" v-model="sourceURL" required placeholder="https://…gov.cn/…"></label><p class="hint">支持 gov.cn、npc.gov.cn。动态网页读取失败时可粘贴正文；PDF 请作为素材上传。</p></template><p class="hint">来源按原文与版本分别保存，导入后标记为效力未核验。</p><p v-if="error" class="alert error">{{ error }}</p><button class="primary full" :disabled="!!busy">{{ busy === 'source' ? '正在导入…' : '保存来源' }}</button></form></section></div>
    <div v-if="evidence" class="modal-backdrop" @click.self="evidence = null"><section class="modal evidence-modal" role="dialog" aria-modal="true" aria-labelledby="evidence-title"><div class="modal-head"><div><p class="eyebrow">SOURCE DOCUMENT</p><h2 id="evidence-title">{{ evidence.name }}</h2></div><button class="icon-button" aria-label="关闭原文" @click="evidence = null"><X :size="20" /></button></div><div class="button-row"><select v-if="previewPages.length" aria-label="选择页码" :value="evidence.page" @change="setPreviewPage(previewPages.find(p => p.number === +($event.target as HTMLSelectElement).value))"><option v-for="p in previewPages" :key="p.id" :value="p.number">第 {{ p.number }} 页</option></select><span v-else-if="evidence.page" class="badge neutral">第 {{ evidence.page }} 页 · 本次分析快照</span><a v-if="evidence.material_id" :href="`/api/materials/${evidence.material_id}/file`" target="_blank" rel="noopener" class="button">打开原件<ArrowUpRight :size="14" /></a><a v-if="safeURL(evidence.url)" :href="safeURL(evidence.url)" target="_blank" rel="noopener" class="button">原始网页<ArrowUpRight :size="14" /></a></div><p v-if="evidence.warning" class="hint">{{ evidence.warning }}</p><div class="evidence-content"><img v-if="evidence.has_image || (evidence.page && evidence.method && evidence.method !== 'text')" :src="`/api/materials/${evidence.material_id}/file?page=${evidence.page}`" alt="原始材料页面"><pre>{{ evidence.text || '未提取到文字。请查看原件或使用图片识别。' }}</pre></div></section></div>
    <div v-if="feeModal" class="modal-backdrop" @click.self="feeModal = false"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="fee-title"><div class="modal-head"><h2 id="fee-title">诉讼费估算</h2><button class="icon-button" aria-label="关闭" @click="feeModal = false"><X :size="20" /></button></div><p class="hint">普通民事财产案件受理费，不适用于所有案类。</p><form @submit.prevent="calculate"><label>请求金额（元）<input type="number" min="0" max="1000000000000" step="0.01" v-model="amount" required></label><button class="primary full">计算估算费用</button></form><div v-if="fee" class="fee-result"><small>估算案件受理费</small><strong>¥ {{ fee.fee }}</strong><p>{{ fee.scope }}</p><p class="hint">{{ fee.verification }}</p></div><p v-if="error" class="alert error">{{ error }}</p></section></div>
  </div>
</template>
