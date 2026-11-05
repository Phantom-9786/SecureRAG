"use client";
import { useState, type FormEvent } from "react";
import { api } from "../../lib/api";
import type { AdminOptions, ManagedUser } from "../../lib/admin";
import type { AdminAction } from "./panel";

export default function UsersAdmin({
  users,
  options,
  run,
  busy,
  currentUserId,
}: {
  users: ManagedUser[];
  options: AdminOptions;
  run: AdminAction;
  busy: boolean;
  currentUserId: string;
}) {
  const [method, setMethod] = useState("google");
  const [search, setSearch] = useState("");
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const body = {
      name: data.get("name"),
      email: data.get("email"),
      role_id: data.get("role_id"),
      ...(method === "password" ? { password: data.get("password") } : {}),
    };
    const done = await run(async (me) => {
      await api(method === "google" ? "/users/google" : "/users", {
        method: "POST",
        csrf: me.csrf_token,
        body,
      });
    }, "User created with the selected role.");
    // Do not retain a temporary password after submission, including a failed request.
    const password = form.elements.namedItem("password");
    if (password instanceof HTMLInputElement) password.value = "";
    if (done) form.reset();
  }
  const filtered = users.filter((user) =>
    `${user.name} ${user.email}`.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <div className="admin-section">
      <form className="admin-card admin-form" onSubmit={create}>
        <h3>Add a workspace user</h3>
        <p className="small">
          Provision a user before their first sign-in. Assign the role
          appropriate to their work.
        </p>
        <fieldset disabled={busy}>
          <div className="admin-form-grid">
            <label>
              Full name
              <input name="name" required maxLength={120} autoComplete="off" />
            </label>
            <label>
              Email address
              <input
                name="email"
                type="email"
                required
                maxLength={254}
                autoComplete="off"
              />
            </label>
            <label>
              Role
              <select aria-label="Role" name="role_id" required defaultValue="">
                <option value="" disabled>
                  Choose a role
                </option>
                {options.roles.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Sign-in method
              <select
                aria-label="Sign-in method"
                value={method}
                onChange={(event) => setMethod(event.target.value)}
              >
                <option value="google">Google sign-in</option>
                <option value="password">Password sign-in</option>
              </select>
            </label>
            {method === "password" ? (
              <label className="wide">
                Initial password
                <input
                  name="password"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={12}
                  maxLength={128}
                />
                <small>12–128 characters. Share privately with the user.</small>
              </label>
            ) : (
              <p className="small wide">
                Use the user's exact Gmail or Google Workspace email. Google
                verifies ownership at sign-in; no usable password is issued.
              </p>
            )}
          </div>
          <button className="primary" type="submit">
            Create user
          </button>
        </fieldset>
      </form>
      <div className="admin-card">
        <div className="admin-list-heading">
          <h3>
            Workspace users <span className="count">{users.length}</span>
          </h3>
          <label className="search-label">
            Search users
            <input
              type="search"
              placeholder="Name or email"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
        </div>
        <p className="small">
          Deactivation revokes existing sessions. Reactivation requires a fresh
          login. At least one active administrator must remain.
        </p>
        <div className="managed-users">
          {filtered.length ? (
            filtered.map((user) => (
              <UserRow
                key={`${user.id}-${user.role_id}-${user.is_active}`}
                user={user}
                options={options}
                busy={busy}
                run={run}
                own={user.id === currentUserId}
              />
            ))
          ) : (
            <p className="small">No users match your search.</p>
          )}
        </div>
      </div>
    </div>
  );
}
function UserRow({
  user,
  options,
  busy,
  run,
  own,
}: {
  user: ManagedUser;
  options: AdminOptions;
  busy: boolean;
  run: AdminAction;
  own: boolean;
}) {
  const [role, setRole] = useState(user.role_id);
  const [active, setActive] = useState(user.is_active);
  const changed = role !== user.role_id || active !== user.is_active;
  async function save(event: FormEvent) {
    event.preventDefault();
    await run(async (me) => {
      await api(`/users/${user.id}`, {
        method: "PATCH",
        csrf: me.csrf_token,
        body: { role_id: role, is_active: active },
      });
    }, "User access updated.");
  }
  return (
    <form
      className="managed-user"
      onSubmit={save}
      aria-label={`Manage ${user.email}`}
    >
      <div className="user-details">
        <strong>
          {user.name} {own ? <span className="badge">YOU</span> : null}
        </strong>
        <span>{user.email}</span>
        <small>
          {user.is_active ? "Active" : "Inactive"}
          {own ? " · Changes here can affect your own session." : ""}
        </small>
      </div>
      <label>
        Role for {user.email}
        <select
          aria-label={`Role for ${user.email}`}
          value={role}
          onChange={(event) => setRole(event.target.value)}
          disabled={busy}
        >
          {options.roles.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      <label className="check-label">
        <input
          type="checkbox"
          checked={active}
          onChange={(event) => setActive(event.target.checked)}
          disabled={busy}
        />{" "}
        Active account
      </label>
      <button className="secondary" type="submit" disabled={busy || !changed}>
        Save user
      </button>
    </form>
  );
}
