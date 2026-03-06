import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Link from "next/link";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Frontier AI Radar",
  description: "Daily multi-agent AI intelligence system",
};

const navLinks = [
  { href: "/", label: "Dashboard" },
  { href: "/sources", label: "Sources" },
  { href: "/runs", label: "Runs" },
  { href: "/findings", label: "Findings" },
  { href: "/analytics", label: "Analytics" },
  { href: "/digests", label: "Digests" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <div className="min-h-screen bg-gray-50">
          <header className="bg-gradient-to-r from-[#1e3a5f] to-[#0f5132] text-white shadow-md">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
              <div className="flex items-center justify-between h-16">
                <div className="flex items-center gap-3">
                  <span className="text-2xl font-bold tracking-tight">Frontier AI Radar</span>
                  <span className="text-xs text-green-300 bg-green-900/40 px-2 py-0.5 rounded-full">
                    Daily Intelligence
                  </span>
                </div>
                <nav className="flex gap-1">
                  {navLinks.map((link) => (
                    <Link
                      key={link.href}
                      href={link.href}
                      className="px-3 py-1.5 text-sm rounded-md hover:bg-white/10 transition-colors"
                    >
                      {link.label}
                    </Link>
                  ))}
                </nav>
              </div>
            </div>
          </header>
          <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
