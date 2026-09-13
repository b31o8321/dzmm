/** AI 创作草案的置灰原因判定：置灰必须伴随用户可读的原因文案。 */

export function draftGateReason(profileCount: number, aiModelProfileId: string): string | null {
  if (profileCount === 0) {
    return '还没有可用的模型档案：先到 设置 → 本地模型 添加一个（填 Base URL 和模型名即可），或展开下方内联表单直接创建。'
  }
  if (!aiModelProfileId) {
    return '在上方选择一个已配置的模型档案后即可生成。'
  }
  return null
}
