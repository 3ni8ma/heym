export const RELEASE_TOUR_STORAGE_KEY = "heym-release-tour-seen";

/** Completed tours as versioned release ids, e.g. `["2026.08@r1"]`. */
export function readSeenReleaseIds(): string[] {
  if (typeof window === "undefined") return [];

  try {
    const raw = window.localStorage.getItem(RELEASE_TOUR_STORAGE_KEY);
    if (!raw) return [];

    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];

    return parsed.filter((value): value is string => typeof value === "string");
  } catch {
    return [];
  }
}

export function writeSeenReleaseIds(releaseIds: readonly string[]): void {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(RELEASE_TOUR_STORAGE_KEY, JSON.stringify(releaseIds));
  } catch {
    // Ignore storage failures so the tour still closes for this session.
  }
}

export function appendSeenReleaseId(versionedReleaseId: string): string[] {
  const seen = readSeenReleaseIds();
  if (seen.includes(versionedReleaseId)) return seen;

  const next = [...seen, versionedReleaseId];
  writeSeenReleaseIds(next);
  return next;
}
