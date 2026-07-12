import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AccessGate } from "@/components/AccessGate";
import { Sidebar } from "@/components/Sidebar";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Beacon",
  description: "AI performance intelligence for multifamily marketing",
  icons: { icon: "/icon.png" },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full font-sans">
        <AccessGate>
          <div className="flex min-h-screen">
            <Sidebar />
            <main className="min-w-0 flex-1">
              <div className="mx-auto max-w-6xl px-8 py-8">{children}</div>
            </main>
          </div>
        </AccessGate>
      </body>
    </html>
  );
}
