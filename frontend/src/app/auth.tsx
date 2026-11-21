/**
 * Session handling. The access token is kept in memory only; the refresh token is an HttpOnly,
 * SameSite=Strict cookie scoped to /api/auth. Refresh rotation has reuse detection on the server, so
 * concurrent refreshes are coalesced into one request (React StrictMode runs effects twice).
 */
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiError, createApiClient, type ApiClient, type AuthBridge } from "../api/client";
import * as endpoints from "../api/endpoints";
import type { TokenResponse, User } from "../api/types";

type Status = "loading" | "anonymous" | "authenticated";

interface SessionState {
  status: Status;
  user: User | null;
  /** The server ended a live session (refresh rejected). */
  expired: boolean;
}

const REFRESH_MARGIN_S = 60;

/** Owns the token, the single in-flight refresh and the proactive refresh timer (outside React). */
class SessionManager implements AuthBridge {
  readonly anonymous: ApiClient;
  readonly api: ApiClient;
  private access: string | null = null;
  private inflight: Promise<string | null> | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private listener: ((state: SessionState) => void) | null = null;

  constructor(fetchImpl?: typeof fetch) {
    this.anonymous = createApiClient({ token: () => null, refresh: () => Promise.resolve(null) }, fetchImpl);
    this.api = createApiClient(this, fetchImpl);
  }

  token = (): string | null => this.access;

  subscribe(listener: (state: SessionState) => void): () => void {
    this.listener = listener;
    return () => {
      if (this.listener === listener) this.listener = null;
    };
  }

  refresh = (): Promise<string | null> => {
    this.inflight ??= endpoints
      .refreshSession(this.anonymous)
      .then((session) => {
        this.accept(session);
        return session.access_token;
      })
      .catch((error: unknown) => {
        const hadSession = this.access !== null;
        this.clear();
        this.listener?.({
          status: "anonymous",
          user: null,
          expired: hadSession && error instanceof ApiError && error.status === 401,
        });
        return null;
      })
      .finally(() => {
        this.inflight = null;
      });
    return this.inflight;
  };

  async signIn(email: string, password: string): Promise<User> {
    const session = await endpoints.login(this.anonymous, email, password);
    this.accept(session);
    return session.user;
  }

  async signOut(): Promise<void> {
    try {
      await endpoints.logout(this.anonymous);
    } finally {
      this.clear();
      this.listener?.({ status: "anonymous", user: null, expired: false });
    }
  }

  dispose(): void {
    this.stopTimer();
  }

  private accept(session: TokenResponse): void {
    this.access = session.access_token;
    this.stopTimer();
    const delay = Math.max(session.expires_in - REFRESH_MARGIN_S, 15) * 1000;
    this.timer = setTimeout(() => void this.refresh(), delay);
    this.listener?.({ status: "authenticated", user: session.user, expired: false });
  }

  private clear(): void {
    this.access = null;
    this.stopTimer();
  }

  private stopTimer(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }
}

interface AuthValue {
  status: Status;
  user: User | null;
  api: ApiClient;
  signIn: (email: string, password: string) => Promise<User>;
  signOut: () => Promise<void>;
  sessionExpired: boolean;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children, fetchImpl }: { children: ReactNode; fetchImpl?: typeof fetch }) {
  const queryClient = useQueryClient();
  const [session] = useState(() => new SessionManager(fetchImpl));
  const [state, setState] = useState<SessionState>({ status: "loading", user: null, expired: false });

  useEffect(() => {
    const unsubscribe = session.subscribe(setState);
    void session.refresh();
    return () => {
      unsubscribe();
      session.dispose();
    };
  }, [session]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      queryClient.clear();
      return session.signIn(email, password);
    },
    [session, queryClient],
  );

  const signOut = useCallback(async () => {
    await session.signOut();
    queryClient.clear();
  }, [session, queryClient]);

  const value = useMemo(
    () => ({
      status: state.status,
      user: state.user,
      api: session.api,
      signIn,
      signOut,
      sessionExpired: state.expired,
    }),
    [state, session, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}

export function useApi(): ApiClient {
  return useAuth().api;
}

export function useCan(): { contribute: boolean; admin: boolean } {
  const role = useAuth().user?.role;
  return { contribute: role === "admin" || role === "analyst", admin: role === "admin" };
}
