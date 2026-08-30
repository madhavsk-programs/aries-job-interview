export type VoiceSession = {
  session_id: string;
  room_name: string;
  server_url: string;
  participant_token: string;
  access_token: string;
  interview_mode: "adaptive" | "linkedin_scripted";
  competency_plan: Array<{
    competency: string;
    text: string;
    difficulty: number;
    question_type: string;
  }>;
};

export type ResumeParseResult = {
  candidate_name: string;
  suggested_role: string;
  professional_summary: string;
  skills: string[];
  experience_highlights: string[];
  education: string[];
  resume_text: string;
  page_count: number;
  parser: "ollama" | "local-fallback";
};


export const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000";

async function responseError(response: Response, fallback: string): Promise<string> {
  const raw = await response.text();
  if (!raw) return fallback;
  try {
    const payload = JSON.parse(raw) as { detail?: string };
    return payload.detail || fallback;
  } catch {
    return raw;
  }
}

export async function parseResume(file: File): Promise<ResumeParseResult> {
  const body = new FormData();
  body.append("file", file);

  const response = await fetch(`${apiBaseUrl}/api/resume/parse`, {
    method: "POST",
    body,
  });

  if (!response.ok) {
    throw new Error(await responseError(response, "The resume could not be read."));
  }

  return (await response.json()) as ResumeParseResult;
}


export async function createVoiceSession(
  sessionId: string,
  setup: {
    participant_name?: string;
    role_focus?: string;
    resume_text?: string;
    job_description?: string;
    interview_mode?: "adaptive" | "linkedin_scripted";
  } = {},
): Promise<VoiceSession> {
  const response = await fetch(`${apiBaseUrl}/api/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      participant_name: setup.participant_name || "Candidate",
      role_focus: setup.role_focus || null,
      resume_text: setup.resume_text || null,
      job_description: setup.job_description || null,
      interview_mode: setup.interview_mode || "linkedin_scripted",
    }),
  });

  if (!response.ok) {
    throw new Error(await responseError(response, "Unable to create a voice session."));
  }

  const session = (await response.json()) as VoiceSession;
  const structuredPlan = session.competency_plan?.length === 8 &&
    session.competency_plan.every((question) => question.question_type === "linkedin_scripted");
  if (session.interview_mode !== "linkedin_scripted" || !structuredPlan) {
    throw new Error(
      "The interview service is still running an older version. Restart the API and voice worker, refresh this page, and begin a new interview.",
    );
  }
  if (typeof window !== "undefined") {
    sessionStorage.setItem(`aries:${session.session_id}`, JSON.stringify(session));
  }
  return session;
}

export function loadVoiceSession(sessionId: string): VoiceSession | null {
  if (typeof window === "undefined") return null;
  const raw = sessionStorage.getItem(`aries:${sessionId}`);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as VoiceSession;
  } catch {
    return null;
  }
}

export async function sessionFetch(
  sessionId: string,
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const session = loadVoiceSession(sessionId);
  if (!session?.access_token) throw new Error("This session link is not available in this browser.");
  return fetch(`${apiBaseUrl}/api/sessions/${sessionId}/${path}`, {
    ...init,
    headers: {
      ...(init?.headers || {}),
      Authorization: `Bearer ${session.access_token}`,
    },
  });
}
