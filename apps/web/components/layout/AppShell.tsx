import Link from "next/link";
import { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { LayoutDashboard, Database, HelpCircle, PanelLeftClose } from "lucide-react";

type Props = {
  children: ReactNode;
};

export function AppShell({ children }: Props) {
  return (
    <div className="flex min-h-screen bg-background text-slate-200 selection:bg-indigo-500/30 selection:text-white overflow-x-hidden font-sans">
      {/* Sidebar */}
      <aside className="fixed left-0 top-0 z-40 hidden h-screen w-60 border-r border-border/50 bg-slate-900/40 backdrop-blur-md lg:block">
        <div className="flex h-full flex-col px-3 py-5">
          {/* Logo */}
          <div className="mb-6 px-2">
            <Link href="/repos" className="group flex items-center gap-2.5 outline-none">
              <div className="h-7 w-7 rounded-lg bg-indigo-600 flex items-center justify-center shadow-sm shrink-0">
                <Database className="h-3.5 w-3.5 text-white" />
              </div>
              <span className="text-[15px] font-semibold tracking-tight text-white group-hover:text-indigo-300 transition-colors">
                RepoBrain
              </span>
            </Link>
          </div>

          {/* Nav */}
          <nav className="flex-1 space-y-0.5">
            <NavItem href="/repos" icon={<LayoutDashboard size={14} />}>
              Repositories
            </NavItem>
          </nav>

          {/* Footer */}
          <div className="mt-auto space-y-0.5 pt-4 border-t border-border/50">
            <NavItem href="#" icon={<HelpCircle size={14} />}>
              Documentation
            </NavItem>
          </div>
        </div>
      </aside>

      {/* Main */}
      <div className="flex flex-1 flex-col lg:pl-60">
        <header className="sticky top-0 z-30 flex h-12 items-center justify-between border-b border-border/50 bg-background/80 px-6 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <button className="lg:hidden p-1.5 rounded-md hover:bg-white/5 transition-colors" aria-label="Toggle sidebar">
              <PanelLeftClose className="h-3.5 w-3.5 text-slate-400" />
            </button>
            <span className="text-[10px] text-slate-500 font-medium uppercase tracking-wider">AI Repository Intelligence</span>
          </div>
          <div className="h-6 w-6 rounded-full bg-slate-800 border border-white/5" />
        </header>

        <main className="flex-1 px-6 py-6 mx-auto w-full max-w-7xl">
          {children}
        </main>
      </div>
    </div>
  );
}

function NavItem({ href, icon, children }: { href: string; icon: ReactNode; children: ReactNode }) {
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors",
        "text-slate-400 hover:bg-white/5 hover:text-white"
      )}
    >
      <span className="text-slate-500 group-hover:text-slate-300">{icon}</span>
      {children}
    </Link>
  );
}
