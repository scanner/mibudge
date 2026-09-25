//
// Vue Router configuration.  Router layer.
//
// History mode with base `/app/`: Django serves the SPA shell for every
// path under `/app/`, and Vue Router renders the matching view.  All
// in-app navigation goes by route name (`{ name: "budget-detail",
// params: { id } }`); names, paths and params are typed in
// `router/types.ts`.
//
// Every route declares `meta.access`.  The global guard sends a
// signed-out visitor on an `authenticated` route to the login page
// with `?next=<path>`, and sends a signed-in user away from the login
// page.  Routes with an `:id` param pass it to the view as a prop
// (`props: true`); views watch it, so reusing the route with a new id
// reloads.  Unknown paths render `NotFoundView`.
//

// 3rd party imports
//
import { createRouter, createWebHistory } from "vue-router";
import type { RouteLocationNormalized, RouteRecordRaw, Router, RouterHistory } from "vue-router";

// app imports
//
import type { AppRouteName, RouteAccess } from "@/router/types";
import { useSessionStore } from "@/stores/session";

export type { AppRouteName, RouteAccess } from "@/router/types";

////////////////////////////////////////////////////////////////////////
//
// A route record with its name and access level spelled out.
//
type AppRouteRecord = RouteRecordRaw & { name: AppRouteName; meta: { access: RouteAccess } };

const PUBLIC = { access: "public" } as const;
const AUTHENTICATED = { access: "authenticated" } as const;

////////////////////////////////////////////////////////////////////////
//
export const routes: AppRouteRecord[] = [
  {
    path: "/login/",
    name: "login",
    component: () => import("@/views/LoginView.vue"),
    meta: PUBLIC,
  },
  {
    path: "/",
    name: "overview",
    component: () => import("@/views/OverviewView.vue"),
    meta: AUTHENTICATED,
  },
  {
    path: "/budgets/",
    name: "budgets",
    component: () => import("@/views/BudgetsView.vue"),
    meta: AUTHENTICATED,
  },
  {
    path: "/budgets/create/",
    name: "budget-create",
    component: () => import("@/views/BudgetCreateView.vue"),
    meta: AUTHENTICATED,
  },
  {
    path: "/budgets/:id/",
    name: "budget-detail",
    component: () => import("@/views/BudgetDetailView.vue"),
    props: true,
    meta: AUTHENTICATED,
  },
  {
    path: "/transactions/",
    name: "transactions",
    component: () => import("@/views/TransactionsView.vue"),
    meta: AUTHENTICATED,
  },
  {
    path: "/transactions/:id/",
    name: "transaction-detail",
    component: () => import("@/views/TransactionDetailView.vue"),
    props: true,
    meta: AUTHENTICATED,
  },
  {
    path: "/account/",
    name: "account",
    component: () => import("@/views/AccountView.vue"),
    meta: AUTHENTICATED,
  },
  {
    path: "/account/profile/",
    name: "user-profile",
    component: () => import("@/views/UserProfileView.vue"),
    meta: AUTHENTICATED,
  },
  {
    path: "/account/settings/",
    name: "account-settings",
    component: () => import("@/views/AccountSettingsView.vue"),
    meta: AUTHENTICATED,
  },
  {
    path: "/account/bank-accounts/create/",
    name: "bank-account-create",
    component: () => import("@/views/BankAccountCreateView.vue"),
    meta: AUTHENTICATED,
  },
  {
    path: "/account/bank-accounts/:id/",
    name: "bank-account-detail",
    component: () => import("@/views/BankAccountDetailView.vue"),
    props: true,
    meta: AUTHENTICATED,
  },
  // Email-change result pages, reached from links in emails.  Paths
  // must match the SPA_EMAIL_CHANGE_* constants in users/email_change.py.
  {
    path: "/email-change/confirmed/",
    name: "email-change-confirmed",
    component: () => import("@/views/EmailChangeConfirmedView.vue"),
    meta: PUBLIC,
  },
  {
    path: "/email-change/revoked/",
    name: "email-change-revoked",
    component: () => import("@/views/EmailChangeRevokedView.vue"),
    meta: PUBLIC,
  },
  {
    path: "/email-change/error/",
    name: "email-change-error",
    component: () => import("@/views/EmailChangeErrorView.vue"),
    meta: PUBLIC,
  },
  {
    path: "/:pathMatch(.*)*",
    name: "not-found",
    component: () => import("@/views/NotFoundView.vue"),
    meta: PUBLIC,
  },
];

////////////////////////////////////////////////////////////////////////
//
// The auth guard, run on every navigation.
//
export function authGuard(to: RouteLocationNormalized) {
  const session = useSessionStore();
  if (to.meta.access !== "public" && !session.isAuthenticated) {
    return { name: "login" as const, query: { next: to.fullPath } };
  }
  if (to.name === "login" && session.isAuthenticated) {
    return { name: "overview" as const };
  }
  return true;
}

////////////////////////////////////////////////////////////////////////
//
// Send the user to the login page with the current path as `next`, so
// signing in again returns them there.  The HTTP client calls this when
// the session ends (a refresh failed).
//
export function redirectToLogin(router: Router): Promise<unknown> {
  const current = router.currentRoute.value;
  if (current.meta.access === "public") return Promise.resolve();
  return router.replace({ name: "login", query: { next: current.fullPath } });
}

////////////////////////////////////////////////////////////////////////
//
// A router with the app's routes and auth guard.  The app uses browser
// history under `/app/`; tests pass a memory history.
//
export function createAppRouter(history: RouterHistory = createWebHistory("/app/")): Router {
  const router = createRouter({ history, routes });
  router.beforeEach(authGuard);
  return router;
}
