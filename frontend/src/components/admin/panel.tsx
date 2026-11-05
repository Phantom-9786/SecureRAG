"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, allPages, ApiError, type Profile } from "../../lib/api";
import {
  managementTabs,
  type AdminTab,
  type AdminOptions,
  type ManagedDocument,
  type ManagedRole,
  type ManagedUser,
} from "../../lib/admin";
import DocumentsAdmin from "./documents";
import UsersAdmin from "./users";
import RolesAdmin from "./roles";

export type AdminAction = (
  work: (current: Profile) => Promise<void>,
  success: string,
) => Promise<boolean>;
export default function AdminPanel({
  profile,
  onProfile,
  onExpired,
  onBusy,
  onChanged,
  locked,
}: {
  profile: Profile;
  onProfile: (profile: Profile) => void;
  onExpired: () => void;
  onBusy: (value: boolean) => void;
  onChanged: () => void;
  locked: boolean;
}) {
  const tabs = managementTabs.filter((item) =>
    profile.permissions.includes(item.permission),
  );
  const [tab, setTab] = useState<AdminTab>(tabs[0]?.id ?? "documents");
  const [options, setOptions] = useState<AdminOptions | null>(null);
  const [documents, setDocuments] = useState<ManagedDocument[]>([]);
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [roles, setRoles] = useState<ManagedRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const sequence = useRef(0);
  const lock = useRef(false);
  const permissions = profile.permissions.join("|");
  const clear = useCallback(() => {
    setOptions(null);
    setDocuments([]);
    setUsers([]);
    setRoles([]);
  }, []);
  const load = useCallback(async () => {
    if (lock.current) return;
    const request = ++sequence.current;
    setLoading(true);
    try {
      const me = await api<Profile>("/auth/me");
      if (request !== sequence.current) return;
      if (me.user.id !== profile.user.id) {
        clear();
        onProfile(me);
        return;
      }
      onProfile(me);
      const allowed = managementTabs.filter((item) =>
        me.permissions.includes(item.permission),
      );
      if (!allowed.some((item) => item.id === tab)) {
        clear();
        if (allowed[0]) setTab(allowed[0].id);
        return;
      }
      const [choices, docs, accounts, grants] = await Promise.all([
        api<AdminOptions>("/admin/options"),
        tab === "documents"
          ? allPages<ManagedDocument>("/admin/documents")
          : Promise.resolve([]),
        tab === "users" ? allPages<ManagedUser>("/users") : Promise.resolve([]),
        tab === "roles" ? api<ManagedRole[]>("/roles") : Promise.resolve([]),
      ]);
      if (request !== sequence.current) return;
      setOptions(choices);
      setDocuments(docs);
      setUsers(accounts);
      setRoles(grants);
    } catch (cause) {
      if (request !== sequence.current) return;
      clear();
      if (cause instanceof ApiError && cause.status === 401) onExpired();
      else
        setError(
          cause instanceof Error
            ? cause.message
            : "Could not load administration.",
        );
    } finally {
      if (request === sequence.current) setLoading(false);
    }
  }, [tab, clear, onProfile, onExpired, profile.user.id]);

  useEffect(() => {
    void load();
    const refresh = () => {
      if (document.visibilityState === "visible" && !lock.current) void load();
    };
    const visibility = () => {
      if (document.visibilityState === "hidden" && !lock.current) {
        sequence.current++;
        setLoading(true);
      } else refresh();
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      sequence.current++;
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [load, clear, permissions]);

  const run: AdminAction = async (work, message) => {
    if (lock.current || locked) return false;
    lock.current = true;
    sequence.current++;
    setBusy(true);
    onBusy(true);
    setError("");
    setSuccess("");
    let done = false;
    let accountChanged = false;
    try {
      const me = await api<Profile>("/auth/me");
      if (me.user.id !== profile.user.id) {
        accountChanged = true;
        clear();
        onProfile(me);
        return false;
      }
      onProfile(me);
      await work(me);
      setSuccess(message);
      done = true;
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        accountChanged = true;
        onExpired();
      } else
        setError(
          cause instanceof Error
            ? cause.message
            : "The change could not be saved. Refresh before retrying.",
        );
    } finally {
      lock.current = false;
      setBusy(false);
      onBusy(false);
      if (!accountChanged) await load();
    }
    if (done) onChanged();
    return done;
  };
  if (!tabs.length)
    return (
      <section className="admin-panel">
        <h2>Administration unavailable</h2>
        <p>Your current role does not have management permissions.</p>
      </section>
    );
  return (
    <section className="admin-panel" aria-busy={busy || loading} inert={locked}>
      <div className="admin-heading">
        <div>
          <span className="badge">WORKSPACE ADMINISTRATION</span>
          <h2>Manage your knowledge workspace</h2>
          <p>Control who has access and which documents are available.</p>
        </div>
        <button
          className="secondary"
          disabled={busy || loading}
          onClick={() => {
            setError("");
            void load();
          }}
        >
          ↻ Refresh admin data
        </button>
      </div>
      <nav className="admin-tabs" aria-label="Administration sections">
        {tabs.map((item) => (
          <button
            key={item.id}
            aria-current={tab === item.id ? "page" : undefined}
            className={tab === item.id ? "active" : ""}
            disabled={busy}
            onClick={() => {
              if (item.id === tab) {
                void load();
                return;
              }
              clear();
              setLoading(true);
              setTab(item.id);
              setError("");
              setSuccess("");
            }}
          >
            {item.label}
          </button>
        ))}
      </nav>
      {error ? (
        <p role="alert" className="error">
          {error}
        </p>
      ) : null}
      {success ? (
        <p role="status" className="admin-success">
          {success}
        </p>
      ) : null}
      {busy ? (
        <p role="status" className="small">
          {tab === "documents"
            ? "Saving your change. PDF indexing can take a few minutes…"
            : "Saving your change…"}
        </p>
      ) : null}
      {loading ? (
        <p role="status" className="small">
          Loading current management data…
        </p>
      ) : null}
      {options ? (
        <div hidden={loading}>
          {tab === "documents" ? (
            <DocumentsAdmin
              documents={documents}
              options={options}
              run={run}
              busy={busy}
            />
          ) : null}
          {tab === "users" ? (
            <UsersAdmin
              users={users}
              options={options}
              run={run}
              busy={busy}
              currentUserId={profile.user.id}
            />
          ) : null}
          {tab === "roles" ? (
            <RolesAdmin
              roles={roles}
              options={options}
              run={run}
              busy={busy}
              currentRoleId={profile.role.id}
            />
          ) : null}
        </div>
      ) : !loading ? (
        <p className="small">Refresh to load current permissions and data.</p>
      ) : null}
    </section>
  );
}
