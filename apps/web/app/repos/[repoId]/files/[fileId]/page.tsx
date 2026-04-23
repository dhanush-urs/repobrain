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
    <div className="space-y-10 pb-24 relative">
      <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-indigo-500/5 blur-[120px] -z-10 animate-pulse-subtle" />

      {/* Breadcrumbs & Modern Header */}
      <div className="animate-in fade-in slide-in-from-top-4 duration-700">
        <div className="flex items-center gap-3 mb-6 px-1">
          <Link href={`/repos/${repoId}/files`} className="flex items-center gap-2 text-[10px] font-extrabold text-slate-500 hover:text-indigo-400 uppercase tracking-[0.3em] transition-all group/back">
            <ArrowLeft className="h-3 w-3 group-hover:-translate-x-1 transition-transform" />
            Explorer
          </Link>
          <ChevronRight className="h-3 w-3 text-slate-800" />
          <span className="text-[10px] font-extrabold text-slate-400 uppercase tracking-[0.3em] truncate max-w-[400px]">{(file?.path || "File").split("/").pop()}</span>
        </div>

        <div className="relative group">
          <div className="absolute -inset-1 bg-gradient-to-r from-indigo-500/10 to-purple-500/10 rounded-3xl blur opacity-25 group-hover:opacity-40 transition duration-1000 group-hover:duration-200" />
          <div className="relative flex flex-col gap-6 md:flex-row md:items-center md:justify-between p-8 rounded-3xl bg-slate-900/40 border border-white/5 backdrop-blur-sm inner-glow">
            <div className="flex items-center gap-6">
              <div className="h-14 w-14 rounded-2xl bg-indigo-500/10 flex items-center justify-center text-indigo-400 ring-1 ring-indigo-500/20 shadow-premium animate-float">
                <FileCode className="h-7 w-7" />
              </div>
              <div>
                <h1 className="text-3xl font-extrabold text-white tracking-tight mb-1">
                  Source Inspector
                </h1>
                <p className="text-slate-400 font-mono text-sm max-w-2xl truncate opacity-70">
                  {file?.path || "Awaiting structural data..."}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <a href={rawUrl} {...rawAssetLinkProps}>
                <Button variant="outline" size="sm" className="bg-white/[0.02] border-white/5 hover:bg-white/[0.05] h-11 px-6 rounded-xl font-bold">
                  <Download className="mr-2 h-4 w-4" />
                  Source
                </Button>
              </a>
            </div>
          </div>
        </div>
      </div>

      <RepoSubnav repoId={repoId} />

      {fetchError ? (
        <Card className="border-rose-500/20 bg-rose-500/5 shadow-premium animate-in fade-in zoom-in-95 duration-500">
          <div className="flex items-start gap-8 p-10">
            <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-[1.5rem] bg-rose-500/10 text-rose-500 shadow-glow/10 border border-rose-500/20">
              <AlertCircle className="h-8 w-8" />
            </div>
            <div className="pt-1">
              <p className="text-[10px] font-extrabold uppercase tracking-[0.3em] text-rose-500 mb-2 opacity-60">System Exception</p>
              <h2 className="text-2xl font-extrabold text-rose-200 tracking-tight">Artifact extraction failed</h2>
              <p className="mt-4 text-lg text-rose-400/70 leading-relaxed max-w-2xl font-medium">{fetchError}</p>
              <div className="mt-10">
                <Link href={`/repos/${repoId}/files`}>
                  <Button variant="indigo" size="sm" className="h-12 px-10 rounded-2xl font-extrabold shadow-lg shadow-rose-500/10">
                    <ArrowLeft className="mr-3 h-5 w-5" />
                    Back to Core Explorer
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        </Card>
      ) : !file ? (
        <EmptyState
          title="Artifact Refraction"
          description="The logical representation of this artifact is no longer detected in the intelligence graph."
          actionHref={`/repos/${repoId}/files`}
          actionLabel="Consult Core Explorer"
        />
      ) : (
        <div className="space-y-10 animate-in fade-in slide-in-from-bottom-8 duration-1000">
          {/* Executive Metadata Section */}
          <div className="grid gap-6 lg:grid-cols-4">
            <Card className="lg:col-span-3 bg-white/[0.01] border-white/5 shadow-premium p-8 inner-glow relative group flex flex-col justify-center rounded-3xl">
              <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-indigo-500/20 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              <div className="flex flex-wrap items-center justify-between gap-8">
                <div className="flex items-center gap-6">
                   <div className="h-14 w-14 rounded-2xl bg-indigo-500/5 border border-white/5 flex items-center justify-center text-indigo-400 shadow-inner group-hover:scale-105 transition-transform duration-500">
                      <FileCode className="h-7 w-7 opacity-70 group-hover:opacity-100 transition-opacity" />
                   </div>
                   <div className="min-w-0">
                      <div className="flex items-center gap-3 mb-1">
                        <h2 className="truncate text-3xl font-extrabold text-white tracking-tighter">
                          {file.path.split("/").pop()}
                        </h2>
                        {highlightLines.length > 0 && (
                          <div className="flex items-center gap-2 text-indigo-400 animate-pulse-subtle bg-indigo-500/10 px-2 py-0.5 rounded-lg border border-indigo-500/20 group-hover:scale-105 transition-transform">
                            <Sparkles className="h-3.5 w-3.5" />
                            <span className="text-[10px] font-black uppercase tracking-widest leading-none">L{highlightLines[0]} Target</span>
                          </div>
                        )}
                      </div>
                      <div className="text-[11px] font-bold text-slate-500 uppercase tracking-[0.3em] font-mono opacity-60 truncate max-w-xl group-hover:opacity-100 transition-opacity">{file.path}</div>
                   </div>
                </div>
                
                <div className="flex items-center gap-8 py-2 px-6 rounded-2xl bg-slate-900 border border-white/5 shadow-inner">
                   <Metric icon={<Hash size={16} />} label="Lines" value={file.line_count || 0} />
                   <div className="h-8 w-[1px] bg-white/5" />
                   <Metric icon={<Database size={16} />} label="Context" value={file.file_kind} />
                   <div className="h-8 w-[1px] bg-white/5" />
                   <Metric icon={<FileText size={16} />} label="Syntax" value={file.language || "Plain"} accent />
                </div>
              </div>
            </Card>

            <Card className="bg-gradient-to-br from-indigo-500/10 via-transparent to-transparent border-indigo-500/20 p-8 shadow-premium inner-glow flex flex-col items-center justify-center text-center rounded-3xl relative overflow-hidden group">
               <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity duration-1000 rotate-12">
                  <Database size={80} />
               </div>
               <p className="text-[10px] font-black uppercase tracking-[0.3em] text-indigo-400/80 mb-3 group-hover:translate-y-[-2px] transition-transform">Intelligence State</p>
               <Badge label={file.parse_status || "synced"} tone={file.parse_status === "completed" ? "green" : "blue"} className="px-6 py-2 rounded-xl text-xs font-black shadow-lg" />
               {file.is_generated && <div className="mt-3 px-3 py-1 rounded-lg bg-amber-500/10 border border-amber-500/20 text-[10px] font-black text-amber-500 uppercase tracking-widest">Synthetic Artifact</div>}
            </Card>
          </div>

          {/* Premium Viewer Frame */}
          <div className="relative group">
            <div className="absolute -inset-1 bg-gradient-to-b from-white/[0.03] to-transparent rounded-[2.5rem] blur opacity-50 pointer-events-none" />
            <Card className="p-0 overflow-hidden border-white/10 shadow-[0_40px_100px_-20px_rgba(0,0,0,0.8)] bg-slate-950 rounded-[2rem] relative z-10 inner-glow">
              <div className="flex flex-wrap items-center justify-between gap-6 px-10 py-6 bg-white/[0.01] border-b border-white/10 relative overflow-hidden">
                <div className="absolute top-0 left-0 w-full h-full bg-gradient-to-r from-indigo-500/[0.02] via-transparent to-transparent pointer-events-none" />
                <div className="flex items-center gap-5 relative z-10">
                  <div className="h-10 w-10 rounded-xl bg-slate-900 border border-white/10 flex items-center justify-center text-indigo-400 shadow-inner group-hover:border-indigo-500/30 transition-colors">
                    <FileText className="h-5 w-5" />
                  </div>
                  <div>
                    <h2 className="text-[10px] font-black uppercase tracking-[0.4em] text-slate-500 mb-0.5">
                      Technical Workspace
                    </h2>
                    <p className="text-xs font-bold text-slate-400 opacity-60">Inspection Interface v2.4</p>
                  </div>
                </div>
                
                <div className="flex items-center gap-2 p-1.5 bg-slate-900/60 rounded-2xl border border-white/5 relative z-10 backdrop-blur-md">
                  {[
                    { href: `/repos/${repoId}/files`, icon: ArrowLeft, label: "Explorer" },
                    { href: `/repos/${repoId}/search`, icon: SearchIcon, label: "Search" },
                    { href: `/repos/${repoId}/ask`, icon: MessageSquare, label: "AI Grounding" }
                  ].map((item) => (
                    <Link key={item.label} href={item.href}>
                      <Button variant="ghost" size="xs" className="h-10 px-5 text-[10px] font-black uppercase tracking-[0.25em] text-slate-500 hover:text-white hover:bg-white/5 transition-all rounded-xl">
                        <item.icon className="mr-2.5 h-4 w-4" />
                        {item.label}
                      </Button>
                    </Link>
                  ))}
                </div>
              </div>

              <div className="relative">
                {isImage ? (
                  <div className="flex flex-col items-center justify-center p-24 bg-slate-900/20 relative overflow-hidden min-h-[600px]">
                    <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(99,102,241,0.08),transparent)] pointer-events-none" />
                    <div className="relative group/img">
                      <div className="absolute -inset-20 bg-indigo-500/10 rounded-full blur-[100px] opacity-20 group-hover/img:opacity-40 transition-opacity duration-1000" />
                      <div className="relative shadow-premium rounded-2xl border border-white/10 overflow-hidden bg-[url('/checkerboard.png')] bg-repeat p-2">
                        <img
                          src={rawUrl}
                          alt={file.path}
                          className="max-w-full h-auto rounded-xl shadow-2xl scale-100 group-hover/img:scale-[1.02] transition-transform duration-1000"
                        />
                      </div>
                    </div>
                    <div className="mt-16 flex items-center gap-4 px-6 py-3 rounded-full border border-white/10 bg-slate-950/80 text-[10px] text-slate-500 font-black uppercase tracking-[0.4em] backdrop-blur-xl shadow-2xl animate-float">
                      <div className="h-2 w-2 rounded-full bg-indigo-500 shadow-[0_0_8px_rgba(99,102,241,1)]" />
                      Visual Representation
                    </div>
                  </div>
                ) : isPdf ? (
                  <div className="h-[90vh] w-full bg-slate-900/50 relative">
                    <iframe src={rawUrl} className="h-full w-full border-0 absolute inset-0" title="Technical Document" />
                    <div className="absolute inset-0 flex items-center justify-center -z-10 bg-slate-950 p-12 text-center">
                      <div className="max-w-md space-y-8">
                        <div className="mx-auto h-24 w-24 rounded-[2rem] bg-indigo-500/5 border border-white/10 flex items-center justify-center text-indigo-400 group-hover:scale-110 transition-transform duration-500 shadow-glow/10">
                          <ExternalLink className="h-10 w-10 opacity-40" />
                        </div>
                        <p className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-600 italic">Structural rendering interface limited. Consult primary viewer.</p>
                        <a href={rawUrl} target="_blank" rel="noopener noreferrer">
                          <Button variant="indigo" className="px-12 h-14 rounded-2xl font-black text-[11px] uppercase tracking-[0.3em] shadow-lg shadow-indigo-500/20">
                            Launch Interface ↗
                          </Button>
                        </a>
                      </div>
                    </div>
                  </div>
                ) : isOffice ? (
                  isPpt ? (
                    <OfficePreviewPane previewUrl={previewUrl} rawUrl={rawUrl} filename={file.path.split("/").pop() || ""} />
                  ) : (
                    <div className="px-10 py-40 text-center bg-slate-900/20">
                      <Card className="flex flex-col items-center gap-12 border border-white/10 bg-slate-950/60 p-20 max-w-xl mx-auto shadow-premium rounded-[3rem] inner-glow group/office">
                        <div className="flex h-28 w-28 items-center justify-center rounded-[2.5rem] bg-indigo-500/5 border border-indigo-500/20 text-indigo-400 shadow-inner group-hover/office:scale-110 transition-all duration-1000 rotate-6 group-hover/office:rotate-0">
                          <Database className="h-14 w-14" />
                        </div>
                        <div className="space-y-6">
                          <div className="text-sm font-black text-indigo-400 uppercase tracking-[0.4em] mb-2 opacity-80">Compound Data Artifact</div>
                          <h3 className="text-3xl font-extrabold text-white tracking-tighter">Native environment required</h3>
                          <p className="text-[17px] text-slate-500 leading-relaxed max-w-sm mx-auto font-medium">
                             Artifact configuration **{file.path.split(".").pop()?.toUpperCase()}** is a complex binary structure designed for local execution.
                          </p>
                        </div>
                        <a href={rawUrl} {...rawAssetLinkProps}>
                          <Button variant="indigo" className="px-14 h-16 rounded-3xl font-black uppercase text-[12px] tracking-[0.3em] shadow-2xl shadow-indigo-500/30 group/btn">
                            <Download className="mr-4 h-6 w-6 group-hover/btn:translate-y-1 transition-transform" />
                            Download Artifact
                          </Button>
                        </a>
                      </Card>
                    </div>
                  )
                ) : file.content ? (
                  <div className="p-0 border-t border-white/5 animate-in fade-in duration-1000">
                    <DataFileViewer content={file.content} path={file.path} highlightLines={highlightLines} />
                  </div>
                ) : (
                  <div className="px-10 py-48 text-center bg-slate-900/20">
                    <div className="inline-flex flex-col items-center gap-8 text-slate-700">
                      <div className="h-24 w-24 rounded-[2.5rem] bg-white/[0.02] border border-dashed border-white/10 flex items-center justify-center animate-pulse-subtle">
                        <FileText className="h-12 w-12 opacity-30" />
                      </div>
                      <div className="text-[10px] font-black uppercase tracking-[0.5em] opacity-40">Zero byte surface detected</div>
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
    <div className="flex flex-col items-center">
      <div className={`text-[9px] font-black uppercase tracking-[0.2em] mb-1.5 flex items-center gap-1.5 ${accent ? "text-indigo-400" : "text-slate-600"}`}>
        {icon}
        {label}
      </div>
      <div className={`text-lg font-extrabold tracking-tight ${accent ? "text-white" : "text-slate-300"}`}>{value}</div>
    </div>
  );
}
