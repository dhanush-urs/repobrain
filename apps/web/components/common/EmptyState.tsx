import Link from "next/link";
import { Button } from "./Button";
import { Ghost } from "lucide-react";

type Props = {
  title: string;
  description: string;
  actionHref?: string;
  actionLabel?: string;
};

export function EmptyState({ title, description, actionHref, actionLabel }: Props) {
  return (
    <div className="flex flex-col items-center justify-center rounded-3xl border-2 border-dashed border-white/5 bg-slate-900/20 p-16 text-center animate-in fade-in zoom-in duration-500">
      <div className="mb-6 rounded-2xl bg-slate-950 p-5 text-slate-600 ring-1 ring-white/5 opacity-50">
        <Ghost className="h-10 w-10" />
      </div>
      <h3 className="text-xl font-bold text-white tracking-tight">{title}</h3>
      <p className="mt-2 text-[15px] text-slate-400 max-w-sm leading-relaxed">{description}</p>
      
      {actionHref && actionLabel && (
        <Link href={actionHref} className="mt-8">
          <Button variant="indigo" size="sm" className="px-8 shadow-lg shadow-indigo-500/10">
            {actionLabel}
          </Button>
        </Link>
      )}
    </div>
  );
}
