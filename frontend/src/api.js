/* api.js — thin re-export of the shared API core (src/shared/api.ts).
   Unwraps the backend's error envelope and carries the optional bearer token.
   This file used to hold the implementation directly; it now delegates so
   the same auth/error contract is used by both this vanilla surface and the
   React Pipeline Island (src/react/lib/api.ts) instead of two independent
   copies. Every existing call site (`import { api } from "../api.js"`,
   `authToken()`, `tokenized()`, `setProjectHeader()`) is unchanged. */

export { authToken, tokenized, setProjectHeader, currentProject, projectScoped, apiFetch as api } from "./shared/api";
