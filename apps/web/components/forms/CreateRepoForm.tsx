"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { createRepository } from "@/lib/api";
import { Button } from "@/components/common/Button";
import { Input } from "@/components/common/Input";
import { Github, Plus } from "lucide-react";

export function CreateRepoForm() {
  const router = useRouter();
  const [repoUrl, setRepoUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setMessage(null);

    try {
      const repo = await createRepository({
        repo_url: repoUrl,
        branch,
      });

      if (!repo || !repo.id) {
        throw new Error("Failed to create repository: No data returned from API.");
      }

      router.push(`/repos/${repo.id}`);
      router.refresh();
    } catch (err) {
      setMessage(
        err instanceof Error ? err.message : "Failed to create repository"
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-2">
        <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
          GitHub Repository URL
        </label>
        <div className="relative">
          <Github className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <Input
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            className="pl-10"
            required
          />
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
          Default Branch
        </label>
        <Input
          value={branch}
          onChange={(e) => setBranch(e.target.value)}
          placeholder="main"
          required
        />
      </div>

      {message ? (
        <div className="rounded-lg bg-rose-500/10 border border-rose-500/20 p-3 text-xs text-rose-400">
          {message}
        </div>
      ) : null}

      <Button
        type="submit"
        isLoading={loading}
        className="w-full"
        variant="indigo"
      >
        <Plus className="mr-2 h-4 w-4" />
        Add Repository
      </Button>
    </form>
  );
}
