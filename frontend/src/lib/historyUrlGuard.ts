/**
 * Preserve Vue Router history state on every push/replace, and send
 * `origin + undefined` navigations to `/` instead of a broken host.
 */
import { APP_BASE_PATH, isBrokenUndefinedUrl, sanitizeNavigationUrl } from "./appUrl";

let installed = false;

function mergeHistoryState(data: unknown): unknown {
  if (data === null || typeof data !== "object") {
    return data;
  }
  const incoming = { ...(data as Record<string, unknown>) };
  const existing = window.history.state;
  const previous =
    existing !== null && typeof existing === "object" ? { ...(existing as Record<string, unknown>) } : {};
  const merged = { ...previous, ...incoming };
  const incomingCurrent = incoming.current;
  const currentMissing =
    incomingCurrent == null ||
    (typeof incomingCurrent === "string" && isBrokenUndefinedUrl(incomingCurrent));
  if (currentMissing) {
    const previousCurrent = previous.current;
    merged.current =
      typeof previousCurrent === "string" && !isBrokenUndefinedUrl(previousCurrent)
        ? previousCurrent
        : APP_BASE_PATH;
  }
  return merged;
}

export function installHistoryUrlGuard(): void {
  if (typeof window === "undefined" || installed) {
    return;
  }
  installed = true;

  const originalPush = History.prototype.pushState;
  History.prototype.pushState = function patchedPushState(
    data: unknown,
    unused: string,
    url?: string | URL | null,
  ): void {
    const state = mergeHistoryState(data);
    if (arguments.length >= 3) {
      originalPush.call(this, state, unused, sanitizeNavigationUrl(url) as string | URL | null | undefined);
      return;
    }
    originalPush.call(this, state, unused);
  };

  const originalReplace = History.prototype.replaceState;
  History.prototype.replaceState = function patchedReplaceState(
    data: unknown,
    unused: string,
    url?: string | URL | null,
  ): void {
    const state = mergeHistoryState(data);
    if (arguments.length >= 3) {
      originalReplace.call(this, state, unused, sanitizeNavigationUrl(url) as string | URL | null | undefined);
      return;
    }
    originalReplace.call(this, state, unused);
  };

  try {
    const assign = window.location.assign.bind(window.location);
    const replace = window.location.replace.bind(window.location);
    window.location.assign = (url: string | URL): void => {
      assign(sanitizeNavigationUrl(url) as string | URL);
    };
    window.location.replace = (url: string | URL): void => {
      replace(sanitizeNavigationUrl(url) as string | URL);
    };
  } catch {
    // Some browsers freeze Location methods.
  }

  const originalOpen = window.open.bind(window);
  window.open = function patchedOpen(
    url?: string | URL,
    target?: string,
    features?: string,
  ): Window | null {
    if (url === undefined) {
      return originalOpen(url, target, features);
    }
    return originalOpen(sanitizeNavigationUrl(url) as string | URL, target, features);
  };
}
