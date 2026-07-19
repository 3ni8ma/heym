interface UseDialogBackHistoryOptions {
  enabled: () => boolean;
  isOpen: () => boolean;
  onBack: () => void;
}

interface UseDialogBackHistoryResult {
  pushDialogHistoryEntry: () => void;
  removeDialogHistoryEntry: () => void;
}

const DIALOG_HISTORY_STATE_KEY = "heymDialog";
const captureOptions = { capture: true };

/** Manages a same-URL history entry that lets browser Back dismiss one dialog. */
export function useDialogBackHistory(
  options: UseDialogBackHistoryOptions,
): UseDialogBackHistoryResult {
  const dialogHistoryId = `dialog-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  let ownsHistoryEntry = false;
  let dialogHistoryHref: string | null = null;

  function currentHistoryBelongsToDialog(): boolean {
    const state = window.history.state as Record<string, unknown> | null;
    return state?.[DIALOG_HISTORY_STATE_KEY] === dialogHistoryId;
  }

  function handlePopState(event: PopStateEvent): void {
    if (!ownsHistoryEntry || !options.isOpen()) return;
    ownsHistoryEntry = false;
    dialogHistoryHref = null;
    window.removeEventListener("popstate", handlePopState, captureOptions);
    event.stopImmediatePropagation();
    options.onBack();
  }

  function pushDialogHistoryEntry(): void {
    if (!options.enabled() || ownsHistoryEntry) return;
    const currentState = window.history.state;
    const state =
      currentState !== null && typeof currentState === "object"
        ? (currentState as Record<string, unknown>)
        : {};
    dialogHistoryHref = window.location.href;
    window.history.pushState(
      { ...state, [DIALOG_HISTORY_STATE_KEY]: dialogHistoryId },
      "",
      dialogHistoryHref,
    );
    ownsHistoryEntry = true;
    // Capture runs before Vue Router and the app-wide overlay handler. The pushed URL is
    // identical, so consuming it closes this dialog without changing the active route.
    window.addEventListener("popstate", handlePopState, captureOptions);
  }

  function removeDialogHistoryEntry(): void {
    window.removeEventListener("popstate", handlePopState, captureOptions);
    if (!ownsHistoryEntry) return;
    ownsHistoryEntry = false;
    const pushedHref = dialogHistoryHref;
    dialogHistoryHref = null;
    if (!currentHistoryBelongsToDialog()) return;
    // Navigating away (e.g. Open live → editor) already replaced/left this entry. Calling
    // history.back() here would undo that route and land back on the board (`/` pathname).
    if (pushedHref !== null && window.location.href !== pushedHref) return;

    // The global overlay handler must ignore the pop used only to remove this dialog's
    // same-URL history entry after a close button, backdrop click, or Escape press.
    document.body.dataset.heymIgnoreNextOverlayDismiss = "true";
    window.history.back();
  }

  return { pushDialogHistoryEntry, removeDialogHistoryEntry };
}
