//
// `useLogin`: the sign-in form.  Feature composable (auth).
//
// On success it loads the user and the account context (sharing one
// `/users/me/` request), then replaces the login route with the path
// in `?next=`, or the overview.  A 401 means bad credentials; any
// other failure gets a generic retry message.
//

// 3rd party imports
//
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

// app imports
//
import { isApiError } from "@/api/errors";
import { useAccountContextStore } from "@/stores/accountContext";
import { useSessionStore } from "@/stores/session";

////////////////////////////////////////////////////////////////////////
//
export function useLogin() {
  const session = useSessionStore();
  const ctx = useAccountContextStore();
  const router = useRouter();
  const route = useRoute();

  const email = ref("");
  const password = ref("");
  const submitting = ref(false);
  const errorMessage = ref<string | null>(null);

  async function submit(): Promise<void> {
    errorMessage.value = null;
    submitting.value = true;
    try {
      await session.login(email.value, password.value);
      await Promise.all([session.loadUser(), ctx.init(true)]);
      const next =
        typeof route.query.next === "string" ? route.query.next : null;
      void router.replace(next ?? { name: "overview" });
    } catch (err) {
      errorMessage.value = isApiError(err, 401)
        ? "Incorrect email or password."
        : "Unable to sign in. Please try again.";
    } finally {
      submitting.value = false;
    }
  }

  return { email, password, submitting, errorMessage, submit };
}
