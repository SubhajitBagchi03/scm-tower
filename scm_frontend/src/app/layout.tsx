import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";
import "./globals.css";


export const metadata: Metadata = {
  title: "SCM AI Control Tower",
  description: "Agentic supply chain intelligence middleware — Supervisor-Judge architecture",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,200..800&display=swap" rel="stylesheet" />
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0" />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}