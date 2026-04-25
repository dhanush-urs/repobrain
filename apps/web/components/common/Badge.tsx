import { cn } from "@/lib/utils";

type Props = {
  label: string;
  tone?: "green" | "blue" | "amber" | "rose" | "slate" | "yellow" | "indigo";
  className?: string;
};

export function Badge({ label, tone, className }: Props) {
  const l = label.toLowerCase();
  
  const tones: Record<string, string> = {
    green: "bg-emerald-500/5 text-emerald-500/80 border-emerald-500/20",
    blue: "bg-indigo-500/5 text-indigo-400 border-indigo-500/20",
    amber: "bg-amber-500/5 text-amber-500/80 border-amber-500/20",
    yellow: "bg-yellow-500/5 text-yellow-500/80 border-yellow-500/20",
    rose: "bg-rose-500/5 text-rose-500/80 border-rose-500/20",
    slate: "bg-slate-500/5 text-slate-500/80 border-slate-500/20",
    indigo: "bg-indigo-500/5 text-indigo-400 border-indigo-500/20",
  };

  const variantsByLabel: Record<string, string> = {
    ready: tones.green,
    indexed: tones.green,
    completed: tones.green,
    indexing: `${tones.blue}`,
    parsing: `${tones.blue}`,
    embedding: `${tones.blue}`,
    processing: `${tones.blue}`,
    running: `${tones.blue}`,
    pending: tones.amber,
    queued: tones.slate,
    failed: tones.rose,
    error: tones.rose,
    generated: tones.yellow,
  };

  const isActive = ["indexing", "parsing", "embedding", "processing", "running"].includes(l);
  const style = tone ? tones[tone] : (variantsByLabel[l] || tones.slate);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider transition-colors duration-300",
        style,
        isActive && "animate-pulse-subtle",
        className
      )}
    >
      <span className={cn("h-1 w-1 rounded-full shrink-0", 
                        l === "ready" || l === "completed" || l === "indexed" ? "bg-emerald-400" :
                        l === "failed" || l === "error" ? "bg-rose-400" :
                        l === "pending" || l === "queued" ? "bg-amber-400" :
                        "bg-indigo-400")} />
      {label}
    </span>
  );
}
