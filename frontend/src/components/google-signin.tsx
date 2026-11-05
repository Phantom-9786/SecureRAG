"use client";

import Script from "next/script";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Profile } from "../lib/api";

type GoogleSdk = {
  initialize(config: {
    client_id: string;
    nonce: string;
    auto_select: boolean;
    ux_mode: "popup";
    callback: (response: { credential: string }) => void;
  }): void;
  renderButton(
    element: HTMLElement,
    config: {
      type: "standard";
      theme: "outline";
      size: "large";
      text: "continue_with";
      width: number;
    },
  ): void;
  cancel(): void;
};
declare global {
  interface Window {
    google?: { accounts: { id: GoogleSdk } };
  }
}

export default function GoogleSignIn({
  onLogin,
  disabled,
  begin,
  finish,
}: {
  onLogin: (profile: Profile) => void;
  disabled: boolean;
  begin: () => boolean;
  finish: () => void;
}) {
  const [clientId, setClientId] = useState<string | null>(null);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [preparing, setPreparing] = useState(false);
  const [version, setVersion] = useState(0);
  const container = useRef<HTMLDivElement>(null);
  const callbacks = useRef({ onLogin, begin, finish });
  useEffect(() => {
    callbacks.current = { onLogin, begin, finish };
  }, [onLogin, begin, finish]);

  useEffect(() => {
    const controller = new AbortController();
    api<{ enabled: boolean; client_id: string | null }>("/auth/google/config", {
      signal: controller.signal,
    })
      .then((config) => {
        setConfigured(config.enabled);
        setClientId(config.client_id);
      })
      .catch((cause) => {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error
              ? cause.message
              : "Google sign-in is unavailable.",
          );
      });
    return () => controller.abort();
  }, [version]);

  const exchange = useCallback(async (credential: string) => {
    if (!callbacks.current.begin()) return;
    setError("");
    try {
      const profile = await api<Profile>("/auth/google", {
        method: "POST",
        body: { credential },
      });
      callbacks.current.onLogin(profile);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Google sign-in failed.",
      );
      setVersion((value) => value + 1);
    } finally {
      callbacks.current.finish();
    }
  }, []);

  useEffect(() => {
    if (!ready || !clientId || !container.current) return;
    const controller = new AbortController();
    const element = container.current;
    element.replaceChildren();
    setPreparing(true);
    api<{ nonce: string }>("/auth/google/challenge", {
      method: "POST",
      signal: controller.signal,
    })
      .then(({ nonce }) => {
        if (controller.signal.aborted || !window.google) return;
        window.google.accounts.id.initialize({
          client_id: clientId,
          nonce,
          auto_select: false,
          ux_mode: "popup",
          callback: (response) => {
            if (!controller.signal.aborted) void exchange(response.credential);
          },
        });
        window.google.accounts.id.renderButton(element, {
          type: "standard",
          theme: "outline",
          size: "large",
          text: "continue_with",
          width: 320,
        });
      })
      .catch((cause) => {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error
              ? cause.message
              : "Google sign-in is unavailable.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setPreparing(false);
      });
    // Refresh the short-lived nonce before it expires; tokens are never stored locally.
    const timer = window.setTimeout(
      () => setVersion((value) => value + 1),
      240_000,
    );
    return () => {
      controller.abort();
      window.clearTimeout(timer);
      element.replaceChildren();
    };
  }, [ready, clientId, exchange, version]);

  return (
    <div className="google-signin">
      {clientId ? (
        <Script
          src="https://accounts.google.com/gsi/client"
          strategy="afterInteractive"
          onReady={() => setReady(true)}
          onError={() =>
            setError(
              "Google sign-in could not load. Check your connection or use your password.",
            )
          }
        />
      ) : null}
      <div
        ref={container}
        className={disabled ? "google-button blocked" : "google-button"}
        inert={disabled}
        aria-busy={preparing}
      />
      {configured === false ? (
        <>
          <button type="button" className="google-unavailable" disabled>
            Continue with Google
          </button>
          <p className="small">Google sign-in is not enabled yet.</p>
        </>
      ) : null}
      {(configured === null || preparing || (clientId && !ready)) && !error ? (
        <p className="small" role="status">
          Preparing Google sign-in…
        </p>
      ) : null}
      {error ? (
        <p className="error" role="alert">
          {error}{" "}
          <button
            type="button"
            onClick={() => {
              if (clientId && !ready) {
                window.location.reload();
                return;
              }
              setError("");
              setVersion((value) => value + 1);
            }}
          >
            Retry
          </button>
        </p>
      ) : null}
      <div className="login-divider">
        <span>or use your password</span>
      </div>
    </div>
  );
}
