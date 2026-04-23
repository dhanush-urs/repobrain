import { cn } from "@/lib/utils";

function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse-subtle rounded-xl bg-white/[0.03] shadow-inner", className)}
      {...props}
    />
  );
}

export { Skeleton };
