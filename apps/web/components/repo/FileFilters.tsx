"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { FileRecord } from "@/lib/types";
import { Input } from "@/components/common/Input";
import { Search, Filter, FileCode, ChevronRight } from "lucide-react";
import { Button } from "@/components/common/Button";

type Props = {
  repoId: string;
  files: FileRecord[];
};

export function FileFilters({ repoId, files }: Props) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");

  const kinds = useMemo(() => {
    const values = Array.from(new Set(files.map((f) => f.file_kind))).sort();
    return ["all", ...values];
  }, [files]);

  const filtered = useMemo(() => {
    return files.filter((file) => {
      const matchesQuery =
        !query ||
        (file.path || "").toLowerCase().includes(query.toLowerCase()) ||
        (file.language || "").toLowerCase().includes(query.toLowerCase());
      const matchesKind = kind === "all" || (file.file_kind || "file") === kind;
      return matchesQuery && matchesKind;
    });
  }, [files, query, kind]);

  return (
    <div className="space-y-4 p-4">
      {/* Search + filter bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by path or language..."
            className="pl-10"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-slate-500 shrink-0" />
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="rounded-lg border border-white/10 bg-slate-900 px-3 py-2 text-sm text-slate-300 outline-none focus:border-indigo-500/50 transition-colors"
          >
            {kinds.map((value) => (
              <option key={value} value={value} className="bg-slate-950">
                {value === "all" ? "All types" : value}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="text-xs text-slate-500 px-1">
        {filtered.length} of {files.length} files
      </div>

      {/* File list */}
      <div className="overflow-hidden rounded-xl border border-white/5 bg-slate-950/40">
        <div className="grid grid-cols-12 border-b border-white/5 bg-white/[0.02] px-5 py-3 text-[10px] font-semibold uppercase tracking-widest text-slate-500">
          <div className="col-span-12 sm:col-span-6">Path</div>
          <div className="hidden sm:col-span-3 sm:block text-center">Language</div>
          <div className="hidden sm:col-span-3 sm:block text-right">Action</div>
        </div>

        <div className="divide-y divide-white/[0.04]">
          {filtered.map((file) => (
            <div key={file.id} className="group grid grid-cols-12 items-center px-5 py-3.5 hover:bg-white/[0.02] transition-colors">
              <div className="col-span-12 sm:col-span-6 flex items-center gap-3">
                <div className="rounded bg-slate-900 p-1.5 text-slate-500 ring-1 ring-white/5 group-hover:text-indigo-400 group-hover:ring-indigo-500/20 transition-all shrink-0">
                  <FileCode className="h-3.5 w-3.5" />
                </div>
                <div className="min-w-0">
                  <div className="truncate text-sm text-slate-200 group-hover:text-white transition-colors font-medium">
                    {file.path}
                  </div>
                  <div className="text-[10px] text-slate-500 sm:hidden mt-0.5">
                    {file.language || "code"} · {file.file_kind}
                  </div>
                </div>
              </div>

              <div className="hidden sm:col-span-3 sm:flex items-center justify-center">
                <span className="rounded-full bg-slate-900 px-2.5 py-0.5 text-[10px] font-medium text-slate-400 ring-1 ring-white/5">
                  {file.language || "text"}
                </span>
              </div>

              <div className="hidden sm:col-span-3 sm:flex items-center justify-end">
                <Link href={`/repos/${repoId}/files/${file.id}`}>
                  <Button variant="ghost" size="sm" className="h-7 group-hover:bg-indigo-500/10 group-hover:text-indigo-400">
                    View
                    <ChevronRight className="ml-1 h-3 w-3" />
                  </Button>
                </Link>
              </div>

              <Link href={`/repos/${repoId}/files/${file.id}`} className="absolute inset-0 sm:hidden">
                <span className="sr-only">View File</span>
              </Link>
            </div>
          ))}

          {filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
              <Search className="h-6 w-6 text-slate-600 mb-3" />
              <h4 className="text-sm font-semibold text-white mb-1">No matches</h4>
              <p className="text-xs text-slate-500">Refine your search or change the type filter.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
