import { cn } from "@/lib/utils";

type Props = {
  label: string;
  tone?: "green" | "blue" | "amber" | "rose" | "slate" | "yellow" | "indigo";
  className?: string;
};

export function Badge({ label, tone, className }: Props) {
  const l = label.toLowerCase();
  
  const tones: Record<string, string> = {
    green: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    blue: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    amber: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    yellow: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
    rose: "bg-rose-500/10 text-rose-400 border-rose-500/20",
    slate: "bg-slate-500/10 text-slate-400 border-slate-500/20",
    indigo: "bg-indigo-500/10 text-indigo-400 border-indigo-500/20",
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
        "inline-flex items-center gap-2 rounded-lg border px-3 py-1 text-[9px] font-black uppercase tracking-[0.2em] transition-all duration-500 inner-glow shadow-sm",
        style,
        isActive && "animate-pulse-subtle",
        className
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", 
                        l === "ready" || l === "completed" || l === "indexed" ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]" :
                        l === "failed" || l === "error" ? "bg-rose-400 shadow-[0_0_8px_rgba(251,113,133,0.6)]" :
                        l === "pending" || l === "queued" ? "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.6)]" :
                        "bg-indigo-400 shadow-[0_0_8px_rgba(129,140,248,0.6)]")} />
      {label}
    </span>
  );
}
