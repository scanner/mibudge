//
// `useSignOut`: end the session and go to the login page.  Feature
// composable (auth).
//
// `session.logout()` revokes the refresh cookie on the server, so a
// reload does not sign the user back in, and resets every store, so
// nothing of this user's data remains for the next person to sign in
// on this tab.  It finishes before the login page opens, so its
// cookie-clearing answer cannot land after a new sign-in.
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
    await session.logout();
    await router.push({ name: "login" });
  }

  return { signOut };
}
