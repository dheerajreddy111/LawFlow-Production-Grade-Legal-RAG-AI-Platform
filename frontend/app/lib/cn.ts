import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Standard shadcn-style classname helper. Combines clsx's conditional class
 * logic with tailwind-merge's last-class-wins deduplication so prop
 * overrides naturally beat component defaults without manual ordering.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
