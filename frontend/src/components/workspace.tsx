"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  api,
  allPages,
  ApiError,
  type Profile,
  type Conversation,
  type Message,
  type Document,
  type Answer,
} from "../lib/api";
import Login from "./login";
import MessageView from "./message";
import AdminPanel from "./admin/panel";
import { managementTabs } from "../lib/admin";

export default function Workspace() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [checking, setChecking] = useState(true);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [view, setView] = useState<"chat" | "documents" | "admin">("chat");
  const [adminBusy, setAdminBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState("auto");
  const [model, setModel] = useState("");
  const sequence = useRef(0);
  const mutation = useRef(false);
  const end = useRef<HTMLDivElement>(null);
  const currentUserId = useRef<string | null>(null);

  const acceptProfile = useCallback((me: Profile) => {
    if (currentUserId.current && currentUserId.current !== me.user.id) {
      // A different account signed in in another tab: discard the previous account's UI.
      sequence.current++;
      setMessages([]);
      setConversations([]);
      setDocuments([]);
      setActive(null);
      setDraft("");
      setModel("");
      setMode("auto");
      setView("chat");
      setError("");
      setNotice("");
      setAdminBusy(false);
    }
    currentUserId.current = me.user.id;
    setProfile(me);
  }, []);

  const clearSession = useCallback(
    (reason = "Your session ended. Please sign in again.") => {
      sequence.current++;
      currentUserId.current = null;
      setProfile(null);
      setMessages([]);
      setConversations([]);
      setDocuments([]);
      setActive(null);
      setDraft("");
      setModel("");
      setMode("auto");
      setLoading(false);
      setAdminBusy(false);
      setError("");
      setNotice(reason);
    },
    [],
  );
  const report = useCallback(
    (cause: unknown) => {
      if (cause instanceof ApiError && cause.status === 401) clearSession();
      else
        setError(
          cause instanceof Error
            ? cause.message
            : "Something went wrong. Try again.",
        );
    },
    [clearSession],
  );

  useEffect(() => {
    const controller = new AbortController();
    api<Profile>("/auth/me", { signal: controller.signal })
      .then(acceptProfile)
      .catch((cause) => {
        if (cause instanceof ApiError && cause.status !== 401)
          setNotice(cause.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setChecking(false);
      });
    return () => controller.abort();
  }, [acceptProfile]);

  const refresh = useCallback(async () => {
    const request = ++sequence.current;
    setLoading(true);
    setMessages([]);
    // A fresh server read rechecks grants and masks revoked historical answers.
    try {
      const me = await api<Profile>("/auth/me");
      if (request !== sequence.current) return;
      if (currentUserId.current !== me.user.id) {
        acceptProfile(me);
        return;
      }
      const [chats, docs, history] = await Promise.all([
        allPages<Conversation>("/conversations"),
        allPages<Document>("/documents"),
        active
          ? allPages<Message>(`/conversations/${active}/messages`)
          : Promise.resolve([]),
      ]);
      if (request !== sequence.current) return;
      acceptProfile(me);
      setConversations(chats);
      setDocuments(docs);
      setMessages(history);
    } catch (cause) {
      if (request === sequence.current) {
        setDocuments([]);
        report(cause);
      }
    } finally {
      if (request === sequence.current) setLoading(false);
    }
  }, [active, report, acceptProfile]);

  useEffect(() => {
    if (!profile?.user.id || sending) return;
    void refresh();
    const onVisible = () => {
      if (document.visibilityState === "visible" && !mutation.current)
        void refresh();
    };
    const onHidden = () => {
      if (document.visibilityState === "hidden") {
        sequence.current++;
        setMessages([]);
        setDocuments([]);
      } else onVisible();
    };
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onHidden);
    return () => {
      sequence.current++;
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onHidden);
    };
  }, [profile?.user.id, refresh, sending]);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  function newChat() {
    sequence.current++;
    setActive(null);
    setMessages([]);
    setDraft("");
    setModel("");
    setView("chat");
    setError("");
    setLoading(false);
  }
  async function send(event: FormEvent) {
    event.preventDefault();
    const question = draft.trim();
    if (!profile || !question || mutation.current || loading) return;
    if (new TextEncoder().encode(question).length > 2500) {
      setError(
        "Question is too long. Please keep it within 2,500 UTF-8 bytes.",
      );
      return;
    }
    mutation.current = true;
    setSending(true);
    setError("");
    sequence.current++;
    try {
      // Refresh CSRF/profile before a mutation; never persist the session in browser storage.
      const me = await api<Profile>("/auth/me");
      if (currentUserId.current !== me.user.id) {
        acceptProfile(me);
        return;
      }
      let conversationId = active;
      if (!conversationId) {
        const chat = await api<Conversation>("/conversations", {
          method: "POST",
          body: {},
          csrf: me.csrf_token,
        });
        conversationId = chat.id;
        // Keep the ID immediately so a failed answer can retry in the same conversation.
        setActive(chat.id);
      }
      const answer = await api<Answer>(
        `/conversations/${conversationId}/messages`,
        {
          method: "POST",
          csrf: me.csrf_token,
          body: { question, model_mode: mode },
        },
      );
      setDraft("");
      setModel(answer.model === "none" ? "" : answer.model);
      // Re-fetch history rather than trusting a cached answer after permissions change.
      acceptProfile(me);
    } catch (cause) {
      report(cause);
    } finally {
      mutation.current = false;
      setSending(false);
      setLoading(false);
    }
  }
  async function logout() {
    if (!profile || mutation.current) return;
    mutation.current = true;
    setSigningOut(true);
    setError("");
    try {
      await api<void>("/auth/logout", {
        method: "POST",
        csrf: profile.csrf_token,
      });
      clearSession("You have signed out.");
    } catch (cause) {
      report(cause);
    } finally {
      mutation.current = false;
      setSigningOut(false);
    }
  }

  if (checking)
    return (
      <main className="session-check" role="status">
        ◈ Checking your session…
      </main>
    );
  if (!profile)
    return (
      <Login
        notice={notice}
        onLogin={(me) => {
          acceptProfile(me);
          setNotice("");
          setView("chat");
        }}
      />
    );
  const current = conversations.find((chat) => chat.id === active);
  const disabled = sending || signingOut || adminBusy;
  const canManage = managementTabs.some((item) =>
    profile.permissions.includes(item.permission),
  );
  return (
    <div className="workspace">
      <aside className="sidebar" aria-label="Workspace navigation">
        <a className="brand" href="/">
          ◈ <span>SecureRAG</span>
        </a>
        <span className="workspace-label">KNOWLEDGE WORKSPACE</span>
        <button
          className="new-chat"
          onClick={newChat}
          disabled={disabled || loading}
        >
          ＋ New conversation
        </button>
        <nav aria-label="Main">
          <button
            className={view === "chat" ? "nav-item selected" : "nav-item"}
            onClick={() => setView("chat")}
            disabled={disabled}
          >
            ◷ Conversations
          </button>
          <button
            className={view === "documents" ? "nav-item selected" : "nav-item"}
            onClick={() => setView("documents")}
            disabled={disabled}
          >
            ▤ Documents <span>{documents.length}</span>
          </button>
          {canManage ? (
            <button
              className={view === "admin" ? "nav-item selected" : "nav-item"}
              disabled={disabled}
              onClick={() => setView("admin")}
            >
              ⚙ Administration
            </button>
          ) : null}
        </nav>
        <div className="recent-heading">RECENT CONVERSATIONS</div>
        <div className="recent-list">
          {conversations.length ? (
            conversations.map((chat) => (
              <button
                key={chat.id}
                title={chat.title}
                aria-current={active === chat.id ? "true" : undefined}
                className={
                  active === chat.id ? "chat-link selected" : "chat-link"
                }
                disabled={disabled}
                onClick={() => {
                  if (active === chat.id) void refresh();
                  else {
                    setMessages([]);
                    setActive(chat.id);
                  }
                  setView("chat");
                  setModel("");
                }}
              >
                {chat.title}
              </button>
            ))
          ) : (
            <p className="small">Your conversations will appear here.</p>
          )}
        </div>
        <div className="account">
          <div className="avatar">
            {profile.user.name.slice(0, 1).toUpperCase()}
          </div>
          <div>
            <strong>{profile.user.name}</strong>
            <span>{profile.role.name}</span>
          </div>
          <button
            aria-label="Sign out"
            title="Sign out"
            onClick={logout}
            disabled={disabled}
          >
            ↪
          </button>
        </div>
      </aside>
      <main className="main-panel">
        <header className="topbar">
          <div>
            <span className="breadcrumb">
              WORKSPACE /{" "}
              {view === "admin"
                ? "ADMINISTRATION"
                : view === "chat"
                  ? "ASSISTANT"
                  : "LIBRARY"}
            </span>
            <h1>
              {view === "admin"
                ? "Administration"
                : view === "documents"
                  ? "Your documents"
                  : (current?.title ?? "New conversation")}
            </h1>
          </div>
          {view !== "admin" ? (
            <button
              className="quiet"
              onClick={() => void refresh()}
              disabled={disabled || loading}
            >
              {loading ? "Refreshing…" : "↻ Refresh"}
            </button>
          ) : null}
        </header>
        {error ? (
          <div role="alert" className="error workspace-error">
            {error}{" "}
            <button onClick={() => setError("")} aria-label="Dismiss error">
              ×
            </button>
          </div>
        ) : null}
        {view === "admin" ? (
          <AdminPanel
            profile={profile}
            key={profile.user.id}
            onProfile={acceptProfile}
            onExpired={clearSession}
            onBusy={setAdminBusy}
            onChanged={() => void refresh()}
            locked={signingOut || sending}
          />
        ) : view === "documents" ? (
          <section className="library">
            <p className="muted">
              Documents available to your role. Downloads are checked each time
              you open them.
            </p>
            {loading ? (
              <p role="status">Loading documents…</p>
            ) : documents.length ? (
              <div className="document-grid">
                {documents.map((doc) => (
                  <a
                    className="document-card"
                    key={doc.id}
                    href={`/api/v1/documents/${doc.id}/file`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <span className="file-icon">PDF</span>
                    <span className="badge">
                      {profile.categories.find(
                        (cat) => cat.id === doc.category_id,
                      )?.name ?? "Document"}
                    </span>
                    <h2>{doc.title}</h2>
                    <p>{doc.original_filename}</p>
                    <span className="document-action">Download original ↗</span>
                  </a>
                ))}
              </div>
            ) : (
              <div className="empty-library">
                <span>▤</span>
                <h2>No documents available yet</h2>
                <p>Your administrator can publish documents for your role.</p>
              </div>
            )}
          </section>
        ) : (
          <>
            <div className="chat-scroll" aria-busy={loading || sending}>
              {loading && !sending ? (
                <p className="loading-text" role="status">
                  Loading your conversation…
                </p>
              ) : messages.length ? (
                <div className="messages">
                  {messages.map((message) => (
                    <MessageView key={message.id} message={message} />
                  ))}
                </div>
              ) : !sending ? (
                <section className="welcome">
                  <div className="welcome-mark">◈</div>
                  <p className="eyebrow">YOUR WORKSPACE ASSISTANT</p>
                  <h2>What would you like to know?</h2>
                  <p>
                    Turn your company documents into answers.
                    <br />
                    Every answer stays within your access.
                  </p>
                  <div className="suggestions">
                    {[
                      "Summarize the key points in the available documents",
                      "What processes do the documents describe?",
                      "Compare the guidance across available documents",
                    ].map((text, i) => (
                      <button key={text} onClick={() => setDraft(text)}>
                        <span>{["↗", "≡", "⇄"][i]}</span>
                        {
                          [
                            "Get a clear summary",
                            "Understand a process",
                            "Compare information",
                          ][i]
                        }
                        <small>{text}</small>
                      </button>
                    ))}
                  </div>
                </section>
              ) : null}
              {sending ? (
                <p className="thinking" role="status">
                  ◈ Finding a source-backed answer…
                </p>
              ) : null}
              <div ref={end} />
            </div>
            <div className="composer-area">
              <div className="access-line">
                <span className="status-dot" /> Access:{" "}
                {profile.categories.map((cat) => cat.name).join(" · ") ||
                  "No categories assigned"}
              </div>
              <form className="composer" onSubmit={send}>
                <label className="sr-only" htmlFor="question">
                  Ask your documents
                </label>
                <textarea
                  id="question"
                  placeholder="Ask a question about your documents…"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  maxLength={2000}
                  rows={2}
                  disabled={disabled || loading}
                />
                <div className="composer-bottom">
                  <label htmlFor="model">Model</label>
                  <select
                    id="model"
                    aria-label="Model"
                    value={mode}
                    onChange={(event) => setMode(event.target.value)}
                    disabled={disabled}
                  >
                    <option value="auto">Auto · recommended</option>
                    <option value="basic">Basic</option>
                    <option value="advanced">Advanced</option>
                  </select>
                  <button
                    className="send-button"
                    type="submit"
                    disabled={disabled || loading || !draft.trim()}
                  >
                    {sending ? "Working…" : "Send ↑"}
                  </button>
                </div>
              </form>
              <p className="composer-note">
                Ask a self-contained question. Verify important details in the
                cited documents.{model ? ` · ${model}` : ""}
              </p>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
