import { ref } from 'vue'
import { useAppStore } from '@/stores/app'

export interface UpdateInfo {
  available: boolean
  version?: string
  body?: string
  date?: string
}

export const updateInfo = ref<UpdateInfo>({ available: false })

export function useUpdater() {
  async function checkForUpdates(): Promise<UpdateInfo> {
    const appStore = useAppStore()
    if (!appStore.isTauri) return { available: false }

    try {
      const { check } = await import('@tauri-apps/plugin-updater')
      const result = await check()
      if (result?.available) {
        const info: UpdateInfo = {
          available: true,
          version: result.version,
          body: (result as any).body ?? '',
          date: (result as any).date ?? '',
        }
        updateInfo.value = info
        return info
      }
    } catch (e) {
      // updater 不可用 (web mode / 没装插件 / 网络) 静默跳过
    }
    updateInfo.value = { available: false }
    return { available: false }
  }

  async function downloadAndInstall(): Promise<void> {
    const appStore = useAppStore()
    if (!appStore.isTauri) throw new Error('updater 仅在桌面端可用')

    const { check } = await import('@tauri-apps/plugin-updater')
    const { relaunch } = await import('@tauri-apps/plugin-process')
    const result = await check()
    if (!result?.available) throw new Error('当前已是最新版本')
    await result.downloadAndInstall()
    await relaunch()
  }

  return { checkForUpdates, downloadAndInstall, updateInfo }
}
