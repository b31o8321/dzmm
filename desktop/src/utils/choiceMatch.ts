/** 自由行动输入与章节选项标签的匹配引导（评分提升计划③）。 */

export interface ChoiceLike {
  id: string
  label: string
}

function normalizeLabel(value: string): string {
  return value
    .replace(/[\s，。！？：；、“”‘’'"「」·,.:;!?()（）-]/g, '')
    .toLowerCase()
}

/**
 * 当自由文本与某个可用选项标签指向同一行动时返回该选项，
 * 让 UI 引导玩家直接点击选项（走状态机安全的 choices 通道）。
 * 匹配规则：规范化后相等，或一方完整包含另一方（≥4 个有效字符）。
 */
export function matchChoiceByInput(
  input: string,
  choices: ChoiceLike[],
): ChoiceLike | null {
  const normalized = normalizeLabel(input)
  if (normalized.length < 2) return null
  for (const choice of choices) {
    const label = normalizeLabel(choice.label)
    if (!label) continue
    if (label === normalized) return choice
    if (normalized.length >= 4 && label.includes(normalized)) return choice
    if (label.length >= 4 && normalized.includes(label)) return choice
  }
  return null
}
