"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const navItems = [
  { href: "/dashboard",       label: "Dashboard",       icon: "dashboard" },
  { href: "/uploads",         label: "Uploads",         icon: "upload" },
  { href: "/command-center",  label: "Command Center",  icon: "terminal" },
  { href: "/inventory",       label: "Inventory",       icon: "inventory_2" },
  { href: "/ask",             label: "Ask",             icon: "smart_toy" },
];

const pageTitles: Record<string, { title: string; subtitle: string }> = {
  "/dashboard":      { title: "Operations Dashboard",  subtitle: "System overview & risk signals" },
  "/uploads":        { title: "Data Ingestion",        subtitle: "CSV & PDF pipeline" },
  "/command-center": { title: "Command Center",        subtitle: "Supervisor-Judge multi-agent orchestration" },
  "/inventory":      { title: "Inventory Intelligence",subtitle: "SKU analysis & stock health" },
  "/ask":            { title: "Ask",                   subtitle: "Document & live data intelligence" },
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const meta = pageTitles[pathname] ?? { title: "SCM Control Tower", subtitle: "" };

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="sidebar-logo-title">SCM Tower</div>
        </div>

        <nav className="sidebar-nav">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`nav-link${pathname === item.href || pathname.startsWith(item.href + "/") ? " nav-link-active" : ""}`}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 20 }}>
                {item.icon}
              </span>
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-footer-label">
            <span className="sidebar-footer-dot" />
            Backend · Connected
          </div>
        </div>
      </aside>

      <div className="content-area">
        <div className="topbar">
          <div>
            <div className="topbar-title">{meta.title}</div>
            {meta.subtitle && <div className="topbar-sub">{meta.subtitle}</div>}
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}