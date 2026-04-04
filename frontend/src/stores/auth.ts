//
// Auth store — owns the JWT access token and the refresh flow.
//
// The access token lives in memory only (never localStorage or a cookie that
// JS can read).  The refresh token is an httpOnly cookie managed by the
// server; the browser sends it automatically on POST /api/token/refresh/
// without JS ever touching it.
//
// On SPA load, the web server app injects the initial access token as
// window.__INITIAL_TOKEN__ in the page HTML.  main.ts reads it once,
// stores it here, and removes it from the DOM.
//

// 3rd party imports
//
import { defineStore } from 'pinia'
import { ref } from 'vue'

// app imports
//
import { apiFetch, ApiError, AuthError } from '@/api/client'

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
interface TokenResponse {
  access: string
}

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export const useAuthStore = defineStore('auth', () => {
  ////////////////////////////////////////////////////////////////////
  //
  const accessToken = ref<string | null>(null)

  ////////////////////////////////////////////////////////////////////
  //
  // Initialise the token from window.__INITIAL_TOKEN__ if present.
  // Called once from main.ts immediately after the store is available.
  //
  function init() {
    const w = window as Window & { __INITIAL_TOKEN__?: string }
    if (w.__INITIAL_TOKEN__) {
      accessToken.value = w.__INITIAL_TOKEN__
      // Remove from the DOM so the token is not readable after page load.
      delete w.__INITIAL_TOKEN__
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  function clear() {
    accessToken.value = null
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Attempt a silent token refresh using the httpOnly refresh cookie.
  // Returns true on success, false if the session has fully expired.
  //
  async function refresh(): Promise<boolean> {
    try {
      const data = await apiFetch<TokenResponse>('/token/refresh/', null, {
        method: 'POST',
      })
      accessToken.value = data.access
      return true
    } catch {
      clear()
      return false
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Authenticated API request with automatic one-shot 401 → refresh → retry.
  //
  async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
    try {
      return await apiFetch<T>(url, accessToken.value, options)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        const ok = await refresh()
        if (ok) return apiFetch<T>(url, accessToken.value, options)
        // Refresh also failed — session is gone.
        throw new AuthError()
      }
      throw err
    }
  }

  return { accessToken, init, clear, refresh, request }
})
