"use client";

import { useRouter } from "next/navigation";

export function OpenReposButton() {
  const router = useRouter();

  return (
    <button
      type="button"
      onClick={() => router.push("/repos")}
      className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500"
    >
      Open Repositories
    </button>
  );
}
