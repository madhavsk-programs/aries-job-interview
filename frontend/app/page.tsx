import StartInterviewButton from "@/components/StartInterviewButton";


export default function HomePage() {
  return (
    <main className="shell">
      <nav className="nav">
        <span className="wordmark">ARIES</span>
        <span className="phase-label">Complete · adaptive voice + evidence</span>
      </nav>

      <section className="hero">
        <p className="kicker">VOICE INTERVIEW PRACTICE</p>
        <h1>Practice interviews that talk back.</h1>
        <p className="lede">
          Every question is chosen from the answer before it, and every score points
          back at the moment in the transcript that produced it.
        </p>
        <StartInterviewButton />
      </section>

      <section className="product-panel" aria-label="Product preview">
        <div className="panel-meta">
          <span className="live-indicator"><i /> live session</span>
          <span>00:00:00</span>
        </div>
        <div className="turn">
          <span className="speaker">Q</span>
          <p>Walk me through how you&rsquo;d design a rate limiter for a public API.</p>
        </div>
        <div className="turn">
          <span className="speaker">A</span>
          <div>
            <p>
              I&rsquo;d start with a token bucket per client, stored in Redis so
              it survives a restart&mdash;
            </p>
            <div className="evidence-marker">
              <div className="evidence-head">
                <span className="evidence-competency">system design</span>
                <span className="evidence-score">0.81</span>
              </div>
              <p className="evidence-quote">
                &ldquo;token bucket per client, stored in Redis&rdquo;
              </p>
              <p className="evidence-note">
                probing deeper<span className="evidence-latency">340ms</span>
              </p>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}

