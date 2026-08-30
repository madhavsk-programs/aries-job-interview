import ReportView from "@/components/ReportView";

export default async function ReportPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;
  return <main className="shell"><nav className="nav"><span className="wordmark">ARIES</span><span className="phase-label">Evidence report</span></nav><ReportView sessionId={sessionId} /></main>;
}
