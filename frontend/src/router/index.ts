//
// Vue Router configuration.
//
// History mode with base /app/ — the server serves the SPA shell at /app/*
// and returns index.html for any path under it.  All navigation within the
// SPA uses pushState; the server never sees sub-routes.
//

// 3rd party imports
//
import { createRouter, createWebHistory } from 'vue-router'

// app imports
//
import HomeView from '@/views/HomeView.vue'

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
const router = createRouter({
  history: createWebHistory('/app/'),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
    },
  ],
})

export default router
