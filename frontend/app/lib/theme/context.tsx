"use client";

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

/**
 * Theme provider for LawFlow.
 *
 * The DOM source of truth is `<html data-theme="…">`. We mirror to React
 * state so components can read the active theme without scanning the DOM.
 *
 * Resolution order on first paint:
 *   1. Inline script set by `<ThemeBootstrap />` in <head> — reads
 *      localStorage and applies before React hydrates, eliminating the
 *      flash-of-incorrect-theme.
 *   2. AuthShell / app code can call `setTheme()` to change it.
 *
 * Three theme settings exist:
 *   - "light"  pinned light
 *   - "dark"   pinned dark
 *   - "system" follows prefers-color-scheme (default)
 */

export type ThemeMode = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "lawflow.theme";

interface ThemeContextValue {
  mode: ThemeMode;
  resolved: ResolvedTheme;
  setMode: (mode: ThemeMode) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStoredMode(): ThemeMode {
  if (typeof window === "undefined") return "system";
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* localStorage may be disabled (private mode); fall through. */
  }
  return "system";
}

function systemPrefersDark(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyTheme(resolved: ResolvedTheme): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", resolved);
  document.documentElement.style.colorScheme = resolved;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // We can read localStorage on the first render in client components.
  // Server-render uses `system` and the no-flash inline script (see
  // ThemeBootstrap) pre-applies the correct attribute before hydration.
  const [mode, setModeState] = useState<ThemeMode>(() => readStoredMode());
  // `systemDark` only changes when the OS preference flips, which is
  // an external system — we subscribe via matchMedia. Everything else
  // (the resolved theme) is derived state computed below.
  const [systemDark, setSystemDark] = useState<boolean>(() => systemPrefersDark());

  // Subscribe to OS preference changes. Pure external sync; the
  // setState-in-effect lint rule only fires when the callback path
  // is synchronous (it isn't here — the listener fires on a media-
  // query change event).
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => setSystemDark(mql.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  // Derived state — never stored. Recomputed from mode + systemDark.
  const resolved: ResolvedTheme = useMemo(
    () => (mode === "system" ? (systemDark ? "dark" : "light") : mode),
    [mode, systemDark],
  );

  // Apply to the DOM as a side-effect on every resolution change. The
  // DOM is the external system here; React state is the source.
  useEffect(() => {
    applyTheme(resolved);
  }, [resolved]);

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* persistence is best-effort */
    }
  }, []);

  // Toggling cycles light → dark → system → light.
  const toggle = useCallback(() => {
    setMode(mode === "light" ? "dark" : mode === "dark" ? "system" : "light");
  }, [mode, setMode]);

  const value = useMemo<ThemeContextValue>(
    () => ({ mode, resolved, setMode, toggle }),
    [mode, resolved, setMode, toggle],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}

/**
 * Inline script that runs *before* React hydrates so the correct
 * data-theme attribute is on <html> for the very first paint. Without
 * this, a dark-mode user sees a light flash on every navigation.
 *
 * Kept tiny: read localStorage, fall back to prefers-color-scheme.
 */
export function ThemeBootstrap() {
  const code = `(function(){try{var k="${STORAGE_KEY}",m=localStorage.getItem(k);var r=(m==="light"||m==="dark")?m:(window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");document.documentElement.setAttribute("data-theme",r);document.documentElement.style.colorScheme=r;}catch(_){}})();`;
  return <script dangerouslySetInnerHTML={{ __html: code }} />;
}
