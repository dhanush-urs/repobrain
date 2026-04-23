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
    <div className={cn("mb-8 space-y-4", className)}>
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-3">
          {icon && (
            <div className="rounded-xl bg-indigo-500/10 p-2.5 text-indigo-400 ring-1 ring-indigo-500/20 shadow-lg shadow-indigo-500/5">
              {icon}
            </div>
          )}
          <h1 className="text-3xl font-black tracking-tight text-white sm:text-4xl pr-4 leading-none">
            {title}
          </h1>
        </div>
        {subtitle && (
          <p className="text-[15px] text-slate-400 max-w-2xl leading-relaxed font-medium">
            {subtitle}
          </p>
        )}
      </div>
      <div className="relative">
        <div className="h-px w-full bg-gradient-to-r from-indigo-500/50 via-white/5 to-transparent" />
        <div className="absolute -top-[0.5px] left-0 h-[2px] w-24 bg-gradient-to-r from-indigo-500 to-transparent" />
      </div>
    </div>
  );
}
