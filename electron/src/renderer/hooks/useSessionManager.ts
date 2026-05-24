export interface SessionMeta {
  id: string;
  title: string;
  createdAt: string;
  lastActiveAt: string;
  threadCount: number;
  preview: string;
  pinned?: boolean;
}

const SESSIONS_KEY = "spark_sessions";
const ACTIVE_KEY = "spark_active_session";

function genId(): string {
  return `s_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
}

export function loadSessions(): SessionMeta[] {
  try {
    return JSON.parse(localStorage.getItem(SESSIONS_KEY) || "[]");
  } catch { return []; }
}

function saveSessions(list: SessionMeta[]) {
  localStorage.setItem(SESSIONS_KEY, JSON.stringify(list.slice(0, 50)));
}

export function getActiveSessionId(): string {
  let id = localStorage.getItem(ACTIVE_KEY);
  if (!id) {
    id = genId();
    localStorage.setItem(ACTIVE_KEY, id);
    const sessions = loadSessions();
    sessions.unshift({
      id,
      title: "",
      createdAt: new Date().toISOString(),
      lastActiveAt: new Date().toISOString(),
      threadCount: 0,
      preview: "",
    });
    saveSessions(sessions);
  }
  return id;
}

export function threadStorageKey(sessionId: string): string {
  return `spark_threads_${sessionId}`;
}

export function startNewSession(): string {
  const id = genId();
  localStorage.setItem(ACTIVE_KEY, id);
  const sessions = loadSessions();
  sessions.unshift({
    id,
    title: "",
    createdAt: new Date().toISOString(),
    lastActiveAt: new Date().toISOString(),
    threadCount: 0,
    preview: "",
  });
  saveSessions(sessions);
  return id;
}

export function switchToSession(sessionId: string) {
  localStorage.setItem(ACTIVE_KEY, sessionId);
}

export function updateSession(sessionId: string, updates: Partial<Omit<SessionMeta, "id">>) {
  const sessions = loadSessions();
  const idx = sessions.findIndex(s => s.id === sessionId);
  if (idx >= 0) {
    sessions[idx] = { ...sessions[idx], ...updates, lastActiveAt: new Date().toISOString() };
  } else {
    sessions.unshift({
      id: sessionId,
      title: updates.title || "",
      createdAt: new Date().toISOString(),
      lastActiveAt: new Date().toISOString(),
      threadCount: updates.threadCount || 0,
      preview: updates.preview || "",
    });
  }
  saveSessions(sessions);
}

export function deleteSession(sessionId: string) {
  const sessions = loadSessions().filter(s => s.id !== sessionId);
  saveSessions(sessions);
  localStorage.removeItem(threadStorageKey(sessionId));
}

export function pinSession(sessionId: string, pinned: boolean) {
  const sessions = loadSessions();
  const idx = sessions.findIndex(s => s.id === sessionId);
  if (idx >= 0) {
    sessions[idx].pinned = pinned;
    saveSessions(sessions);
  }
}
