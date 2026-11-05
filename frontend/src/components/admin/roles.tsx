"use client";
import { useState, type FormEvent } from "react";
import { api } from "../../lib/api";
import type { AdminOptions, ManagedRole } from "../../lib/admin";
import type { AdminAction } from "./panel";

export default function RolesAdmin({
  roles,
  options,
  run,
  busy,
  currentRoleId,
}: {
  roles: ManagedRole[];
  options: AdminOptions;
  run: AdminAction;
  busy: boolean;
  currentRoleId: string;
}) {
  const [selected, setSelected] = useState(roles[0]?.id ?? "");
  const role = roles.find((item) => item.id === selected);
  return (
    <div className="admin-section">
      <div className="admin-card">
        <h3>Roles & access</h3>
        <p className="small">
          Category access controls which documents a role can retrieve.
          Management permissions control which administration tools it can use.
          Saving replaces the role's full grant selection.
        </p>
        <label className="role-picker">
          Choose role
          <select
            aria-label="Choose role"
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            disabled={busy}
          >
            {roles.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {role ? (
        <RoleEditor
          key={`${role.id}-${role.category_ids.join()}-${role.permission_ids.join()}`}
          role={role}
          options={options}
          run={run}
          busy={busy}
          own={role.id === currentRoleId}
        />
      ) : null}
    </div>
  );
}
function RoleEditor({
  role,
  options,
  run,
  busy,
  own,
}: {
  role: ManagedRole;
  options: AdminOptions;
  run: AdminAction;
  busy: boolean;
  own: boolean;
}) {
  const [categories, setCategories] = useState(role.category_ids);
  const [permissions, setPermissions] = useState(role.permission_ids);
  function toggle(values: string[], id: string) {
    return values.includes(id)
      ? values.filter((value) => value !== id)
      : [...values, id];
  }
  const changed =
    [...categories].sort().join() !== [...role.category_ids].sort().join() ||
    [...permissions].sort().join() !== [...role.permission_ids].sort().join();
  async function save(event: FormEvent) {
    event.preventDefault();
    await run(async (me) => {
      await api(`/roles/${role.id}/grants`, {
        method: "PUT",
        csrf: me.csrf_token,
        body: { category_ids: categories, permission_ids: permissions },
      });
    }, `Access grants updated for ${role.name}.`);
  }
  return (
    <form className="admin-card admin-form" onSubmit={save}>
      <h3>{role.name} access</h3>
      {own ? (
        <p className="notice small">
          You currently use this role. Removing management permissions can
          remove your access to this panel.
        </p>
      ) : null}
      <div className="grant-grid">
        <fieldset disabled={busy}>
          <legend>Document categories</legend>
          {options.categories.map((item) => (
            <label className="grant-option" key={item.id}>
              <input
                type="checkbox"
                checked={categories.includes(item.id)}
                onChange={() => setCategories(toggle(categories, item.id))}
              />
              <span>{item.name}</span>
            </label>
          ))}
          <p className="small">{categories.length} categories selected</p>
        </fieldset>
        <fieldset disabled={busy}>
          <legend>Management permissions</legend>
          {options.permissions.map((item) => (
            <label className="grant-option" key={item.id}>
              <input
                type="checkbox"
                checked={permissions.includes(item.id)}
                onChange={() => setPermissions(toggle(permissions, item.id))}
              />
              <span>
                {(
                  {
                    "users.manage": "Manage users",
                    "roles.manage": "Manage roles & access",
                    "documents.manage": "Upload & manage documents",
                  } as Record<string, string>
                )[item.code] ?? item.code}
                <small>{item.code}</small>
              </span>
            </label>
          ))}
          <p className="small">{permissions.length} permissions selected</p>
        </fieldset>
      </div>
      <div className="grant-summary">
        <strong>Saving for: {role.name}</strong>
        <p>
          Categories:{" "}
          {options.categories
            .filter((item) => categories.includes(item.id))
            .map((item) => item.name)
            .join(", ") || "None"}
        </p>
        <p>
          Management:{" "}
          {options.permissions
            .filter((item) => permissions.includes(item.id))
            .map((item) => item.code)
            .join(", ") || "None"}
        </p>
      </div>
      <button className="primary" disabled={busy || !changed} type="submit">
        Save role access
      </button>
      <p className="small">
        The backend protects the last active administrator and applies new
        grants on subsequent requests.
      </p>
    </form>
  );
}
