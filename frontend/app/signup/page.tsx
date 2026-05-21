"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { AuthField } from "../components/auth/AuthField";
import { AuthShell } from "../components/auth/AuthShell";
import { AuthSubmit } from "../components/auth/AuthSubmit";
import { AuthError, useAuth } from "../lib/auth/context";

interface FormErrors {
  email?: string;
  password?: string;
  full_name?: string;
}

export default function SignupPage() {
  const router = useRouter();
  const { signup } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [pending, setPending] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FormErrors>({});

  function validate(): FormErrors | null {
    const errs: FormErrors = {};
    if (!email.includes("@")) errs.email = "Please enter a valid email.";
    if (password.length < 8) errs.password = "Password must be at least 8 characters.";
    if (password.length > 72) errs.password = "Password is too long (max 72 characters).";
    if (Object.keys(errs).length === 0) return null;
    return errs;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    const errs = validate();
    setFieldErrors(errs ?? {});
    if (errs) return;
    setPending(true);
    setFormError(null);
    try {
      const session = await signup({
        email: email.trim().toLowerCase(),
        password,
        full_name: fullName.trim() || undefined,
      });
      router.replace(session.user.role === "admin" ? "/admin" : "/");
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
      eyebrow="Create account"
      title="Start your research"
      subtitle="Free access to LawFlow's deterministic + RAG legal intelligence."
      footer={
        <span>
          Already registered?{" "}
          <Link
            href="/login"
            className="font-semibold text-[#0A1628] underline-offset-4 hover:underline"
          >
            Sign in
          </Link>
        </span>
      }
    >
      <form className="space-y-4" onSubmit={onSubmit} noValidate>
        <AuthField
          label="Full name"
          name="full_name"
          type="text"
          autoComplete="name"
          placeholder="Counsel"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          error={fieldErrors.full_name}
        />
        <AuthField
          label="Work email"
          name="email"
          type="email"
          autoComplete="email"
          inputMode="email"
          required
          placeholder="counsel@firm.in"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={fieldErrors.email}
        />
        <AuthField
          label="Password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          maxLength={72}
          placeholder="At least 8 characters"
          hint="8–72 characters."
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={fieldErrors.password}
        />
        {formError && (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50/80 px-3.5 py-2.5 text-[12.5px] text-red-700"
          >
            {formError}
          </div>
        )}
        <AuthSubmit pending={pending}>Create account</AuthSubmit>
        <p className="text-[11.5px] leading-relaxed text-slate-400">
          By signing up, you agree to use LawFlow as a research tool — outputs
          are not legal advice.
        </p>
      </form>
    </AuthShell>
  );
}
