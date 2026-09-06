/** A retriable action captures its source Run and cannot cross a Run boundary. */
export function shouldResetRetriableAction(previousRunId: string | undefined, nextRunId: string) {
  return previousRunId !== nextRunId
}
