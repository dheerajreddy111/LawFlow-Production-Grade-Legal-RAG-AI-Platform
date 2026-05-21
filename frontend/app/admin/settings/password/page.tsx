"use client";

import { ChangePasswordCard } from "../../../components/auth/ChangePasswordCard";

export default function AdminChangePasswordPage() {
  return (
    <div className="mx-auto max-w-xl space-y-5 px-5 py-6 sm:px-8 sm:py-8">
      <div>
        <p className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-[#9E6A0E]">
          Settings
        </p>
        <h1 className="mt-1.5 font-display text-[26px] font-semibold leading-tight tracking-tight text-[#0A1628]">
          Account security
        </h1>
        <p className="mt-1 max-w-lg text-[13px] leading-relaxed text-slate-500">
          Rotate the admin password. Changing it revokes every persisted
          refresh token, so any other browser using this account will be
          signed out within seconds.
        </p>
      </div>
      <ChangePasswordCard />
    </div>
  );
}
