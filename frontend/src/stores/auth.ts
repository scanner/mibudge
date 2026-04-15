//
// Auth store — owns the JWT access token and the refresh flow.
//
// The access token lives in memory only (never localStorage or a cookie that
// JS can read).  The refresh token is an httpOnly cookie managed by the
// server; the browser sends it automatically on POST /api/token/refresh/
// without JS ever touching it.
//
// On cold boot, main.ts calls refresh() -- if the refresh cookie is still
// valid the SPA becomes authenticated before the first router guard runs;
// otherwise the guard redirects to /app/login/.
//

// 3rd party imports
//
import { defineStore } from "pinia";
import { computed, ref } from "vue";

// app imports
//
import { apiFetch, authFetch, ApiError, AuthError } from "@/api/client";
import type { User } from "@/types/api";

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
interface TokenResponse {
  access: string;
}

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export const useAuthStore = defineStore("auth", () => {
  ////////////////////////////////////////////////////////////////////
  //
  const accessToken = ref<string | null>(null);
  const user = ref<User | null>(null);

  const isAuthenticated = computed(() => accessToken.value !== null);

  ////////////////////////////////////////////////////////////////////
  //
  function clear() {
    accessToken.value = null;
    user.value = null;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Exchange username + password for an access token.  The backend
  // also sets the httpOnly refresh cookie on the response, so nothing
  // else is needed here.  Throws ApiError(401) on bad credentials.
  //
  async function login(username: string, password: string): Promise<void> {
    const data = await authFetch<TokenResponse>("/token/", null, {
      method: "POST",
      body: { username, password } as unknown as BodyInit,
    });
    accessToken.value = data.access;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Fetch the current user and cache it on the store.  Safe to call
  // more than once; `force` re-fetches if the cache is already warm.
  //
  async function loadUser(force = false): Promise<User | null> {
    if (!force && user.value) return user.value;
    try {
      const me = await request<User>("/users/me/");
      user.value = me;
      return me;
    } catch {
      return null;
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Attempt a silent token refresh using the httpOnly refresh cookie.
  // Returns true on success, false if the session has fully expired.
  //
  async function refresh(): Promise<boolean> {
    try {
      const data = await authFetch<TokenResponse>("/token/refresh/", null, {
        method: "POST",
      });
      accessToken.value = data.access;
      return true;
    } catch {
      clear();
      return false;
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Authenticated API request with automatic one-shot 401 → refresh → retry.
  //
  async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
    try {
      return await apiFetch<T>(url, accessToken.value, options);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        const ok = await refresh();
        if (ok) return apiFetch<T>(url, accessToken.value, options);
        // Refresh also failed — session is gone.
        throw new AuthError();
      }
      throw err;
    }
  }

  return {
    accessToken,
    user,
    isAuthenticated,
    clear,
    refresh,
    login,
    loadUser,
    request,
  };
});
