/**
 * Join a window origin with an in-app path. Prevents `origin + undefined` → "...comundefined".
 */
export function joinOriginAndPath(origin: string, path: string | undefined | null): string {
  const normalizedOrigin = origin.replace(/\/$/, "");
  const rawPath = path == null || path === "" ? "/" : path;
  const normalizedPath = rawPath.startsWith("/") ? rawPath : `/${rawPath}`;
  return `${normalizedOrigin}${normalizedPath}`;
}

const GLUED_HOST_RE = /https?:\/\/[^/\s?#]+(?:undefined|null)(?:[/:?#]|$)/i;
const GLUED_HOST_NO_PROTOCOL_RE = /(?:^|\/\/)[^/\s?#]*[a-z0-9](?:undefined|null)(?:[/:?#]|$)/i;
const PATH_OR_QUERY_TOKEN_RE = /(?:^|[/?#=&])(?:undefined|null)(?:[/?#=&]|$)/;

export const APP_BASE_PATH = "/";

/** True for JS-coerced `origin + undefined` and `/undefined` path tokens. */
export function isBrokenUndefinedUrl(url: string): boolean {
  if (url === "undefined" || url === "null") {
    return true;
  }
  if (!url.includes("undefined") && !url.includes("null")) {
    return false;
  }
  return (
    GLUED_HOST_RE.test(url) || GLUED_HOST_NO_PROTOCOL_RE.test(url) || PATH_OR_QUERY_TOKEN_RE.test(url)
  );
}

/** Replace a coerced-undefined navigation target with the app base. */
export function sanitizeNavigationUrl(url: string | URL | null | undefined): string | URL | null | undefined {
  if (url == null) {
    return url;
  }
  return isBrokenUndefinedUrl(String(url)) ? APP_BASE_PATH : url;
}
