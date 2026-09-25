//
// `useSignOut`: end the session and go to the login page.  Feature
// composable (auth).
//
// `session.logout()` resets every store, so nothing of this user's
// data remains for the next person to sign in on this tab.
//

// 3rd party imports
//
import { useRouter } from "vue-router";

// app imports
//
import { useSessionStore } from "@/stores/session";

////////////////////////////////////////////////////////////////////////
//
export function useSignOut() {
  const session = useSessionStore();
  const router = useRouter();

  async function signOut(): Promise<void> {
    session.logout();
    await router.push({ name: "login" });
  }

  return { signOut };
}
