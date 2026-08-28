/** The projects seam. The store already owns the wire types and every call, so this
 *  re-exports rather than restating them — a second declaration of `Project` here
 *  would be a second source of truth for a shape the backend defines. */

export type { Project, ProjectRepo } from "~/lib/stores/projects";
