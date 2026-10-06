<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Save, PlugZap, Check, ShieldCheck } from 'lucide-vue-next'
import { api, post } from './api'
const props = defineProps<{ accountName: string }>()
const emit = defineEmits(['saved', 'account-changed'])
const account = ref({ username: props.accountName, current_password: '', password: '', confirm: '' })
async function saveAccount() {
  if (account.value.password !== account.value.confirm) { error.value = '两次输入的新密码不一致'; return }
  busy.value = 'account'; error.value = ''; message.value = ''
  try {
    await api('/account', { method: 'PUT', body: JSON.stringify({ username: account.value.username.trim(), current_password: account.value.current_password, password: account.value.password }) })
    account.value.current_password = ''; account.value.password = ''; account.value.confirm = ''
    emit('account-changed', account.value.username.trim())
  } catch (e: any) { error.value = e.message } finally { busy.value = '' }
}
const config = ref<any>(null)
const busy = ref('')
const error = ref('')
const message = ref('')
const tools = ref<any[]>([])
const argumentsText = ref('{}')
const clearModelKeys = new Set<string>()
async function load() {
  try { config.value = await api('/settings'); argumentsText.value = JSON.stringify(config.value.mcp.arguments, null, 2) }
  catch (e: any) { error.value = e.message }
}
onMounted(load)
async function save() {
  busy.value = 'save'; error.value = ''; message.value = ''
  try {
    config.value.mcp.arguments = JSON.parse(argumentsText.value)
    const payload = JSON.parse(JSON.stringify(config.value))
    for (const [name, provider] of Object.entries<any>(payload.providers)) {
      if (!provider.api_key && !clearModelKeys.has(name)) delete provider.api_key
    }
    for (const key of ['secret_id', 'secret_key']) if (!payload.storage[key]) delete payload.storage[key]
    if (!payload.mcp.token) delete payload.mcp.token
    config.value = await api('/settings', { method: 'PATCH', body: JSON.stringify(payload) })
    clearModelKeys.clear()
    message.value = '配置已保存'; emit('saved')
  } catch (e: any) { error.value = e.message || '配置无效' }
  finally { busy.value = '' }
}
async function test(target: string) {
  busy.value = target; error.value = ''; message.value = ''
  try {
    const r = await api('/settings/test/' + target, post())
    if (r.tools) { tools.value = r.tools; message.value = `连接成功，发现 ${r.tools.length} 个工具` }
    else message.value = r.message
  } catch (e: any) { error.value = e.message }
  finally { busy.value = '' }
}
</script>

