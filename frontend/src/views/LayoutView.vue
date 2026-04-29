<script setup lang="ts">
import SidebarNav from '@/components/SidebarNav.vue'
</script>

<template>
  <div class="flex h-full">
    <SidebarNav />
    <main class="flex-1 overflow-auto bg-slate-50">
      <router-view />
    </main>
  </div>
</template>
