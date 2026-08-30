import VoiceRoom from "@/components/VoiceRoom";


type InterviewPageProps = {
  params: Promise<{ sessionId: string }>;
};


export default async function InterviewPage({ params }: InterviewPageProps) {
  const { sessionId } = await params;

  return (
    <main className="interview-shell">
      <header className="interview-header">
        <span className="wordmark">ARIES</span>
        <span className="session-code">session {sessionId.slice(0, 8)}</span>
      </header>
      <VoiceRoom sessionId={sessionId} />
    </main>
  );
}

