/** User management feature data contracts. */

export type UserStatus = "active" | "disabled";

export type Privilege =
  | "memory"
  | "skills"
  | "documents"
  | "email"
  | "calendar"
  | "rag"
  | "uploads"
  | "gallery"
  | "code";

export interface ManagedUser {
  id: string;
  name: string;
  isAdmin: boolean;
  lastActiveAt: string;
  privileges: Privilege[];
  status: UserStatus;
}

export const ALL_PRIVILEGES: Privilege[] = [
  "memory",
  "skills",
  "documents",
  "email",
  "calendar",
  "rag",
  "uploads",
  "gallery",
  "code",
];

/** Short, plain-language explanation of what each privilege grants. */
export const PRIVILEGE_LEGEND: Record<Privilege, string> = {
  memory: "Read and write persistent memory facts the assistant learns.",
  skills: "Install and run agent skills and tools.",
  documents: "Open, edit, and manage workspace documents.",
  email: "Read and send email through connected accounts.",
  calendar: "View and create calendar events.",
  rag: "Query and ingest the retrieval knowledge base.",
  uploads: "Upload files into the workspace.",
  gallery: "View and manage generated images.",
  code: "Execute shell and Python code via the sandbox.",
};
