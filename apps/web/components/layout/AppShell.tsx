import Link from "next/link";
import { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { LayoutDashboard, Database, HelpCircle, PanelLeftClose } from "lucide-react";

type Props = {
  children: ReactNode;
};

export function AppShell({ children }: Props) {
  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-200 selection:bg-indigo-500/30 selection:text-white overflow-x-hidden">
      {/* Sidebar */}
      <aside className="fixed left-0 top-0 z-40 hidden h-screen w-64 border-r border-white/5 bg-slate-900/50 backdrop-blur-xl lg:block">
        <div className="flex h-full flex-col px-4 py-6">
          {/* Logo */}
          <div className="mb-8 px-2">
            <Link href="/repos" className="group flex items-center gap-3 outline-none">
              <div className="h-8 w-8 rounded-lg bg-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/20 shrink-0">
                <Database className="h-4 w-4 text-white" />
              </div>
              <span className="text-[17px] font-bold tracking-tight text-white group-hover:text-indigo-300 transition-colors">
                RepoBrain
              </span>
            </Link>
          </div>

          {/* Nav */}
          <nav className="flex-1 space-y-0.5">
            <NavItem href="/repos" icon={<LayoutDashboard size={16} />}>
              Repositories
            </NavItem>
          </nav>

          {/* Footer */}
          <div className="mt-auto space-y-0.5 pt-4 border-t border-white/5">
            <NavItem href="#" icon={<HelpCircle size={16} />}>
              Documentation
            </NavItem>
          </div>
        </div>
      </aside>

      {/* Main */}
      <div className="flex flex-1 flex-col lg:pl-64">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-white/5 bg-slate-950/80 px-6 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <button className="lg:hidden p-2 rounded-lg hover:bg-white/5 transition-colors" aria-label="Toggle sidebar">
              <PanelLeftClose className="h-4 w-4 text-slate-400" />
            </button>
            <span className="text-xs text-slate-500 font-medium">AI Repository Intelligence</span>
          </div>
          <div className="h-7 w-7 rounded-full bg-slate-800 border border-white/10" />
        </header>

        <main className="flex-1 px-6 py-8 mx-auto w-full max-w-7xl">
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
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
        "text-slate-400 hover:bg-white/5 hover:text-white"
      )}
    >
      <span className="text-slate-500">{icon}</span>
      {children}
    </Link>
  );
}
