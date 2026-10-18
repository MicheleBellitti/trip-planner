/**
 * The API client, imported the first time something calls it: the default loaders of the shared
 * plan components (PlanView's Trip, the covers) go through here, so a page that brings its own
 * data (the demo) never evaluates `lib/api`. One import, shared by every caller.
 */
import type { ApiClient } from "./api";

let pending: Promise<ApiClient> | null = null;

export function lazyApi(): Promise<ApiClient> {
  pending ??= import("./api").then((module) => module.api);
  return pending;
}
