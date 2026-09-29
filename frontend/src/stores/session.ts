//
// Session store: the access token, the signed-in user, sign-in and
// sign-out.  Store layer.
//
// The access token lives in memory only.  The refresh token is an
// httpOnly cookie the server sets on sign-in; the browser sends it on
// `POST /api/token/refresh/` without JS ever reading it.
//
// `createSessionHttpClient()` builds the HTTP client wired to this
// store: requests carry `accessToken`, a 401 runs `renewToken()` (once
// for all concurrent requests), and a failed refresh ends the session
// (`endSession()`) before the caller's `onAuthFailure` runs --
// `main.ts` uses that to send the user to the login page with a
// return path.
//
// `endSession()` resets every store (see `stores/reset.ts`).
// `logout()` first asks the server to revoke the refresh cookie, then
// ends the session.
//

// 3rd party imports
//
import { defineStore, getActivePinia } from "pinia";
import { computed, ref } from "vue";

// app imports
//
import { api, getHttp } from "@/api";
import type { AuthError } from "@/api/errors";
import type { HttpClient } from "@/api/http";
import { createHttpClient } from "@/api/http";
import { resetAllStores } from "@/stores/reset";
import type { User, UserUpdate } from "@/models/user";
import { DEFAULT_TIMEZONE, userFromDto, userToUpdateDto } from "@/models/user";

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export const useSessionStore = defineStore("session", () => {
  const pinia = getActivePinia();

  ////////////////////////////////////////////////////////////////////
  //
  const accessToken = ref<string | null>(null);
  const user = ref<User | null>(null);

  const isAuthenticated = computed(() => accessToken.value !== null);
  // The profile timezone, used for every date shown.
  const timezone = computed(() => user.value?.timezone ?? DEFAULT_TIMEZONE);

  ////////////////////////////////////////////////////////////////////
  //
  // Exchange email + password for an access token.  Rejects with
  // `ApiError(401)` on bad credentials.
  //
  async function login(email: string, password: string): Promise<void> {
    const data = await api.auth.obtainToken(email, password);
    accessToken.value = data.access;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // One refresh attempt against the server; the HTTP client calls this
  // through its single-flight `refresh()`.  A failure clears the token
  // and user.
  //
  async function renewToken(): Promise<boolean> {
    try {
      const data = await api.auth.refreshToken();
      accessToken.value = data.access;
      return true;
    } catch {
      accessToken.value = null;
      user.value = null;
      return false;
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Silent refresh through the HTTP client, shared with any refresh a
  // 401 already started.  `main.ts` calls this on cold boot.
  //
  function refresh(): Promise<boolean> {
    return getHttp().refresh();
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Load the current user once; concurrent callers share one request
  // and later callers get the cached user unless `force` is set.
  // Resolves to `null` when the profile cannot be loaded.
  //
  let userLoad: Promise<User | null> | null = null;

  function loadUser(force = false): Promise<User | null> {
    if (!force && user.value) return Promise.resolve(user.value);
    if (!force && userLoad) return userLoad;
    const load = api.users
      .me()
      .then((dto) => {
        if (userLoad === load) user.value = userFromDto(dto);
        return user.value;
      })
      .catch(() => null)
      .finally(() => {
        if (userLoad === load) userLoad = null;
      });
    userLoad = load;
    return load;
  }

  ////////////////////////////////////////////////////////////////////
  //
  async function updateProfile(update: UserUpdate): Promise<User> {
    const updated = userFromDto(
      await api.users.updateMe(userToUpdateDto(update)),
    );
    user.value = updated;
    return updated;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // End the session in this tab: forget the token and reset every
  // store.
  //
  function endSession(): void {
    if (pinia) resetAllStores(pinia);
    else reset();
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Sign out: revoke the refresh cookie on the server, then end the
  // session.  The server call is best-effort; the session ends even
  // when it fails.
  //
  async function logout(): Promise<void> {
    try {
      await api.auth.logout();
    } catch {
      // The cookie outlives a failed call; there is nothing to retry.
    }
    endSession();
  }

  ////////////////////////////////////////////////////////////////////
  //
  function reset(): void {
    accessToken.value = null;
    user.value = null;
    userLoad = null;
  }

  return {
    accessToken,
    user,
    isAuthenticated,
    timezone,
    login,
    renewToken,
    refresh,
    loadUser,
    updateProfile,
    endSession,
    logout,
    reset,
  };
});

////////////////////////////////////////////////////////////////////////
//
export interface SessionHttpOptions {
  baseUrl?: string;
  // Runs after the session has been ended by a failed refresh.
  onAuthFailure?: (err: AuthError) => void;
}

////////////////////////////////////////////////////////////////////////
//
// The HTTP client for the active Pinia's session.  Call with a Pinia
// active (after `app.use(pinia)` or `setActivePinia`).
//
export function createSessionHttpClient(
  options: SessionHttpOptions = {},
): HttpClient {
  const session = useSessionStore();
  return createHttpClient({
    baseUrl: options.baseUrl,
    getToken: () => session.accessToken,
    refresh: () => session.renewToken(),
    onAuthFailure: (err) => {
      session.endSession();
      options.onAuthFailure?.(err);
    },
  });
}
