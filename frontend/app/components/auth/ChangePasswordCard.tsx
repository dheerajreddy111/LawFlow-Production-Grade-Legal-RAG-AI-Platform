"use client";

import { CheckCircle2, KeyRound, Lock } from "lucide-react";
import { FormEvent, useState } from "react";

import { changePassword, type ChangePasswordError } from "../../lib/auth/client";
import { AuthField } from "./AuthField";
import { AuthSubmit } from "./AuthSubmit";

/**
 * Self-contained password-change form. Drops into any authenticated
 * surface (settings page, modal, drawer). Uses the same AuthField /
 * AuthSubmit primitives the login + signup forms use so the visual
 * language matches.
 *
 * Behaviour:
 *  - Client-side validation: new vs confirm must match, min length 8.
 *  - Backend revokes every refresh token on success — we show that to
 *    the operator so they aren't surprised when other devices log out.
 */
export function ChangePasswordCard({
  onSuccess,
}: {
  onSuccess?: () => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<{ field: string; msg: string } | null>(
    null,
  );
  const [success, setSuccess] = useState(false);

  function resetErrors() {
    setFormError(null);
    setFieldError(null);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    resetErrors();

    if (newPassword.length < 8) {
      setFieldError({ field: "new_password", msg: "Use at least 8 characters." });
      return;
    }
    if (newPassword !== confirmPassword) {
      setFieldError({ field: "confirm_password", msg: "Passwords do not match." });
      return;
    }
    if (newPassword === currentPassword) {
      setFieldError({
        field: "new_password",
        msg: "New password must differ from your current one.",
      });
      return;
    }

    setPending(true);
    setSuccess(false);
    try {
      await changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setSuccess(true);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      onSuccess?.();
    } catch (err) {
      const e = err as ChangePasswordError;
      if (e.status === 401) {
        setFieldError({
          field: "current_password",
          msg: "Current password is incorrect.",
        });
      } else {
        setFormError(e.detail || "Could not update password.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="space-y-4 rounded-xl border border-slate-200/70 bg-white p-5 sm:p-6"
      aria-labelledby="change-pw-title"
    >
      <header className="flex items-start gap-3 border-b border-slate-100 pb-4">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#0A1628] text-[#D8A849]">
          <KeyRound className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#9E6A0E]">
            Security
          </p>
          <h2
            id="change-pw-title"
            className="mt-0.5 font-display text-[16px] font-semibold leading-tight tracking-tight text-[#0A1628]"
          >
            Change password
          </h2>
          <p className="mt-1 text-[12px] leading-relaxed text-slate-500">
            Updating your password signs every other device out. Pick a value
            you haven&apos;t used elsewhere.
          </p>
        </div>
      </header>

      {success && (
        <div
          role="status"
          className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50/80 px-3.5 py-2.5 text-[12.5px] text-emerald-800"
        >
          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <div>
            <p className="font-semibold">Password updated.</p>
            <p className="mt-0.5 text-emerald-700">
              Other devices have been signed out — use your new password to
              sign back in elsewhere.
            </p>
          </div>
        </div>
      )}

      {formError && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50/80 px-3.5 py-2.5 text-[12.5px] text-red-700"
        >
          {formError}
        </div>
      )}

      <AuthField
        label="Current password"
        type="password"
        autoComplete="current-password"
        name="current_password"
        value={currentPassword}
        onChange={(e) => {
          setCurrentPassword(e.target.value);
          if (fieldError?.field === "current_password") resetErrors();
        }}
        error={fieldError?.field === "current_password" ? fieldError.msg : null}
        required
      />
      <AuthField
        label="New password"
        type="password"
        autoComplete="new-password"
        name="new_password"
        value={newPassword}
        onChange={(e) => {
          setNewPassword(e.target.value);
          if (fieldError?.field === "new_password") resetErrors();
        }}
        hint="At least 8 characters."
        error={fieldError?.field === "new_password" ? fieldError.msg : null}
        required
        minLength={8}
      />
      <AuthField
        label="Confirm new password"
        type="password"
        autoComplete="new-password"
        name="confirm_password"
        value={confirmPassword}
        onChange={(e) => {
          setConfirmPassword(e.target.value);
          if (fieldError?.field === "confirm_password") resetErrors();
        }}
        error={fieldError?.field === "confirm_password" ? fieldError.msg : null}
        required
        minLength={8}
      />

      <div className="pt-1">
        <AuthSubmit pending={pending} disabled={pending}>
          <Lock className="h-3.5 w-3.5" aria-hidden /> Update password
        </AuthSubmit>
      </div>
    </form>
  );
}
