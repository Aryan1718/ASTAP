import { createClient, SupportedStorage } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;
const storagePreferenceKey = "astsp:remember-session";

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error("Missing Supabase client configuration");
}

function resolveStorage() {
  if (typeof window === "undefined") {
    return null;
  }

  const remember = window.localStorage.getItem(storagePreferenceKey) !== "false";
  return remember ? window.localStorage : window.sessionStorage;
}

const browserStorage: SupportedStorage = {
  getItem(key) {
    return resolveStorage()?.getItem(key) ?? null;
  },
  setItem(key, value) {
    resolveStorage()?.setItem(key, value);
  },
  removeItem(key) {
    window.localStorage.removeItem(key);
    window.sessionStorage.removeItem(key);
  },
};

export function setRememberSession(enabled: boolean) {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(storagePreferenceKey, enabled ? "true" : "false");
  }
}

export function getRememberSession() {
  if (typeof window === "undefined") {
    return true;
  }

  return window.localStorage.getItem(storagePreferenceKey) !== "false";
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    autoRefreshToken: true,
    persistSession: true,
    detectSessionInUrl: true,
    storage: browserStorage,
  },
});
