import Link from "next/link";
import { Badge } from "@/components/common/Badge";
import { Card } from "@/components/common/Card";
import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { RepoSubnav } from "@/components/layout/RepoSubnav";
import { DataFileViewer } from "@/components/repo/DataFileViewer";
import { OfficePreviewPane } from "@/components/repo/OfficePreviewPane";
import { getRepositoryFileDetail } from "@/lib/api";
import { 
  FileText, 
  Download, 
  ExternalLink, 
  ArrowLeft, 
  Search as SearchIcon, 
  MessageSquare,
  ChevronRight,
  FileCode,
  AlertCircle,
  Hash,
  Database,
  Sparkles
} from "lucide-react";
import { Button } from "@/components/common/Button";

type Props = {
  params: Promise<{ repoId: string; fileId: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
};

export default async function FileDetailPage({ params, searchParams }: Props) {
  const { repoId, fileId } = await params;
  const sParams = await searchParams;

  // Guard: ensure fileId is a valid non-empty, non-null string before fetching
  const isValidFileId =
    fileId &&
    fileId !== "null" &&
    fileId !== "undefined" &&
    fileId.length > 4;

  // Safely parse ?line=N — must be a positive integer
  const highlightLineStr = sParams.line as string | undefined;
  const parsedLine = highlightLineStr ? parseInt(highlightLineStr, 10) : NaN;
  const highlightLines =
    !isNaN(parsedLine) && parsedLine > 0 ? [parsedLine] : [];

  let file = null;
  let fetchError: string | null = null;

  if (!isValidFileId) {
    fetchError = `Invalid file ID: "${fileId}"`;
  } else {
    try {
      file = await getRepositoryFileDetail(repoId, fileId);
      if (!file) {
        fetchError = `File with ID "${fileId}" was not found in the repository.`;
      }
    } catch (err) {
      fetchError =
        err instanceof Error
          ? `Failed to load file: ${err.message}`
          : "An unexpected error occurred while loading the file.";
    }
  }

  const isImage = file?.path && /\.(jpg|jpeg|png|gif|webp|svg)$/i.test(file.path);
  const isPdf = file?.path && /\.pdf$/i.test(file.path);
  const isOffice = file?.path && /\.(pptx|ppt|docx|doc|xlsx|xls|odt|odp|ods)$/i.test(file.path);
  const isPpt = file?.path && /\.(pptx|ppt)$/i.test(file.path);

  // Build a browser-safe raw asset URL.
  const publicApiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");
  const publicApiOrigin = publicApiBase.endsWith("/api/v1")
    ? publicApiBase.slice(0, -"/api/v1".length)
    : publicApiBase;

  let rawUrl = "";
  if (file?.raw_url) {
    if (/^https?:\/\//i.test(file.raw_url)) {
      rawUrl = file.raw_url;
    } else if (publicApiOrigin) {
      rawUrl = `${publicApiOrigin}${file.raw_url}`;
    } else {
      rawUrl = file.raw_url;
    }
  } else if (publicApiOrigin) {
    rawUrl = `${publicApiOrigin}/api/v1/repos/${repoId}/files/${fileId}/raw`;
  } else {
    rawUrl = `/api/v1/repos/${repoId}/files/${fileId}/raw`;
  }

  const shouldForceDownload =
    Boolean(isOffice) || Boolean(file?.is_binary && !isImage && !isPdf);
  const rawAssetLinkProps = shouldForceDownload
    ? { download: file?.path?.split("/").pop() || true }
    : { target: "_blank", rel: "noreferrer" as const };

  // previewUrl is always relative — works via the Next.js /api/v1 proxy rewrite.
  const previewUrl = `/api/v1/repos/${repoId}/files/${fileId}/preview`;

  return (
    <div className="space-y-6 pb-12">
      {/* Breadcrumbs & Header */}
      <div className="animate-in fade-in slide-in-from-bottom-2 duration-500">
        <div className="flex items-center gap-2 mb-4 px-1">
          <Link href={`/repos/${repoId}/files`} className="flex items-center gap-1.5 text-[10px] font-bold text-slate-500 hover:text-indigo-400 uppercase tracking-wider transition-colors group/back">
            <ArrowLeft size={10} className="group-hover:-translate-x-0.5 transition-transform" />
            Explorer
          </Link>
          <ChevronRight size={10} className="text-slate-800" />
          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider truncate max-w-[400px]">{(file?.path || "File").split("/").pop()}</span>
        </div>

        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between px-4 py-3.5 rounded-lg bg-slate-900/40 border border-border/40 shadow-sm">
          <div className="flex items-center gap-4">
            <div className="h-10 w-10 rounded bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
              <FileCode size={20} />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white tracking-tight leading-none mb-1">
                File Inspector
              </h1>
              <p className="text-slate-500 font-mono text-[11px] max-w-2xl truncate">
                {file?.path || "..."}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <a href={rawUrl} {...rawAssetLinkProps}>
              <Button variant="outline" size="sm" className="h-8 px-4 text-xs">
                <Download size={14} className="mr-2" />
                Raw Source
              </Button>
            </a>
          </div>
        </div>
      </div>

      <RepoSubnav repoId={repoId} />

      {fetchError ? (
        <Card className="border-rose-500/20 bg-rose-500/5 shadow-sm animate-in fade-in zoom-in-95 duration-500">
          <div className="flex items-start gap-4 p-6">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded bg-rose-500/10 text-rose-500 border border-rose-500/20">
              <AlertCircle size={20} />
            </div>
            <div className="pt-0.5">
              <p className="text-[10px] font-bold uppercase tracking-wider text-rose-500 mb-1 opacity-60">Error</p>
              <h2 className="text-base font-bold text-rose-200 tracking-tight">Failed to load file</h2>
              <p className="mt-2 text-sm text-rose-400/80 leading-relaxed max-w-2xl">{fetchError}</p>
              <div className="mt-6">
                <Link href={`/repos/${repoId}/files`}>
                  <Button variant="primary" size="sm" className="h-8 px-4">
                    <ArrowLeft size={14} className="mr-2" />
                    Back to Explorer
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        </Card>
      ) : !file ? (
        <EmptyState
          title="File Not Found"
          description="The requested file could not be located in the indexed codebase."
          actionHref={`/repos/${repoId}/files`}
          actionLabel="Back to Explorer"
        />
      ) : (
        <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700">
          {/* Metadata Grid */}
          <div className="grid gap-4 lg:grid-cols-4">
            <Card className="lg:col-span-3 bg-slate-900/20 border-border/40 p-4 flex items-center justify-between gap-6 rounded-lg shadow-premium">
              <div className="flex items-center gap-4">
                <div className="h-10 w-10 rounded bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
                  <FileCode size={18} />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <h2 className="truncate text-base font-bold text-slate-200 tracking-tight">
                      {file.path.split("/").pop()}
                    </h2>
                    {highlightLines.length > 0 && (
                      <div className="flex items-center gap-1.5 text-indigo-400 bg-indigo-500/10 px-1.5 py-0.5 rounded border border-indigo-500/20">
                        <Sparkles size={10} />
                        <span className="text-[9px] font-bold uppercase tracking-wider leading-none">Line {highlightLines[0]}</span>
                      </div>
                    )}
                  </div>
                  <div className="text-[10px] font-medium text-slate-600 uppercase tracking-wider font-mono truncate max-w-xl">{file.path}</div>
                </div>
              </div>
              
              <div className="flex items-center gap-6 px-4 py-2 rounded bg-slate-950/40 border border-white/5 shadow-inner">
                <Metric icon={<Hash size={12} />} label="Lines" value={file.line_count || 0} />
                <div className="h-6 w-[1px] bg-white/5" />
                <Metric icon={<Database size={12} />} label="Role" value={file.file_kind} />
                <div className="h-6 w-[1px] bg-white/5" />
                <Metric icon={<FileText size={12} />} label="Type" value={file.language || "Text"} accent />
              </div>
            </Card>

            <Card className="bg-slate-900/40 border-border/40 p-4 flex flex-col items-center justify-center text-center rounded-lg shadow-premium group">
              <p className="text-[9px] font-bold uppercase tracking-wider text-slate-600 mb-2">Indexing Status</p>
              <Badge label={file.parse_status || "indexed"} tone={file.parse_status === "completed" ? "green" : "blue"} className="px-3 py-1 text-[10px] font-bold" />
              {file.is_generated && <div className="mt-2 px-2 py-0.5 rounded border border-amber-500/20 bg-amber-500/5 text-[9px] font-bold text-amber-500/80 uppercase tracking-wider">Generated</div>}
            </Card>
          </div>

          {/* Viewer Container */}
          <div className="relative">
            <Card className="p-0 overflow-hidden border-border/40 shadow-premium bg-slate-950 rounded-lg">
              <div className="flex flex-wrap items-center justify-between gap-4 px-4 py-3 bg-white/[0.01] border-b border-white/5">
                <div className="flex items-center gap-3">
                  <div className="h-7 w-7 rounded bg-slate-900 border border-white/5 flex items-center justify-center text-indigo-400">
                    <FileText size={14} />
                  </div>
                  <h2 className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    Technical Preview
                  </h2>
                </div>
                
                <div className="flex items-center gap-1">
                  {[
                    { href: `/repos/${repoId}/files`, icon: ArrowLeft, label: "Files" },
                    { href: `/repos/${repoId}/search`, icon: SearchIcon, label: "Search" },
                    { href: `/repos/${repoId}/chat`, icon: MessageSquare, label: "Ask AI" }
                  ].map((item) => (
                    <Link key={item.label} href={item.href}>
                      <Button variant="ghost" size="xs" className="h-7 px-2.5 text-[9px] font-bold uppercase tracking-wider text-slate-500 hover:text-slate-200 transition-colors">
                        <item.icon size={12} className="mr-1.5" />
                        {item.label}
                      </Button>
                    </Link>
                  ))}
                </div>
              </div>

              <div className="relative">
                {isImage ? (
                  <div className="flex flex-col items-center justify-center p-16 bg-slate-900/20 min-h-[400px]">
                    <div className="relative shadow-lg rounded border border-white/10 overflow-hidden bg-[url('/checkerboard.png')] bg-repeat p-1">
                      <img
                        src={rawUrl}
                        alt={file.path}
                        className="max-w-full h-auto rounded-sm"
                      />
                    </div>
                    <div className="mt-8 flex items-center gap-2 px-3 py-1.5 rounded-full border border-white/5 bg-slate-950/80 text-[9px] text-slate-600 font-bold uppercase tracking-wider shadow-sm">
                      <div className="h-1.5 w-1.5 rounded-full bg-indigo-500/50" />
                      Image Preview
                    </div>
                  </div>
                ) : isPdf ? (
                  <div className="h-[70vh] w-full bg-slate-900/50 relative">
                    <iframe src={rawUrl} className="h-full w-full border-0 absolute inset-0" title="PDF Preview" />
                  </div>
                ) : isOffice ? (
                  isPpt ? (
                    <OfficePreviewPane previewUrl={previewUrl} rawUrl={rawUrl} filename={file.path.split("/").pop() || ""} />
                  ) : (
                    <div className="px-6 py-24 text-center bg-slate-900/20">
                      <Card className="flex flex-col items-center gap-8 border border-white/5 bg-slate-950/60 p-12 max-w-md mx-auto shadow-premium rounded-xl">
                        <div className="flex h-16 w-16 items-center justify-center rounded-lg bg-indigo-500/5 border border-indigo-500/20 text-indigo-400">
                          <Database size={24} />
                        </div>
                        <div className="space-y-4">
                          <h3 className="text-xl font-bold text-white tracking-tight">Binary Format</h3>
                          <p className="text-sm text-slate-500 leading-relaxed font-medium">
                             This file format (**{file.path.split(".").pop()?.toUpperCase()}**) is a binary structure that requires a native application for full inspection.
                          </p>
                        </div>
                        <a href={rawUrl} {...rawAssetLinkProps}>
                          <Button variant="primary" size="sm" className="px-8 h-10 shadow-sm">
                            <Download size={16} className="mr-2" />
                            Download File
                          </Button>
                        </a>
                      </Card>
                    </div>
                  )
                ) : file.content ? (
                  <div className="p-0 border-t border-white/5">
                    <DataFileViewer content={file.content} path={file.path} highlightLines={highlightLines} />
                  </div>
                ) : (
                  <div className="px-6 py-32 text-center bg-slate-900/20">
                    <div className="inline-flex flex-col items-center gap-4 text-slate-700">
                      <div className="h-16 w-16 rounded-lg bg-white/[0.02] border border-dashed border-white/10 flex items-center justify-center">
                        <FileText size={24} className="opacity-20" />
                      </div>
                      <div className="text-[9px] font-bold uppercase tracking-widest opacity-40">Empty or unreadable content</div>
                    </div>
                  </div>
                )}
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ icon, label, value, accent }: { icon: React.ReactNode; label: string; value: string | number; accent?: boolean }) {
  return (
    <div className="flex flex-col items-start min-w-[60px]">
      <div className={`text-[9px] font-bold uppercase tracking-wider mb-1 flex items-center gap-1.5 ${accent ? "text-indigo-400" : "text-slate-600"}`}>
        {icon}
        {label}
      </div>
      <div className={`text-sm font-bold tracking-tight ${accent ? "text-slate-200" : "text-slate-400"}`}>{value}</div>
    </div>
  );
}
