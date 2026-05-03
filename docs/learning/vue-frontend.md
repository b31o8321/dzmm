# Vue3 前端实现

---

## 1. 项目用了哪些前端技术

| 技术 | 用途 | 文件 |
|------|------|------|
| Vue3 Composition API | UI 框架 | 所有 `.vue` 文件 |
| TypeScript | 类型安全 | 所有 `.ts` 文件 |
| Pinia | 全局状态管理 | `stores/` |
| Vue Router | 路由 | `router/index.ts` |
| Element Plus | UI 组件库 | 全局使用 |
| Vite | 构建工具 | `vite.config.ts` |

---

## 2. Vue3 响应式核心：ref 和 reactive

Vue3 的核心是"响应式"——状态变了，UI 自动更新。

### ref：基本类型的响应式包装

[`composables/useGameTurn.ts`](https://github.com/b31o8321/dzmm/blob/main/frontend/src/composables/useGameTurn.ts)：

```typescript
import { ref } from 'vue'

const turns = ref<Turn[]>([])     // Turn[] 的响应式容器
const sending = ref(false)        // boolean 的响应式容器
const turnCount = ref(0)

// 读取值必须 .value
console.log(sending.value)        // false
// 修改值也必须 .value → 触发 Vue 更新所有依赖这个值的组件
sending.value = true
```

**在模板里不需要 `.value`（Vue 自动解包）：**
```html
<button :disabled="sending">发送</button>   <!-- 直接用 sending，不用 sending.value -->
```

### reactive：对象的响应式包装（深度代理）

```typescript
import { reactive } from 'vue'

// 问题：普通对象的字段变化 Vue 不知道
const turn = { narrative: '', choices: [] }
turn.narrative += '你走进酒馆'   // Vue 不会重渲染！

// 解决：用 reactive 包装
const turn = reactive({ narrative: '', choices: [] })
turn.narrative += '你走进酒馆'   // Vue 检测到变化 → 自动更新 UI ✓
```

**为什么流式文本必须用 reactive？**（代码注释里有解释）

```typescript
// useGameTurn.ts:104
// IMPORTANT: wrap in reactive() so subsequent turn.narrative += text mutations
// go through the Vue reactivity proxy. Without this, streaming text updates
// the underlying object but Vue doesn't notice because the local `turn` var
// bypasses the proxy — leading to blank narrative until a refresh.
const turn: Turn = reactive({
    action: userAction,
    narrative: '',
    choices: [],
    events: [],
    turn: turnCount.value + 1,
})
```

---

## 3. Composable：把状态和逻辑打包复用

Composable 是 Vue3 的核心设计模式。把相关的响应式状态 + 操作函数打包成一个普通函数，在组件里调用。

### useGameTurn：管理回合状态

[`composables/useGameTurn.ts`](https://github.com/b31o8321/dzmm/blob/main/frontend/src/composables/useGameTurn.ts)：

```typescript
export function useGameTurn(sessionId: number, gs: GameStateBindings, hooks: UseGameTurnHooks = {}) {
    // 内部状态（每次调用 useGameTurn 都是独立的）
    const turns = ref<Turn[]>([])
    const sending = ref(false)
    const sceneMood = ref<SceneMood>('neutral')

    async function sendAction(userAction: string) {
        if (!userAction || sending.value) return
        sending.value = true
        
        const turn: Turn = reactive({ action: userAction, narrative: '', choices: [], events: [], turn: 0 })
        turns.value.push(turn)
        
        try {
            await streamTurn(sessionId, userAction, {
                onNarrative: (text) => { turn.narrative += text },  // 流式累积
                onTag: (name, attrs, content) => { /* 处理各种标签 */ },
                onDone: () => { turnCount.value += 1 },
            })
        } finally {
            sending.value = false
        }
    }

    // 返回外部需要的状态和方法
    return { turns, sending, sceneMood, sendAction }
}
```

**在 GameView.vue 里使用：**
```typescript
const { turns, sending, sceneMood, sendAction } = useGameTurn(sessionId, gameState, {
    onScroll: () => scrollToBottom(),
    onTurnDone: () => refreshNpcs(),
})
```

---

## 4. SSE 消费：接收 LLM 流式响应

### SSE 协议格式

后端推送的 SSE 是这样的文本流：
```
event: narrative
data: {"text": "你"}

event: narrative
data: {"text": "走进"}

event: tag
data: {"name": "npc_update", "attrs": {"name": "老板"}, "content": "注意到你"}

event: done
data: {}
```

### 前端用 fetch + ReadableStream 解析

[`composables/useTurnStream.ts`](https://github.com/b31o8321/dzmm/blob/main/frontend/src/composables/useTurnStream.ts)：

```typescript
export async function streamTurn(sessionId, action, handlers) {
    // fetch 比 EventSource 灵活：支持 POST、自定义 headers、AbortSignal
    const resp = await fetch(`/sessions/${sessionId}/turn`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify({ action }),
    })
    
    const reader = resp.body.getReader()    // 获取流读取器
    const decoder = new TextDecoder('utf-8')
    let buf = ''
    
    while (true) {
        const { value, done } = await reader.read()  // 读取下一块二进制数据
        if (done) break
        buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
        
        let nl: number
        // SSE 事件之间用 \n\n 分隔，找到完整事件块后处理
        while ((nl = buf.indexOf('\n\n')) >= 0) {
            const block = buf.slice(0, nl)
            buf = buf.slice(nl + 2)
            dispatch(block, handlers)     // 解析并分发事件
        }
    }
}

function dispatch(block: string, h: TurnHandlers) {
    let event = 'message'
    let data = ''
    for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7).trim()
        else if (line.startsWith('data: ')) data += line.slice(6)
    }
    
    const parsed = JSON.parse(data)
    switch (event) {
        case 'narrative': h.onNarrative?.(parsed.text ?? ''); break
        case 'tag':       h.onTag?.(parsed.name, parsed.attrs ?? {}, parsed.content ?? ''); break
        case 'done':      h.onDone?.(); break
    }
}
```

**为什么不用浏览器原生 `EventSource`？**  
`EventSource` 只支持 GET 请求，但我们需要 POST（传 `action` 请求体）。所以用 `fetch` 手动解析 SSE 格式。

---

## 5. Pinia Store：全局状态管理

Composable 是组件内的局部状态；Pinia Store 是跨组件共享的全局状态。

### sessions store

[`stores/sessions.ts`](https://github.com/b31o8321/dzmm/blob/main/frontend/src/stores/sessions.ts)：

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'

// defineStore 第一个参数是 Store 的唯一 ID
export const useSessionsStore = defineStore('sessions', () => {
    // 响应式状态（所有组件共享同一份）
    const items = ref<GameSession[]>([])
    const loading = ref(false)
    
    async function refresh() {
        loading.value = true
        try {
            items.value = await sessionsApi.list()
        } finally {
            loading.value = false
        }
    }
    
    async function create(body: SessionIn) {
        const s = await sessionsApi.create(body)
        items.value.push(s)    // 修改 items → 所有用 sessions.items 的组件自动更新
        return s
    }
    
    async function remove(id: number) {
        await sessionsApi.delete(id)
        items.value = items.value.filter((s) => s.id !== id)   // 过滤掉已删除的
    }
    
    return { items, loading, refresh, create, remove }
})
```

**在任何组件里使用：**
```typescript
const sessions = useSessionsStore()
await sessions.refresh()
// sessions.items 是 ref，模板里直接用 sessions.items（不需要 .value）
```

---

## 6. API 封装层

所有 HTTP 请求都封装在 `api/` 目录下，组件不直接调用 `fetch`。

### 统一 axios 客户端

[`api/client.ts`](https://github.com/b31o8321/dzmm/blob/main/frontend/src/api/client.ts) 配置了 baseURL 和错误处理，所有接口复用这一个实例。

### sessions API

[`api/sessions.ts`](https://github.com/b31o8321/dzmm/blob/main/frontend/src/api/sessions.ts)：

```typescript
export const sessionsApi = {
    list: () => api.get<GameSession[]>('/sessions').then(r => r.data),
    get: (id: number) => api.get<GameSession>(`/sessions/${id}`).then(r => r.data),
    create: (body: SessionIn) => api.post<GameSession>('/sessions', body).then(r => r.data),
    delete: (id: number) => api.delete(`/sessions/${id}`),
    messages: (id: number) => api.get<MessageRow[]>(`/sessions/${id}/messages`).then(r => r.data),
}
```

---

## 7. 场景氛围检测：纯前端逻辑

根据叙事文本关键词判断场景氛围，用于背景音乐切换：

[`composables/useGameTurn.ts`](https://github.com/b31o8321/dzmm/blob/main/frontend/src/composables/useGameTurn.ts)：

```typescript
const _MOOD_WORDS = {
    tense:      ['紧张','危险','战斗','追','逃','血','刀','剑','杀'],
    horror:     ['恐惧','鬼','尸','黑暗','阴森','诡异'],
    romantic:   ['温柔','心跳','甜','红晕','靠近','爱意'],
    mysterious: ['神秘','迷雾','秘密','命运','未知'],
    neutral:    [],
}

export function detectSceneMood(narrative: string): SceneMood {
    const scores = { tense: 0, horror: 0, romantic: 0, mysterious: 0 }
    for (const [mood, words] of Object.entries(_MOOD_WORDS)) {
        if (mood === 'neutral') continue
        for (const w of words) if (narrative.includes(w)) scores[mood]++
    }
    const sorted = Object.entries(scores).sort((a, b) => b[1] - a[1])
    return sorted[0][1] >= 2 ? sorted[0][0] as SceneMood : 'neutral'
    //                   ↑ 至少 2 个关键词才认定，避免单词误判
}

// 每回合结束时检测
onDone: () => {
    sceneMood.value = detectSceneMood(turn.narrative)
}
```

---

## 8. LLM 输出清理：去除混入的 XML 标签

GM 有时会把 `<state_change>` 等标签混入 `<narrative>` 里。前端清理后才显示：

[`composables/useGameTurn.ts`](https://github.com/b31o8321/dzmm/blob/main/frontend/src/composables/useGameTurn.ts)：

```typescript
const ANY_KNOWN_CHILD_RE =
    /<(?:choices|state_change|npc_update|plot_event|dice)\b[^>]*>[\s\S]*?(?:<\/(?:choices|state_change|npc_update|plot_event|dice)>|$)/g

export function cleanNarrative(raw: string): string {
    return raw
        .replace(ANY_KNOWN_CHILD_RE, '')               // 移除已知子标签
        .replace(/<think\b[^>]*>[\s\S]*?<\/think>/gi, '')  // 移除 DeepSeek 推理块
        .replace(/<\/?\w+\b[^>]*>/g, '')               // 移除任何残留 XML 标签
        .trim()
}

// 回合结束时清理
onDone: () => {
    turn.narrative = cleanNarrative(turn.narrative)
}
```

---

## 9. TypeScript 接口定义

TypeScript 让前后端的数据结构有类型保障，和 API 文档一样起文档作用：

[`api/sessions.ts`](https://github.com/b31o8321/dzmm/blob/main/frontend/src/api/sessions.ts)：

```typescript
export interface MessageEvent {
    type: string
    payload: Record<string, any>    // Record<K,V> = { [key: K]: V }，相当于 Map<String, Any>
    content?: string                // ? 表示可选字段
}

export interface SessionState {
    stats: Record<string, number>
    inventory: string[]
    npcs: { name: string; favor: number; state: string }[]  // 内联接口定义
    threads: { type: string; description: string; importance: number }[]
}
```

**组件里的依赖注入接口（面向接口编程）：**

```typescript
// useGameTurn.ts
export interface GameStateBindings {
    applyStateChange: (content: string) => void
    applyNpcUpdate: (content: string) => void
    pushDice: (d: { skill: string; target: string; result: string; success?: string; fail?: string }) => void
    threads: Ref<{ type: string; description: string; importance: number }[]>
}

// useGameTurn 不直接引用 GameView 里的变量，而是通过接口注入
// 这样 useGameTurn 可以独立测试，也可以被其他页面复用
export function useGameTurn(sessionId: number, gs: GameStateBindings, hooks: UseGameTurnHooks = {}) {
    // 内部通过 gs.applyStateChange() 操作外部状态
}
```
