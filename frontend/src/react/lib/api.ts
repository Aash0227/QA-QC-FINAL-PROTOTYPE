/** Typed client for the pipeline backend contract — thin re-export of the
 *  shared API core (src/shared/api.ts), which also backs the vanilla
 *  dashboard's src/api.js. Both surfaces now share one auth/error/fetch
 *  implementation instead of two independent copies. */

export {
  authToken, tokenized, ApiError, pipelineApi as api,
  setProjectHeader, currentProject, projectScoped,
} from "../../shared/api";
