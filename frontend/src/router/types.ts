//
// Route typing for the SPA.  Router layer.
//
// - `RouteMeta.access` says whether a route needs a session.
// - `RouteNamedMap` lists every named route with its path and params,
//   so `router.push({ name, params })` and `<router-link :to>` are
//   type-checked: a misspelt name or a missing param fails `vue-tsc`.
// Add a route here and to `routes` in `router/index.ts` together.
//

// 3rd party imports
//
import type { RouteRecordInfo } from "vue-router";

////////////////////////////////////////////////////////////////////////
//
// `public`: reachable signed out (sign-in, email-change result pages,
// not-found).  `authenticated`: the guard sends signed-out visitors to
// the login page with a return path.
//
export type RouteAccess = "public" | "authenticated";

type NoParams = Record<never, never>;
type IdParam = { id: string | number };
type IdParamNormalized = { id: string };

////////////////////////////////////////////////////////////////////////
//
export interface AppRouteNamedMap {
  login: RouteRecordInfo<"login", "/login/", NoParams, NoParams>;
  overview: RouteRecordInfo<"overview", "/", NoParams, NoParams>;
  budgets: RouteRecordInfo<"budgets", "/budgets/", NoParams, NoParams>;
  "budget-create": RouteRecordInfo<"budget-create", "/budgets/create/", NoParams, NoParams>;
  "budget-detail": RouteRecordInfo<"budget-detail", "/budgets/:id/", IdParam, IdParamNormalized>;
  transactions: RouteRecordInfo<"transactions", "/transactions/", NoParams, NoParams>;
  "transaction-detail": RouteRecordInfo<
    "transaction-detail",
    "/transactions/:id/",
    IdParam,
    IdParamNormalized
  >;
  account: RouteRecordInfo<"account", "/account/", NoParams, NoParams>;
  "user-profile": RouteRecordInfo<"user-profile", "/account/profile/", NoParams, NoParams>;
  "account-settings": RouteRecordInfo<"account-settings", "/account/settings/", NoParams, NoParams>;
  "bank-account-create": RouteRecordInfo<
    "bank-account-create",
    "/account/bank-accounts/create/",
    NoParams,
    NoParams
  >;
  "bank-account-detail": RouteRecordInfo<
    "bank-account-detail",
    "/account/bank-accounts/:id/",
    IdParam,
    IdParamNormalized
  >;
  "email-change-confirmed": RouteRecordInfo<
    "email-change-confirmed",
    "/email-change/confirmed/",
    NoParams,
    NoParams
  >;
  "email-change-revoked": RouteRecordInfo<
    "email-change-revoked",
    "/email-change/revoked/",
    NoParams,
    NoParams
  >;
  "email-change-error": RouteRecordInfo<
    "email-change-error",
    "/email-change/error/",
    NoParams,
    NoParams
  >;
  "not-found": RouteRecordInfo<
    "not-found",
    "/:pathMatch(.*)*",
    { pathMatch: string | string[] },
    { pathMatch: string | string[] }
  >;
}

export type AppRouteName = keyof AppRouteNamedMap;

////////////////////////////////////////////////////////////////////////
//
declare module "vue-router" {
  interface RouteMeta {
    access?: RouteAccess;
  }

  interface TypesConfig {
    RouteNamedMap: AppRouteNamedMap;
  }
}
