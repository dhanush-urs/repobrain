"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { 
  BarChart3, 
  FileCode, 
  Search, 
  MessageSquare, 
  History,
  GitBranch,
  Zap,
  Workflow
} from "lucide-react";

type Props = {
  repoId: string;
};

export function RepoSubnav({ repoId }: Props) {
  const pathname = usePathname();

  const navItems = [
    { label: "Overview",  href: `/repos/${repoId}`,              icon: <BarChart3 className="h-4 w-4" /> },
    { label: "Ask Repo",  href: `/repos/${repoId}/chat`,         icon: <MessageSquare className="h-4 w-4" /> },
    { label: "Files",     href: `/repos/${repoId}/files`,        icon: <FileCode className="h-4 w-4" /> },
    { label: "Search",    href: `/repos/${repoId}/search`,       icon: <Search className="h-4 w-4" /> },
    { label: "Knowledge Graph", href: `/repos/${repoId}/graph`,        icon: <GitBranch className="h-4 w-4" /> },
    { label: "Execution Map", href: `/repos/${repoId}/flows`,        icon: <Workflow className="h-4 w-4" /> },
    { label: "Impact",    href: `/repos/${repoId}/impact`,       icon: <Zap className="h-4 w-4" /> },
    { label: "Jobs",      href: `/repos/${repoId}/refresh-jobs`, icon: <History className="h-4 w-4" /> },
  ];

  return (
    <div className="mb-8 overflow-x-auto">
      <nav className="flex items-center gap-1 border-b border-border min-w-max">
        {navItems.map((item) => {
          const isActive = pathname === item.href || (item.label !== "Overview" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "group relative flex items-center gap-2 px-4 py-3 text-sm font-medium transition-all duration-200",
                isActive
                  ? "text-indigo-400"
                  : "text-slate-400 hover:text-slate-200"
              )}
            >
              {item.icon}
              {item.label}
              {isActive && (
                <div className="absolute bottom-0 left-0 h-0.5 w-full bg-indigo-500 shadow-[0_0_8px_rgba(99,102,241,0.5)]" />
              )}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
