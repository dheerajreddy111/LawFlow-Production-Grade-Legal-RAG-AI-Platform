"use client";

import { Monitor, Moon, Sun } from "lucide-react";

import { cn } from "../lib/cn";
import { useTheme, type ThemeMode } from "../lib/theme/context";

/**
 * Compact 3-position theme toggle: light · dark · system.
 *
 * Used in the AdminTopBar and the user-facing UserMenu so the operator
 * can switch themes from anywhere. Kept terse — three icons, no labels.
 */
export function ThemeToggle({
  size = "md",
  className,
}: {
  size?: "sm" | "md";
  className?: string;
}) {
  const { mode, setMode } = useTheme();
  const buttonSize = size === "sm" ? "h-5 w-5" : "h-6 w-6";
  const iconSize = size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5";

  const options: Array<{ value: ThemeMode; icon: typeof Sun; label: string }> = [
    { value: "light", icon: Sun, label: "Light" },
    { value: "dark", icon: Moon, label: "Dark" },
    { value: "system", icon: Monitor, label: "System" },
  ];

  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className={cn(
        "inline-flex items-center rounded-md border border-slate-200 bg-white p-0.5",
        className,
      )}
    >
      {options.map((opt) => {
        const Icon = opt.icon;
        const active = mode === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={opt.label}
            onClick={() => !active && setMode(opt.value)}
            className={cn(
              "flex items-center justify-center rounded-[5px] transition-colors",
              buttonSize,
              active
                ? "bg-[#0A1628] text-[#D8A849]"
                : "text-slate-500 hover:text-[#0A1628] hover:bg-slate-50",
            )}
          >
            <Icon className={iconSize} aria-hidden />
            <span className="sr-only">{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}
