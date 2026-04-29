import { createRouter, createWebHashHistory } from 'vue-router'
import LayoutView from '@/views/LayoutView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      component: LayoutView,
      children: [
        { path: '', redirect: '/sessions' },
        { path: 'models', name: 'models', component: () => import('@/views/ModelsView.vue') },
        { path: 'worlds', name: 'worlds', component: () => import('@/views/WorldsView.vue') },
        { path: 'characters', name: 'characters', component: () => import('@/views/CharactersView.vue') },
        { path: 'sessions', name: 'sessions', component: () => import('@/views/SessionsView.vue') },
        { path: 'play/:id', name: 'play', component: () => import('@/views/GameView.vue'), props: true },
        { path: 'play/:id/journal', name: 'journal',
          component: () => import('@/views/JournalView.vue'), props: true },
        { path: 'play/:id/npcs', name: 'npcs',
          component: () => import('@/views/NpcsView.vue'), props: true },
      ],
    },
  ],
})

export default router
