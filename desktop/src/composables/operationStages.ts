export const OPERATION_STAGES = [
  'preparing',
  'connecting',
  'generating',
  'applying',
  'completed',
  'failed',
  'cancelled',
  'restored',
] as const

export type OperationStage = (typeof OPERATION_STAGES)[number]

export const OPERATION_STAGE_LABELS: Record<OperationStage, string> = {
  preparing: '准备',
  connecting: '连接模型',
  generating: '生成叙事',
  applying: '状态写入',
  completed: '完成',
  failed: '失败',
  cancelled: '已取消',
  restored: '已恢复',
}

export const OPERATION_STAGE_STEPS = OPERATION_STAGES.filter(
  (stage) => !['failed', 'cancelled', 'restored'].includes(stage),
)

export const OPERATION_CANCELLABLE_STAGES = [
  'preparing',
  'connecting',
  'generating',
] as const satisfies readonly OperationStage[]

export const OPERATION_TERMINAL_STAGES = [
  'completed',
  'failed',
  'cancelled',
  'restored',
] as const satisfies readonly OperationStage[]

export function isOperationStageCancellable(stage: OperationStage) {
  return (OPERATION_CANCELLABLE_STAGES as readonly string[]).includes(stage)
}

export function isOperationStageTerminal(stage: OperationStage) {
  return (OPERATION_TERMINAL_STAGES as readonly string[]).includes(stage)
}
