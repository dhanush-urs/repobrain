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
        "relative overflow-hidden rounded-xl border border-white/5 bg-card/40 p-5 transition-colors duration-300 hover:border-white/10",
        "inner-glow shadow-sm",
        className
      )}
    >
      <div className="relative z-10">{children}</div>
    </div>
  );
}
