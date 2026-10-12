/**
 * The plan page's backend client. Unlike the app's default `api`, a 401 does not send the
 * browser away: the page keeps the last known state on screen and offers the link to sign in
 * again, which brings the user back here (spec, "Tutti gli stati sono disegnati": "Sessione
 * scaduta: il link per accedere di nuovo, che riporta qui").
 */

import { createApiClient, type ApiClient } from "@/lib/api";

export const liveApi: ApiClient = createApiClient({ onUnauthorized: () => {} });
