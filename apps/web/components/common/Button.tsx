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
      primary: "bg-white text-slate-950 hover:bg-slate-100 shadow-premium active:bg-slate-200",
      secondary: "bg-slate-900 text-white hover:bg-slate-800 border border-white/5 shadow-premium active:bg-slate-950",
      outline: "bg-transparent border border-white/10 hover:border-white/20 hover:bg-white/5 text-white active:bg-white/10",
      ghost: "bg-transparent hover:bg-white/5 text-white active:bg-white/10",
      danger: "bg-rose-600 text-white hover:bg-rose-500 shadow-lg shadow-rose-900/20 active:bg-rose-700",
      indigo: "bg-indigo-600 text-white hover:bg-indigo-500 shadow-lg shadow-indigo-900/20 active:bg-indigo-700",
    };

    const sizes = {
      xs: "h-7 px-2 text-[10px] rounded-md font-semibold tracking-wide uppercase",
      sm: "h-9 px-3.5 text-xs rounded-lg font-medium",
      md: "h-11 px-5 text-sm rounded-xl font-semibold",
      lg: "h-13 px-7 text-base rounded-2xl font-bold tracking-tight",
      icon: "h-10 w-10 flex items-center justify-center rounded-xl",
    };

    return (
      <button
        ref={ref}
        disabled={isLoading || disabled}
        className={cn(
          "inline-flex items-center justify-center transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-white/20 focus:ring-offset-2 focus:ring-offset-background active:scale-[0.97] disabled:opacity-50 disabled:pointer-events-none",
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
