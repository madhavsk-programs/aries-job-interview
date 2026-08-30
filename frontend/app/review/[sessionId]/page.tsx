import ReviewerView from "@/components/ReviewerView";

export default async function ReviewPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;
  return <main className="shell"><nav className="nav"><span className="wordmark">ARIES</span><span className="phase-label">Reviewer dashboard</span></nav><ReviewerView sessionId={sessionId} /></main>;
}
