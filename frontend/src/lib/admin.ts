export type Named = { id: string; name: string };
export type ManagedUser = {
  id: string;
  name: string;
  email: string;
  role_id: string;
  is_active: boolean;
  created_at: string;
};
export type ManagedRole = Named & {
  category_ids: string[];
  permission_ids: string[];
};
export type ManagedDocument = {
  id: string;
  title: string;
  original_filename: string;
  category_id: string;
  active: boolean;
  ingestion_status: "processing" | "ready" | "failed";
  created_at: string;
};
export type AdminOptions = {
  roles: Named[];
  categories: Named[];
  permissions: { id: string; code: string }[];
  max_upload_mb: number;
};
export type AdminTab = "documents" | "users" | "roles";
export const managementTabs = [
  {
    id: "documents" as const,
    permission: "documents.manage",
    label: "Documents",
  },
  { id: "users" as const, permission: "users.manage", label: "Users" },
  { id: "roles" as const, permission: "roles.manage", label: "Roles & access" },
];
