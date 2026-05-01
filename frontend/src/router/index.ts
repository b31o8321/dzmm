import { createRouter, createWebHashHistory } from 'vue-router'
import LayoutView from '@/views/LayoutView.vue'
import { useAppStore } from '@/stores/app'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/welcome',
      name: 'welcome',
      component: () => import('@/views/WelcomeView.vue'),
    },
    {
      path: '/',
      component: LayoutView,
      children: [
        { path: '', redirect: '/sessions' },
        { path: 'models', name: 'models', component: () => import('@/views/ModelsView.vue') },
        { path: 'worlds', name: 'worlds', component: () => import('@/views/WorldsView.vue') },
        { path: 'characters', name: 'characters', component: () => import('@/views/CharactersView.vue') },
        { path: 'sessions', name: 'sessions', component: () => import('@/views/SessionsView.vue') },
        { path: 'sessions/wizard', name: 'session-wizard',
          component: () => import('@/views/WizardView.vue') },
        { path: 'sessions/generate/:id', name: 'session-generate',
          component: () => import('@/views/SessionGenerateView.vue'), props: true },
        { path: 'play/:id', name: 'play', component: () => import('@/views/GameView.vue'), props: true },
        { path: 'play/:id/journal', name: 'journal',
          component: () => import('@/views/JournalView.vue'), props: true },
        { path: 'play/:id/npcs', name: 'npcs',
          component: () => import('@/views/NpcsView.vue'), props: true },
        { path: 'play/:id/relations', name: 'relations',
          component: () => import('@/views/RelationsView.vue'), props: true },
{ path: 'play/:id/screenplay', name: 'screenplay',
          component: () => import('@/views/ScreenplayView.vue'), props: true },
        { path: 'help', name: 'help', component: () => import('@/views/HelpView.vue') },
        { path: 'settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
        { path: 'debug', name: 'debug', component: () => import('@/views/DebugView.vue') },
      ],
    },
  ],
})

// First-launch guard: if the user hasn't completed (or started) the
// onboarding tour, redirect them to /welcome on their initial visit.
router.beforeEach((to, _from, next) => {
  if (to.path === '/welcome') {
    next()
    return
  }
  try {
    const appStore = useAppStore()
    if (!appStore.tourCompleted && appStore.tourStep === 0) {
      next('/welcome')
      return
    }
  } catch {
    /* pinia not ready yet, fall through */
  }
  next()
})

export default router
