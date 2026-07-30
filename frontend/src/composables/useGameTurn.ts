// ============================================================
// useGameTurn — 游戏回合管理（Vue3 Composable）
// ============================================================
// 【Vue3 Composable 是什么？】
//   Composable 就是"把相关的响应式状态和函数打包成一个可复用的函数"。
//   类似 React Hooks，但用的是 Vue3 的 Composition API。
//   【Java 对比】有点像 Service 类，但它直接持有 UI 状态（ref/reactive）。
//
// 【这个文件做什么？】
//   管理"发送行动 → 接收 LLM 流式响应 → 更新 UI 状态"的完整流程。
//   前端所有"回合"逻辑都在这里，GameView.vue 只是调用它、渲染它的状态。
// ============================================================

import { reactive, ref, type Ref } from 'vue'
// reactive(obj)  → 使对象的每个属性都变成响应式（深度代理）
// ref(value)     → 把基本类型（string/number/boolean）包成响应式容器
// Ref<T>         → ref() 返回值的类型（泛型）
// 【Java 对比】可以理解为"自动触发 UI 更新的 AtomicReference/AtomicInteger"

// ── 场景氛围检测 ──────────────────────────────────────────
// 根据叙事文本的关键词判断当前场景氛围，用于背景音乐/色调切换

export type SceneMood = 'neutral' | 'tense' | 'horror' | 'romantic' | 'mysterious'

// 每种氛围的触发关键词列表（中文关键词）
const _MOOD_WORDS: Record<SceneMood, string[]> = {
  tense:      ['紧张','警戒','危险','战斗','追','逃','血','刀','剑','杀','威胁','慌','急','激烈','冲突','搏斗'],
  horror:     ['恐惧','恐怖','鬼','尸','黑暗','阴森','诡异','寒意','颤','惊悚','骇人','阴冷','异动'],
  romantic:   ['温柔','温暖','心跳','甜','红晕','羞','靠近','触碰','柔软','爱意','情意','脸红','心软'],
  mysterious: ['神秘','迷雾','秘密','预言','暗影','谜','命运','异象','古老','玄','未知','离奇'],
  neutral:    [],
}

export function detectSceneMood(narrative: string): SceneMood {
  // Record<string, number> 是 TypeScript 的键值对类型（相当于 Map<String, Integer>）
  const scores: Record<string, number> = { tense: 0, horror: 0, romantic: 0, mysterious: 0 }
  for (const [mood, words] of Object.entries(_MOOD_WORDS)) {
    if (mood === 'neutral') continue
    for (const w of words) if (narrative.includes(w)) scores[mood]++
  }
  // 按分数降序排列，取最高分
  const sorted = Object.entries(scores).sort((a, b) => b[1] - a[1])
  // 需要至少 2 个关键词才认定为该氛围，否则返回 neutral（避免误判）
  return sorted[0][1] >= 2 ? (sorted[0][0] as SceneMood) : 'neutral'
}

import { ElMessage } from 'element-plus'
import { streamTurn, TurnStreamError } from '@/composables/useTurnStream'
import { sessionsApi, type MessageEvent } from '@/api/sessions'
import { useAudio } from '@/composables/useAudio'

// ── 类型定义 ──────────────────────────────────────────────

export interface Turn {
  action: string       // 玩家输入的行动描述
  narrative: string    // GM 生成的叙事文本（流式累积）
  choices: string[]    // GM 给出的行动选项列表
  events: MessageEvent[] // 本回合的结构化事件（dice/state_change 等）
  diagnostics: string[]  // XML/协议等不影响叙事保存的回合级诊断
  turn: number         // 回合序号
  rawContent?: string  // 原始内容（含 XML 标签，用于重建对话气泡）
  msgId?: number       // debug: 对应数据库 Message.id（assistant 行），用于 debug 查看 prompt
}

