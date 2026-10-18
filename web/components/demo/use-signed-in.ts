"use client";

import { useSyncExternalStore } from "react";

import { SIGNED_IN_KEY } from "@/lib/returning";

const subscribe = () => () => {};

function readMark(): boolean {
  try {
    return localStorage.getItem(SIGNED_IN_KEY) === "1";
  } catch {
    return false;
  }
}

/** Whether this browser has signed in before (lib/returning.ts): the demo then asks it to plan a
 * trip, and asks anyone else to sign in, since Atlas is by invitation. False on the server. */
export function useSignedIn(): boolean {
  return useSyncExternalStore(subscribe, readMark, () => false);
}
