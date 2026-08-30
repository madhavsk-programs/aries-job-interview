"use client";

import { ChangeEvent, FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { createVoiceSession, parseResume } from "@/lib/livekit-client";

const MAX_PDF_BYTES = 5 * 1024 * 1024;

export default function SetupPage() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [uploadStatus, setUploadStatus] = useState("");
  const [name, setName] = useState("Candidate");
  const [role, setRole] = useState("");
  const [job, setJob] = useState("");
  const [summary, setSummary] = useState("");
  const [skills, setSkills] = useState("");
  const [experience, setExperience] = useState("");
  const [education, setEducation] = useState("");
  const [resumeText, setResumeText] = useState("");

  async function uploadResume(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;

    setError("");
    setUploadStatus("");
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      setError("Please choose a PDF resume.");
      event.target.value = "";
      return;
    }
    if (file.size > MAX_PDF_BYTES) {
      setError("The PDF must be 5 MB or smaller.");
      event.target.value = "";
      return;
    }

    setUploading(true);
    try {
      const profile = await parseResume(file);
      if (profile.candidate_name) setName(profile.candidate_name);
      if (profile.suggested_role) setRole(profile.suggested_role);
      setSummary(profile.professional_summary);
      setSkills(profile.skills.join(", "));
      setExperience(profile.experience_highlights.join("\n"));
      setEducation(profile.education.join("\n"));
      setResumeText(profile.resume_text);

      const parserNote = profile.parser === "local-fallback"
        ? " Basic extraction was used, so review the fields below."
        : " The fields below are ready for review.";
      setUploadStatus(
        `${file.name} · ${profile.page_count} page${profile.page_count === 1 ? "" : "s"} read.${parserNote}`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The resume could not be read.");
    } finally {
      setUploading(false);
      event.target.value = "";
    }
  }

  function interviewContext() {
    return [
      summary && `Professional summary:\n${summary}`,
      skills && `Key skills:\n${skills}`,
      experience && `Experience highlights:\n${experience}`,
      education && `Education:\n${education}`,
      resumeText && `Full extracted resume text:\n${resumeText}`,
    ].filter(Boolean).join("\n\n").slice(0, 30_000);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const sessionId = crypto.randomUUID();
    try {
      await createVoiceSession(sessionId, {
        participant_name: name || "Candidate",
        role_focus: role,
        resume_text: interviewContext(),
        job_description: job,
        interview_mode: "linkedin_scripted",
      });
      router.push(`/interview/${sessionId}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create the interview.");
      setBusy(false);
    }
  }

  return (
    <main className="shell setup-shell">
      <nav className="nav"><span className="wordmark">ARIES</span><span className="phase-label">Interview setup</span></nav>
      <section className="setup-card">
        <p className="kicker">PERSONALIZE THE PRACTICE</p>
        <h1>Build your interview.</h1>
        <p className="lede">Upload a resume and ARIES will fill the setup for you. Everything remains editable before the interview starts.</p>
        <form onSubmit={submit} className="setup-form">
          <section className="resume-upload" aria-busy={uploading}>
            <div>
              <strong>{uploading ? "Reading your resume…" : "Upload resume PDF"}</strong>
              <span>One text-based PDF, up to 5 MB and 15 pages.</span>
            </div>
            <input
              type="file"
              accept="application/pdf,.pdf"
              aria-label="Upload resume PDF"
              onChange={uploadResume}
              disabled={uploading || busy}
            />
          </section>
          <p className="privacy-note">The file is read in memory and is not saved by ARIES. Its text is organized by Ollama on this computer and is not sent to a commercial AI API.</p>
          {uploadStatus ? <p className="resume-status">✓ {uploadStatus}</p> : null}

          <div className="form-section-title"><span>Review the extracted details</span><small>or fill them manually</small></div>
          <label>Name<input name="name" maxLength={80} value={name} onChange={(event) => setName(event.target.value)} required /></label>
          <label>Target role<input name="role" maxLength={160} value={role} onChange={(event) => setRole(event.target.value)} placeholder="Senior backend engineer" /></label>
          <label>Key skills<textarea name="skills" rows={3} maxLength={4000} value={skills} onChange={(event) => setSkills(event.target.value)} placeholder="Python, FastAPI, PostgreSQL…" /></label>
          <label>Professional summary<textarea name="summary" rows={4} maxLength={6000} value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="A short overview of your experience…" /></label>
          <label>Experience highlights<textarea name="experience" rows={5} maxLength={10000} value={experience} onChange={(event) => setExperience(event.target.value)} placeholder="One achievement per line…" /></label>
          <label>Education<textarea name="education" rows={3} maxLength={4000} value={education} onChange={(event) => setEducation(event.target.value)} placeholder="Degree, institution, graduation year…" /></label>
          <label>Job description <small className="optional-label">optional</small><textarea name="job" rows={7} maxLength={30000} value={job} onChange={(event) => setJob(event.target.value)} placeholder="Paste the role description for more targeted questions…" /></label>

          {resumeText ? (
            <details className="resume-details">
              <summary>View or edit full extracted resume text</summary>
              <textarea aria-label="Full extracted resume text" rows={10} maxLength={30000} value={resumeText} onChange={(event) => setResumeText(event.target.value)} />
            </details>
          ) : null}

          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <button className="primary-action" disabled={busy || uploading}>{busy ? "Preparing interview…" : uploading ? "Reading resume…" : "Begin interview"}</button>
        </form>
      </section>
    </main>
  );
}