<template>
  <div class="settings-page">
    <div class="page-heading"><div><p class="eyebrow">WORKSPACE SETTINGS</p><h1>工作台设置</h1><p class="muted">管理账号、模型、文件存储与可选检索服务。</p></div><button class="primary" :disabled="!!busy || !config" @click="save"><Save :size="16" />{{ busy === 'save' ? '保存中…' : '保存配置' }}</button></div>
    <p v-if="error" class="alert error" role="alert">{{ error }}</p><p v-if="message" class="alert success" role="status"><Check :size="16" />{{ message }}</p>
    <div v-if="config" class="settings-grid">
      <section class="panel settings-card wide">
        <div class="section-title"><ShieldCheck :size="20" /><h2>账号与密码</h2></div>
        <p class="muted small">修改时需要验证当前密码。保存后所有已登录设备都会退出，请使用新账号和密码重新登录。</p>
        <form @submit.prevent="saveAccount">
          <div class="two-columns">
            <label>登录账号<input v-model="account.username" autocomplete="username" required minlength="3" maxlength="64" pattern="[A-Za-z0-9_.@-]+"></label>
            <label>当前密码<input v-model="account.current_password" type="password" autocomplete="current-password" required maxlength="256"></label>
            <label>新密码<input v-model="account.password" type="password" autocomplete="new-password" required minlength="12" maxlength="256" placeholder="至少 12 个字符"></label>
            <label>确认新密码<input v-model="account.confirm" type="password" autocomplete="new-password" required minlength="12" maxlength="256"></label>
          </div>
          <button type="submit" :disabled="!!busy">{{ busy === 'account' ? '正在保存…' : '保存账号与密码' }}</button>
        </form>
      </section>
      <section class="panel settings-card"><div class="section-title"><span class="step-number">01</span><h2>大模型</h2><span class="badge">必需</span></div>
        <p class="muted small">先保存，再分别测试文本与图片能力。测试会调用所选模型。</p>
        <label>当前供应商<select v-model="config.provider"><option value="deepseek">DeepSeek 直连</option><option value="tokenhub">腾讯云 TokenHub</option></select></label>
        <label>接口地址<input v-model="config.providers[config.provider].base_url" placeholder="https://…/v1"></label>
        <label>模型 ID<input v-model="config.providers[config.provider].model" placeholder="填写该供应商提供的模型 ID"></label>
        <label>API Key<input type="password" autocomplete="new-password" v-model="config.providers[config.provider].api_key" :placeholder="config.providers[config.provider].has_key ? '已保存；留空不修改' : '尚未配置'"></label>
        <label class="check-row"><input type="checkbox" v-model="config.providers[config.provider].vision">该模型支持图片输入</label>
        <label class="check-row"><input type="checkbox" v-model="config.providers[config.provider].json_mode">使用 JSON 模式（供应商支持时启用）</label>
        <p class="hint">图片能力按模型单独确认；TokenHub 的模型 ID 与直连可能不同。</p>
        <div class="button-row"><button :disabled="!!busy" @click="test('model')"><PlugZap :size="15" />测试文本</button><button :disabled="!!busy" @click="test('vision')">测试图片</button><button class="text-button danger" @click="clearModelKeys.add(config.provider); config.providers[config.provider].api_key = ''; message = '密钥将于保存后清除'">清除密钥</button></div>
      </section>
      <section class="panel settings-card"><div class="section-title"><span class="step-number">02</span><h2>素材存储</h2></div>
        <label>存储方式<select v-model="config.storage.mode"><option value="local">本地开发存储</option><option value="cos">腾讯云 COS</option></select></label>
        <p class="hint">COS 未配置时可在本地验证流程。切换仅影响新上传文件；旧文件保留原存储位置。</p>
        <label>地域<input v-model="config.storage.region" placeholder="ap-guangzhou"></label><label>存储桶<input v-model="config.storage.bucket" placeholder="bucket-appid"></label>
        <label>SecretId<input type="password" autocomplete="new-password" v-model="config.storage.secret_id" :placeholder="config.storage.has_secret_id ? '已保存；留空不修改' : 'COS SecretId'"></label>
        <label>SecretKey<input type="password" autocomplete="new-password" v-model="config.storage.secret_key" :placeholder="config.storage.has_secret_key ? '已保存；留空不修改' : 'COS SecretKey'"></label>
        <div class="button-row"><button :disabled="!!busy" @click="test('cos')"><PlugZap :size="15" />测试存储桶</button></div>
        <p class="hint"><ShieldCheck :size="14" />密钥在后端加密保存，文件通过已登录的后端接口读取。</p>
      </section>
      <section class="panel settings-card wide"><div class="section-title"><span class="step-number">03</span><h2>法律检索 MCP</h2><span class="badge neutral">可选</span></div>
        <p class="muted small">不启用也可分析上传材料。启用后仅调用你配置的只读检索工具，失败时保留来源缺口并继续材料分析。</p>
        <label class="check-row"><input type="checkbox" v-model="config.mcp.enabled">分析时使用法律检索服务</label>
        <div class="two-columns"><label>服务地址<input v-model="config.mcp.url" placeholder="https://…/mcp"></label><label>协议<select v-model="config.mcp.transport"><option value="streamable-http">Streamable HTTP</option><option value="sse">SSE</option></select></label></div>
        <label>Bearer Token（按服务要求）<input type="password" autocomplete="new-password" v-model="config.mcp.token" :placeholder="config.mcp.has_token ? '已保存；留空不修改' : '可选'"></label>
        <div class="two-columns"><label>只读检索工具名<input v-model="config.mcp.tool" list="mcp-tools" placeholder="search_article"><datalist id="mcp-tools"><option v-for="t in tools" :key="t.name" :value="t.name">{{ t.description }}</option></datalist></label><label>查询参数名<input v-model="config.mcp.query_field" placeholder="text"></label></div>
        <label>其他固定参数（JSON）<textarea v-model="argumentsText" rows="3" spellcheck="false"></textarea></label>
        <p class="hint">标准返回支持 sources/results 数组中的 title、content、url、version；非结构化结果会标注为待适配，不作为已核验依据。</p>
        <button :disabled="!!busy" @click="test('mcp')"><PlugZap :size="15" />连接并发现工具</button>
        <details v-if="tools.length"><summary>查看工具参数</summary><pre>{{ JSON.stringify(tools, null, 2) }}</pre></details>
      </section>
    </div><p v-else class="muted">正在加载设置…</p>
  </div>
</template>