// ── 正则表达式常量（预编译，性能更好）──────────────────────
// 匹配任何已知子标签（用于从叙事文本中剥离意外混入的标签）
const ANY_KNOWN_CHILD_RE =
  /<(?:choices|state_change|npc_update|plot_event|dice)\b[^>]*>[\s\S]*?(?:<\/(?:choices|state_change|npc_update|plot_event|dice)>|$)/g
const CHOICES_RE = /<choices\b[^>]*>([\s\S]*?)<\/choices>/g

export function cleanNarrative(raw: string): string {
  /**
   * 清理叙事文本：移除 LLM 错误混入的 XML 标签和 <think> 推理块。
   * LLM 有时会把 <state_change> 等内容夹在 <narrative> 里，这里把它们剥掉。
   */
  return raw
    .replace(ANY_KNOWN_CHILD_RE, '')           // 移除已知子标签
    .replace(/<think\b[^>]*>[\s\S]*?<\/think>/gi, '')  // 移除 DeepSeek 的推理块
    .replace(/<\/?\w+\b[^>]*>/g, '')           // 移除剩余的任何 XML 标签
    .trim()
}

export function extractChoices(content: string): string[] {
  /**
   * 从内容中提取 <choices> 标签里的选项列表。
   * LLM 有时会把 <choices> 放在 <narrative> 里（协议违规），
   * 这个函数作为降级处理，从文本中补救出选项。
   */
  const out: string[] = []
  let m: RegExpExecArray | null
  CHOICES_RE.lastIndex = 0  // 重置 regex 状态（有 g 标志的 regex 是有状态的）
  while ((m = CHOICES_RE.exec(content))) {
    for (const line of m[1].split('\n')) {
      const trimmed = line.trim().replace(/^[-*•・·]\s*/, '')  // 去掉列表符号
      if (trimmed) out.push(trimmed)
    }
  }
  return out
}

// ── 外部依赖接口 ──────────────────────────────────────────
// useGameTurn 需要调用 GameView 里的状态更新函数，通过接口注入而非直接引用，
// 实现了"依赖倒置"（和 Java 的 interface 注入思路一致）。

export interface GameStateBindings {
  applyStateChange: (content: string) => void   // 处理角色属性变化
  applyNpcUpdate: (content: string) => void     // 更新 NPC 信息
  applyPcMood: (content: string) => void        // 更新 PC 情绪
  pushDice: (d: { skill: string; target: string; result: string; success?: string; fail?: string }) => void
  threads: Ref<{ type: string; description: string; importance: number }[]>
}

export interface UseGameTurnHooks {
  onScroll?: () => void           // 有新文本时滚动到底部
  onTurnDone?: () => void         // 回合结束后执行（如刷新 NPC 列表）
  onNpcInitiative?: (npcName: string) => void  // NPC 主动出场时触发
  onLocationEnter?: (locationName: string) => void  // 玩家进入新地点时触发
  onBgmChange?: (mood: string) => void              // GM 切换背景音乐情绪时触发
  onChapterAdvance?: () => void                      // 章节推进时触发
  onRecoveryRequired?: () => Promise<void> | void    // event gap 后重读权威状态
}


