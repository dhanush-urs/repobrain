import * as React from "react";
import { cn } from "@/lib/utils";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "outline" | "ghost" | "danger" | "indigo";
  size?: "xs" | "sm" | "md" | "lg" | "icon";
  isLoading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", isLoading, children, disabled, ...props }, ref) => {
    const variants = {
      primary: "bg-white text-slate-950 hover:bg-slate-100 shadow-sm active:bg-slate-200 font-bold",
      secondary: "bg-slate-900 text-slate-200 hover:bg-slate-800 border border-border/40 active:bg-slate-950 font-semibold",
      outline: "bg-transparent border border-white/10 hover:border-white/20 hover:bg-white/5 text-slate-400 hover:text-slate-200 active:bg-white/10 font-semibold",
      ghost: "bg-transparent hover:bg-white/5 text-slate-500 hover:text-slate-300 active:bg-white/10 font-semibold",
      danger: "bg-rose-500/10 text-rose-500 border border-rose-500/20 hover:bg-rose-500/20 active:bg-rose-500/30 font-bold",
      indigo: "bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 hover:bg-indigo-500/20 active:bg-indigo-500/30 font-bold",
    };

    const sizes = {
      xs: "h-7 px-2 text-[10px] rounded-md uppercase tracking-wider",
      sm: "h-8 px-3 text-[11px] rounded-md font-bold uppercase tracking-wider",
      md: "h-9 px-4 text-xs rounded-md",
      lg: "h-10 px-6 text-sm rounded-md",
      icon: "h-9 w-9 flex items-center justify-center rounded-md",
    };

    return (
      <button
        ref={ref}
        disabled={isLoading || disabled}
        className={cn(
          "inline-flex items-center justify-center transition-colors duration-200 focus:outline-none focus:ring-1 focus:ring-white/20 disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap",
          variants[variant],
          sizes[size],
          className
        )}
        {...props}
      >
        {isLoading ? (
          <svg className="mr-2 h-4 w-4 animate-spin" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
        ) : null}
        {children}
      </button>
    );
  }
);

Button.displayName = "Button";
