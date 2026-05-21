import type { Metadata } from "next";
import { Geist, Geist_Mono, Fraunces } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "./lib/auth/context";
import { ThemeBootstrap, ThemeProvider } from "./lib/theme/context";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Judiciary-inspired serif for display headings and the brand wordmark.
const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: "LawFlow India — AI-Powered Legal Intelligence",
  description:
    "AI-powered Indian legal research — statutes, case law, and tribunal orders across all jurisdictions.",
  authors: [
    { name: "Dheeraj Reddy Thumma", url: "https://github.com/dheerajreddy111" },
  ],
  creator: "Dheeraj Reddy Thumma",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${fraunces.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        {/* Pre-paint theme apply — prevents the light/dark flash on
            navigation. Must run before React hydrates. See
            app/lib/theme/context.tsx for the resolution rules. */}
        <ThemeBootstrap />
      </head>
      <body className="min-h-full flex flex-col">
        <ThemeProvider>
          <AuthProvider>{children}</AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
