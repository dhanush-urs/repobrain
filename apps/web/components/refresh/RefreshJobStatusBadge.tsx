import { Badge } from "@/components/common/Badge";

type Props = {
  status: string;
};

function toneForStatus(
  status: string
): "green" | "blue" | "amber" | "rose" | "slate" {
  const s = status.toLowerCase();
  if (s === "ready" || s === "indexed" || s === "completed" || s === "success")
    return "green";
  if (["indexing", "parsing", "embedding", "running", "processing"].includes(s))
    return "blue";
  if (s === "pending" || s === "queued") return "slate";
  if (s === "failed" || s === "error") return "rose";
  return "slate";
}

export function RefreshJobStatusBadge({ status }: Props) {
  return <Badge label={status} tone={toneForStatus(status)} />;
}
