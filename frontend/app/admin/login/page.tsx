"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { AuthField } from "../../components/auth/AuthField";
import { AuthShell } from "../../components/auth/AuthShell";
import { AuthSubmit } from "../../components/auth/AuthSubmit";
import { AuthError, useAuth } from "../../lib/auth/context";

export default function AdminLoginPage() {
  const router = useRouter();
  const { adminLogin } = useAuth();
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
      await adminLogin({ email: email.trim(), password });
      router.replace("/admin");
    } catch (err) {
      const message =
        err instanceof AuthError
          ? // Backend deliberately returns "Invalid credentials" for both
            // bad password and non-admin user so we don't leak admin status.
            err.detail
          : "Could not reach the LawFlow API. Please try again.";
      setFormError(message);
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthShell
      variant="admin"
      eyebrow="Restricted access"
      title="Admin sign in"
      subtitle="Access the LawFlow operations console — ingestion, evaluation, analytics."
      footer={
        <span className="text-slate-300">
          Not an administrator?{" "}
          <Link
            href="/login"
            className="font-semibold text-white underline-offset-4 hover:underline"
          >
            Go to user sign in
          </Link>
        </span>
      }
    >
      <form className="space-y-4" onSubmit={onSubmit} noValidate>
        <AuthField
          label="Admin email"
          name="email"
          type="email"
          autoComplete="email"
          required
          inputMode="email"
          placeholder="admin@firm.in"
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
        <AuthSubmit pending={pending} variant="admin">
          Enter admin console
        </AuthSubmit>
        <p className="rounded-lg bg-slate-50 px-3 py-2 text-[11.5px] leading-relaxed text-slate-500 ring-1 ring-slate-200/70">
          Admin actions are logged. Access is restricted to operators
          authorised to manage ingestion, evaluation, and analytics.
        </p>
      </form>
    </AuthShell>
  );
}