// ── 主 Composable 函数 ────────────────────────────────────
export function useGameTurn(
  sessionId: number,
  gs: GameStateBindings,   // 依赖注入：外部状态操作函数
  hooks: UseGameTurnHooks = {},
) {
  // ref() 创建响应式引用。Vue 会追踪哪些组件读了它，值变化时自动重新渲染。
  // 访问/修改值需要 .value（这是 Vue3 的规则）
  const turns = ref<Turn[]>([])           // 所有已完成/进行中的回合
  const currentTurn = ref<Turn | null>(null)  // 当前正在流式生成的回合
  const turnCount = ref(0)
  const tokensIn = ref(0)
  const tokensOut = ref(0)
  const sending = ref(false)              // 是否正在发送（防止重复点击）
  const sceneMood = ref<SceneMood>('neutral')
  const audio = useAudio()               // 音效控制 composable

  async function sendAction(userAction: string) {
    if (!userAction || sending.value) return
    sending.value = true

    // reactive() 对对象做深度代理，确保 turn.narrative += text 能触发 Vue 重渲染。
    // 【注意】如果只写 const turn: Turn = {...}，JavaScript 对象不是响应式的，
    // Vue 不会追踪到字段变化，导致流式文本更新了对象但页面不刷新。
    // 【Java 对比】类似"把普通对象包装成 Observable 对象"
    const turn: Turn = reactive({
      action: userAction,
      narrative: '',
      choices: [],
      events: [],
      diagnostics: [],
      turn: turnCount.value + 1,
    })
    currentTurn.value = turn
    // rawContent 分段构建，保持文档顺序（旁白 + 对话交织）
    type RawPart = { kind: 'narr'; text: string } | { kind: 'tag'; text: string }
    const rawParts: RawPart[] = []
    let pendingNarr = ''  // 累积旁白，遇到对话标签时 flush

    // 清空上一回合的选项（玩家已经做了选择，旧选项过时了）
    for (const t of turns.value) t.choices = []
    turns.value.push(turn)
    hooks.onScroll?.()   // ?. 是"可选链"：hooks.onScroll 为 undefined 时不报错

    try {
      const requestId = globalThis.crypto?.randomUUID?.()
        ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`
      // streamTurn 使用 fetch + EventSource 接收 SSE 流，每个事件触发对应回调
      await streamTurn(sessionId, requestId, userAction, {

        // ── 叙事流处理 ──────────────────────────────────
        onNarrative: (text) => {
          turn.narrative += text    // 累积叙事文本（触发响应式更新 → UI 实时显示）
          pendingNarr += text       // 同步追加到 rawContent 旁白缓冲
          hooks.onScroll?.()
        },

        // ── 结构化标签处理 ──────────────────────────────
        onTag: (name, attrs, content) => {
          // say/pc_action：先 flush 待处理旁白，再追加对话标签（保持文档顺序）
          if (name === 'say' || name === 'pc_action') {
            if (pendingNarr) {
              rawParts.push({ kind: 'narr', text: pendingNarr })
              pendingNarr = ''
            }
            if (name === 'say') {
              const speakerAttr = attrs.speaker ? ` speaker="${attrs.speaker}"` : ''
              rawParts.push({ kind: 'tag', text: `<say${speakerAttr}>${content}</say>` })
            } else {
              // Strip leading "#name：" placeholder that some 7B models emit
              const cleaned = content.replace(/^[#□★]\s*[\S]+[：:]\s*/, '').trim() || content
              rawParts.push({ kind: 'tag', text: `<pc_action>${cleaned}</pc_action>` })
            }
          }

          // 记录结构化事件（显示在消息旁边的小图标里）
          const skipForEvents = new Set(['narrative', 'narriative', 'say', 'pc_action', 'choices'])
          if (!skipForEvents.has(name)) {
            let payload: Record<string, any> = { ...attrs }  // 展开属性（... = 解构）
            const trimmed = content.trim()
            if (trimmed) {
              try {
                const parsed = JSON.parse(trimmed)
                // 如果 content 是 JSON 对象，合并到 payload
                if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                  payload = { ...payload, ...parsed }
                } else {
                  payload = { ...payload, value: parsed }
                }
              } catch {
                payload = { ...payload, content: trimmed }  // 不是 JSON，当字符串处理
              }
            }
            turn.events.push({ type: name, payload, content: trimmed || undefined })
          }

          // 各种标签的具体处理逻辑：
          if (name === 'state_change') {
            // 属性变化 → 播放音效 + 更新侧边栏数值
            try {
              const obj = JSON.parse(content)
              let totalDelta = 0
              for (const [, v] of Object.entries(obj)) {
                if (typeof v === 'number') totalDelta += v
              }
              if (totalDelta < 0) audio.playSfx('state_down')   // 属性降低音效
              else if (totalDelta > 0) audio.playSfx('state_up') // 属性提升音效
            } catch { /* ignore */ }
            gs.applyStateChange(content)
          }
          else if (name === 'npc_update') gs.applyNpcUpdate(content)
          else if (name === 'pc_mood') gs.applyPcMood(content)
          else if (name === 'choices') {
            // 解析选项列表（每行一个选项，去掉列表符号）
            const opts: string[] = []
            for (const line of content.split('\n')) {
              const trimmed = line.trim().replace(/^[-*•・·]\s*/, '')
              if (trimmed) opts.push(trimmed)
            }
            turn.choices = opts
          }
          else if (name === 'dice') {
            // 骰子判定 → 播放骰子音效 + 推入侧边栏
            audio.playSfx('dice')

            // v0.9 dice schema is structured XML: content is `<scene>…</scene>
            // <reaction speaker mood>…</reaction>` rather than the v0.8
            // free-form roll string. Strip those tags out of the side-panel
            // result line and prefer the new `pc_roll` / `dc` / `outcome` /
            // `category` attrs when present.
            const stripTags = (s: string) =>
              s.replace(/<scene>[\s\S]*?<\/scene>/gi, '')
               .replace(/<reaction\b[^>]*>[\s\S]*?<\/reaction>/gi, '')
               .replace(/<[^>]+>/g, '')
               .trim()

            const skillLabel = attrs.skill || attrs.category || '判定'
            const targetLabel = attrs.target || attrs.dc || '?'

            // Build a compact result line. Prefer the structured fields:
            // `outcome` (crit_success/success/fail/crit_fail) + `pc_roll`/`mod`
            // give a clean one-line summary. Fall back to the stripped body
            // text for legacy v0.8 emits.
            const outcomeLabel: Record<string, string> = {
              crit_success: '✦ 大成功',
              success: '✓ 成功',
              fail: '✗ 失败',
              crit_fail: '☠ 大失败',
            }
            let resultLine = ''
            if (attrs.pc_roll) {
              const mod = attrs.mod ? ` ${attrs.mod}` : ''
              resultLine = `d20=${attrs.pc_roll}${mod}`
              if (attrs.outcome && outcomeLabel[attrs.outcome]) {
                resultLine += ` ${outcomeLabel[attrs.outcome]}`
              }
            } else {
              resultLine = stripTags(content) || '?'
            }

            gs.pushDice({
              skill: skillLabel,
              target: targetLabel,
              result: resultLine,
              success: attrs.success || undefined,  // 成功后果（可选）
              fail: attrs.fail || undefined,         // 失败后果（可选）
            })
          }
          else if (name === 'plot_event') {
            // 剧情事件 → 加入侧边栏时间线（忽略 importance=1 的琐碎事件）
            let importance = 2
            const parsed = parseInt(attrs.importance ?? '2', 10)
            if (!isNaN(parsed)) importance = Math.max(1, Math.min(3, parsed))
            if (importance >= 2) {
              gs.threads.value.push({
                type: attrs.type ?? 'major_event',
                description: content.trim(),
                importance,
              })
            }
          }
          else if (name === 'narrative_revised') {
            // 可选"润色后"的叙事文本：替换流式版本（如果开启了 narrative_polish）
            const polished = content.trim()
            if (polished) turn.narrative = polished
          }
          else if (name === 'npc_initiative') {
            // NPC 主动出场：通知 GameView 触发 NPC tick（让 NPC 说话）
            hooks.onNpcInitiative?.(attrs.npc ?? '')
          }
          else if (name === 'location_enter') {
            // 玩家进入新地点：通知 GameView 加载场景图和环境音
            hooks.onLocationEnter?.(attrs.name ?? '')
          }
          else if (name === 'bgm') {
            // GM 切换背景音乐情绪：通知 GameView 切换 BGM
            hooks.onBgmChange?.(attrs.mood ?? '')
          }
          else if (name === 'chapter_advance') {
            // 章节推进：通知 GameView 重新加载章节 BGM
            hooks.onChapterAdvance?.()
          }
        },

        onError: (msg) => {
          turn.diagnostics.push(msg)
          // "Unclosed tag" 是正常情况（LLM 有时忘记写闭合标签，后端已容错处理）
          // 只打 debug 日志，不弹错误提示，避免干扰玩家
          if (/unclosed/i.test(msg)) {
            console.debug('[parser]', msg)
            return
          }
          ElMessage.warning(msg)   // 其他错误作为警告弹窗
        },

        onDone: (doneData?: { assistant_msg_id?: number }) => {
          // ── 回合结束的收尾工作 ──────────────────────────
          if (doneData?.assistant_msg_id) {
            turn.msgId = doneData.assistant_msg_id
          }
          turnCount.value += 1

          // GM 有时忘记用 <choices> 标签，直接把选项写在 narrative 里
          // 这里从叙事文本中补救出选项（降级处理）
          if (!turn.choices.length) {
            const leaked = extractChoices(turn.narrative)
            if (leaked.length) turn.choices = leaked
          }

          // 清理叙事文本（移除意外混入的 XML 标签）
          turn.narrative = cleanNarrative(turn.narrative)

          // 检测本回合的场景氛围（用于背景音乐/UI 色调）
          sceneMood.value = detectSceneMood(turn.narrative)

          // 把剩余旁白 flush 进 rawParts（对话全在旁白之后时）
          if (pendingNarr) {
            rawParts.push({ kind: 'narr', text: pendingNarr })
            pendingNarr = ''
          }

          // 构建 rawContent：按文档顺序交织旁白和对话，保持 TTS 播放顺序正确
          if (rawParts.length) {
            turn.rawContent = rawParts
              .map((p) =>
                p.kind === 'narr'
                  ? `<narrative>${p.text}</narrative>`
                  : p.text,
              )
              .join('')
          } else if (turn.narrative) {
            // 降级：没有对话标签时，全部作为旁白（格式崩溃时的兜底）
            turn.rawContent = `<narrative>${turn.narrative}</narrative>`
          }

          refreshTokens()      // 异步刷新 token 统计（fire-and-forget）
          hooks.onTurnDone?.()
        },
      })
    } catch (e: any) {
      if (e instanceof TurnStreamError && e.code === 'event_gap') {
        await recoverTurnFromHistory(turn)
        await hooks.onRecoveryRequired?.()
        return
      }
      ElMessage.error(e.message ?? '请求失败')
      turn.narrative += `\n\n[出错：${e.message ?? '未知错误'}]`
    } finally {
      // finally 块无论成功/失败/异常都会执行（相当于 Java 的 try-finally）
      sending.value = false
      currentTurn.value = null
    }
  }

  async function recoverTurnFromHistory(turn: Turn) {
    const messages = await sessionsApi.messages(sessionId)
    const assistant = [...messages]
      .reverse()
      .find((message) => message.role === 'assistant')
    if (!assistant) return
    turn.narrative = cleanNarrative(assistant.content)
    turn.choices = extractChoices(assistant.content)
    turn.events = assistant.events ?? []
    turn.diagnostics = assistant.diagnostics ?? []
    turn.rawContent = assistant.content
    turn.msgId = assistant.id
    turn.turn = assistant.turn
    turnCount.value = Math.max(turnCount.value, assistant.turn)
  }

  async function refreshTokens() {
    /**
     * 从数据库重新统计 token 用量（仅用于 UI 展示，非关键路径）。
     * 不 await、不 throw，纯后台刷新。
     */
    try {
      const msgs = await sessionsApi.messages(sessionId)
      let ti = 0, to = 0
      for (const m of msgs) {
        if (m.role === 'assistant') {
          ti += m.tokens_in
          to += m.tokens_out
        }
      }
      tokensIn.value = ti
      tokensOut.value = to
    } catch { /* ignore */ }
  }

  // 返回所有外部需要的状态和方法
  // 调用方用解构：const { turns, sending, sendAction } = useGameTurn(...)
  return {
    turns,
    currentTurn,
    turnCount,
    tokensIn,
    tokensOut,
    sending,
    sceneMood,
    sendAction,
    refreshTokens,
  }
}
