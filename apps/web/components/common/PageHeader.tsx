import { cn } from "@/lib/utils";
import React from "react";

type Props = {
  title: string;
  subtitle?: string;
  icon?: React.ReactNode;
  className?: string;
};

export function PageHeader({ title, subtitle, icon, className }: Props) {
  return (
    <div className={cn("mb-6 space-y-4", className)}>
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-3">
          {icon && (
            <div className="rounded bg-indigo-500/10 p-1.5 text-indigo-400 border border-indigo-500/20 shrink-0 shadow-inner">
              {React.cloneElement(icon as React.ReactElement, { size: 16 })}
            </div>
          )}
          <h1 className="text-base font-bold tracking-tight text-white leading-none uppercase tracking-wider">
            {title}
          </h1>
        </div>
        {subtitle && (
          <p className="text-[11px] font-medium text-slate-500 max-w-2xl leading-relaxed">
            {subtitle}
          </p>
        )}
      </div>
      <div className="h-px w-full bg-white/5" />
    </div>
  );
}
