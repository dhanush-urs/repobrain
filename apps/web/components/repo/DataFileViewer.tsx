"use client";

import { useState } from "react";
import { CodeBlockViewer } from "./CodeBlockViewer";

type Props = {
  content: string;
  path: string;
  highlightLines?: number[];
};

export function DataFileViewer({ content, path, highlightLines = [] }: Props) {
  const [viewMode, setViewMode] = useState<"table" | "raw">("table");

  // Basic CSV parsing
  const isCsv = path.endsWith(".csv") || path.endsWith(".tsv");
  const delimiter = path.endsWith(".tsv") ? "\t" : ",";
  
  const parseCsv = (text: string) => {
    // A simple parser handling basic CSV structure.
    const lines = text.trim().split("\n").filter(Boolean);
    if (lines.length === 0) return [];
    
    return lines.map(line => {
      const vals = [];
      let current = "";
      let inQuotes = false;
      for (let i = 0; i < line.length; i++) {
        const char = line[i];
        if (char === '"') {
          inQuotes = !inQuotes;
        } else if (char === delimiter && !inQuotes) {
          vals.push(current);
          current = "";
        } else {
          current += char;
        }
      }
      vals.push(current);
      return vals;
    });
  };

  const rows = isCsv ? parseCsv(content) : [];
  const maxRows = 200;
  const isTruncated = rows.length > maxRows;
  const displayRows = rows.slice(0, maxRows);

  if (!isCsv) {
    return <CodeBlockViewer content={content} highlightLines={highlightLines} />;
  }

  return (
    <div className="flex flex-col h-full space-y-3">
      <div className="flex items-center justify-between px-1">
        <div className="text-[11px] font-medium text-slate-500">
          {viewMode === "table" && isTruncated && (
            <span>Showing {maxRows} of {rows.length} records</span>
          )}
        </div>
        <div className="flex bg-slate-950 border border-white/5 rounded-md p-1 shadow-inner">
          <button
            onClick={() => setViewMode("table")}
            className={`px-3 py-1 text-[11px] font-bold rounded transition-colors ${
              viewMode === "table" ? "bg-indigo-500/10 text-indigo-400 border border-indigo-500/20" : "text-slate-600 hover:text-slate-400"
            }`}
          >
            Table
          </button>
          <button
            onClick={() => setViewMode("raw")}
            className={`px-3 py-1 text-[11px] font-bold rounded transition-colors ${
              viewMode === "raw" ? "bg-indigo-500/10 text-indigo-400 border border-indigo-500/20" : "text-slate-600 hover:text-slate-400"
            }`}
          >
            Raw
          </button>
        </div>
      </div>

      {viewMode === "table" ? (
        <div className="overflow-x-auto rounded border border-border/40 bg-slate-950/20">
          <table className="w-full text-left text-sm text-slate-400">
            <thead className="bg-slate-900/60 text-[10px] uppercase font-bold text-slate-600 border-b border-border/40 sticky top-0">
              <tr>
                <th className="px-4 py-2 w-12 text-center border-r border-border/40 font-bold">#</th>
                {displayRows[0]?.map((col, idx) => (
                  <th key={idx} className="px-4 py-2 whitespace-nowrap tracking-wider">
                    {col.trim()}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.02]">
              {displayRows.slice(1).map((row, rIdx) => (
                <tr key={rIdx} className="hover:bg-white/[0.01] transition-colors">
                  <td className="px-4 py-2 font-mono text-[10px] text-slate-700 border-r border-border/40 text-center bg-slate-950/20">
                    {rIdx + 2}
                  </td>
                  {row.map((col, cIdx) => (
                    <td key={cIdx} className="px-4 py-2 whitespace-nowrap truncate max-w-[300px] text-[12px] font-medium">
                      {col.trim()}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <CodeBlockViewer content={content} highlightLines={highlightLines} />
      )}
    </div>
  );
}
