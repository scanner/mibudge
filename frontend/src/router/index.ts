//
// Vue Router configuration.
//
// History mode with base /app/ — the server serves the SPA shell at
// /app/* and returns index.html for any path under it.  All navigation
// within the SPA uses pushState; the server never sees sub-routes.
//
// Route meta:
//   public: true  — no auth required (LoginView only).
// Every other route is authenticated.  The global beforeEach guard
// sends unauthenticated visitors to /login/ with a `next` query
// param, and kicks already-authenticated visitors off the login page.
//

// 3rd party imports
//
import { createRouter, createWebHistory } from "vue-router";
import type { RouteRecordRaw } from "vue-router";

// app imports
//
import { useAuthStore } from "@/stores/auth";

////////////////////////////////////////////////////////////////////////
//
const routes: RouteRecordRaw[] = [
  {
    path: "/login/",
    name: "login",
    component: () => import("@/views/LoginView.vue"),
    meta: { public: true },
  },
  {
    path: "/",
    name: "overview",
    component: () => import("@/views/OverviewView.vue"),
  },
  {
    path: "/budgets/",
    name: "budgets",
    component: () => import("@/views/BudgetsView.vue"),
  },
  {
    path: "/budgets/create/",
    name: "budget-create",
    component: () => import("@/views/BudgetCreateView.vue"),
  },
  {
    path: "/budgets/:id/",
    name: "budget-detail",
    component: () => import("@/views/BudgetDetailView.vue"),
    props: true,
  },
  {
    path: "/transactions/",
    name: "transactions",
    component: () => import("@/views/TransactionsView.vue"),
  },
  {
    path: "/transactions/:id/",
    name: "transaction-detail",
    component: () => import("@/views/TransactionDetailView.vue"),
    props: true,
  },
  {
    path: "/account/",
    name: "account",
    component: () => import("@/views/AccountView.vue"),
  },
  {
    path: "/account/profile/",
    name: "user-profile",
    component: () => import("@/views/UserProfileView.vue"),
  },
  {
    path: "/account/bank-accounts/create/",
    name: "bank-account-create",
    component: () => import("@/views/BankAccountCreateView.vue"),
  },
  {
    path: "/account/bank-accounts/:id/",
    name: "bank-account-detail",
    component: () => import("@/views/BankAccountDetailView.vue"),
    props: true,
  },
];

////////////////////////////////////////////////////////////////////////
//
const router = createRouter({
  history: createWebHistory("/app/"),
  routes,
});

////////////////////////////////////////////////////////////////////////
//
// Auth guard.  Runs on every navigation.
//
// On an unauthenticated visit to a protected route, redirect to the
// login view with `?next=` so we can send the user back where they
// wanted to go.  If an authenticated user hits /login/, bounce them
// to the overview so the back button doesn't leave them stranded on
// a dead sign-in page.
//
router.beforeEach((to) => {
  const auth = useAuthStore();
  const isPublic = to.meta.public === true;
  if (!isPublic && !auth.isAuthenticated) {
    return { path: "/login/", query: { next: to.fullPath } };
  }
  if (to.path === "/login/" && auth.isAuthenticated) {
    return { path: "/" };
  }
  return true;
});

export default router;
