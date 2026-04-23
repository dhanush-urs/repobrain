import { ReactNode } from "react";
import { cn } from "@/lib/utils";

type Props = {
  children: ReactNode;
  className?: string;
};

export function Card({ children, className }: Props) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-2xl border border-white/5 bg-card/40 p-6 shadow-premium backdrop-blur-md transition-all duration-300 hover:border-white/10 hover:shadow-glow/10 hover:-translate-y-0.5",
        "inner-glow",
        className
      )}
    >
      <div className="relative z-10">{children}</div>
    </div>
  );
}
