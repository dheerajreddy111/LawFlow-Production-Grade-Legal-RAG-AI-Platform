"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";

import { AuthField } from "../components/auth/AuthField";
import { AuthShell } from "../components/auth/AuthShell";
import { AuthSubmit } from "../components/auth/AuthSubmit";
import { AuthError, useAuth } from "../lib/auth/context";

// useSearchParams reads request-bound state, which forces this subtree out
// of the static prerender unless it's inside a Suspense boundary. The
// outer page component is the boundary so the surrounding AuthShell + brand
// chrome can still be statically generated.
export default function LoginPage() {
  return (
    <Suspense fallback={<LoginShellFallback />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginShellFallback() {
  return (
    <AuthShell title="Welcome back" subtitle="Loading sign-in…">
      <div className="h-24 animate-pulse rounded-lg bg-slate-100" />
    </AuthShell>
  );
}

function LoginForm() {
  const router = useRouter();
  const search = useSearchParams();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    setPending(true);
    setFormError(null);
    try {
      const session = await login({ email: email.trim(), password });
      const next = search.get("next");
      // Admins logging in through the user form still land on the requested
      // route — admin-only redirect happens only from /admin/login.
      const target =
        next && next.startsWith("/") && !next.startsWith("//")
          ? next
          : session.user.role === "admin"
          ? "/admin"
          : "/";
      router.replace(target);
    } catch (err) {
      const message =
        err instanceof AuthError
          ? err.detail
          : "Could not reach the LawFlow API. Please try again.";
      setFormError(message);
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthShell
      eyebrow="Sign in"
      title="Welcome back"
      subtitle="Access your legal research workspace."
      footer={
        <span>
          New to LawFlow?{" "}
          <Link
            href="/signup"
            className="font-semibold text-[#0A1628] underline-offset-4 hover:underline"
          >
            Create an account
          </Link>
        </span>
      }
    >
      <form className="space-y-4" onSubmit={onSubmit} noValidate>
        <AuthField
          label="Work email"
          name="email"
          type="email"
          autoComplete="email"
          required
          inputMode="email"
          placeholder="counsel@firm.in"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <AuthField
          label="Password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          minLength={8}
          maxLength={72}
          placeholder="••••••••"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {formError && (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50/80 px-3.5 py-2.5 text-[12.5px] text-red-700"
          >
            {formError}
          </div>
        )}
        <AuthSubmit pending={pending}>Sign in</AuthSubmit>

        <div className="relative my-1.5">
          <div className="absolute inset-x-0 top-1/2 h-px bg-slate-200" />
          <div className="relative flex justify-center">
            <span className="bg-white px-2 text-[10.5px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              or
            </span>
          </div>
        </div>

        <Link
          href="/admin/login"
          className="group flex items-center justify-between rounded-lg border border-slate-200 bg-gradient-to-r from-white to-slate-50 px-3.5 py-2.5 text-[12.5px] text-slate-600 transition-colors hover:border-[#C9892A]/35 hover:text-[#0A1628]"
        >
          <span className="inline-flex items-center gap-2">
            <span className="inline-flex h-5 w-5 items-center justify-center rounded bg-[#0A1628] text-[#D8A849]">
              <KeyIcon />
            </span>
            <span className="font-medium">Admin Portal</span>
          </span>
          <span className="text-[#9E6A0E] transition-transform group-hover:translate-x-0.5">
            →
          </span>
        </Link>
      </form>
    </AuthShell>
  );
}

function KeyIcon() {
  return (
    <svg
      className="h-3 w-3"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M15 7a4 4 0 11-3.7 5.5L7 17l-2 2H3v-2l5.5-5.5A4 4 0 1115 7z"
      />
    </svg>
  );
}
