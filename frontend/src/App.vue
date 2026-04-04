<script setup lang="ts">
//
// Root application component.
//
// Intentionally minimal — layout, navigation, and page content all live in
// views and child components.  RouterView renders whatever the current route
// resolves to.
//

// 3rd party imports
//
import { RouterView } from 'vue-router'
</script>

<template>
  <RouterView />
</template>
