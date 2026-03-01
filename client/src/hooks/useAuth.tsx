import type { Session } from "@supabase/supabase-js";
import { ReactNode, createContext, useContext, useEffect, useMemo, useState } from "react";

import { getRememberSession, setRememberSession, supabase } from "../lib/supabaseClient";

type AuthContextValue = {
  session: Session | null;
  loading: boolean;
  rememberSession: boolean;
  userEmail: string | null;
  signIn: (email: string, password: string, remember: boolean) => Promise<void>;
  signUp: (email: string, password: string, remember: boolean) => Promise<{ requiresEmailConfirmation: boolean }>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [rememberSessionState, setRememberSessionState] = useState(getRememberSession());

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setLoading(false);
    });

    return () => subscription.unsubscribe();
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      loading,
      rememberSession: rememberSessionState,
      userEmail: session?.user.email ?? null,
      async signIn(email, password, remember) {
        setRememberSession(remember);
        setRememberSessionState(remember);
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) {
          throw error;
        }
      },
      async signUp(email, password, remember) {
        setRememberSession(remember);
        setRememberSessionState(remember);
        const { data, error } = await supabase.auth.signUp({ email, password });
        if (error) {
          throw error;
        }

        return { requiresEmailConfirmation: !data.session };
      },
      async signOut() {
        const { error } = await supabase.auth.signOut();
        if (error) {
          throw error;
        }
      },
    }),
    [loading, rememberSessionState, session]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }

  return context;
}
