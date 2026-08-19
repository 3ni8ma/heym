import {
  computed,
  onUnmounted,
  ref,
  toValue,
  watch,
  type ComputedRef,
  type MaybeRefOrGetter,
} from "vue";

import { RELEASE_REGISTRY } from "@/features/release-tour/releaseRegistry";
import { buildReleaseTours, selectPendingReleaseTour } from "@/features/release-tour/releaseTourMapper";
import { appendSeenReleaseId, readSeenReleaseIds } from "@/features/release-tour/releaseTourStorage";
import type { ReleaseTour } from "@/features/release-tour/releaseTour.types";

/** Lets the page settle before the popup slides in. */
const AUTO_OPEN_DELAY_MS = 900;

export interface UseReleaseTourResult {
  activeTour: ComputedRef<ReleaseTour | null>;
  isOpen: ComputedRef<boolean>;
  hasUnseenRelease: ComputedRef<boolean>;
  openTour: () => void;
  completeTour: () => void;
}

/**
 * Wires the release registry to persisted "seen" state. `eligible` is the
 * host page's own visibility rule; the tour never auto-opens without it.
 */
export function useReleaseTour(eligible: MaybeRefOrGetter<boolean>): UseReleaseTourResult {
  const tours = buildReleaseTours(RELEASE_REGISTRY);
  const seenReleaseIds = ref<string[]>(readSeenReleaseIds());
  const isOpen = ref(false);
  let autoOpenTimeoutId: number | null = null;

  const pendingTour = computed(() => selectPendingReleaseTour(tours, seenReleaseIds.value));
  /** Falls back to the newest tour so the launcher can replay an already-seen release. */
  const activeTour = computed<ReleaseTour | null>(() => pendingTour.value ?? tours[0] ?? null);
  const hasUnseenRelease = computed(() => pendingTour.value !== null);

  function clearAutoOpenTimeout(): void {
    if (autoOpenTimeoutId === null) return;
    window.clearTimeout(autoOpenTimeoutId);
    autoOpenTimeoutId = null;
  }

  function openTour(): void {
    clearAutoOpenTimeout();
    if (!activeTour.value) return;
    isOpen.value = true;
  }

  function completeTour(): void {
    clearAutoOpenTimeout();
    const tour = activeTour.value;
    if (tour) {
      seenReleaseIds.value = appendSeenReleaseId(tour.versionedReleaseId);
    }
    isOpen.value = false;
  }

  watch(
    () => toValue(eligible) && pendingTour.value !== null,
    (shouldAutoOpen) => {
      clearAutoOpenTimeout();
      if (!shouldAutoOpen || isOpen.value) return;

      autoOpenTimeoutId = window.setTimeout(() => {
        autoOpenTimeoutId = null;
        isOpen.value = true;
      }, AUTO_OPEN_DELAY_MS);
    },
    { immediate: true },
  );

  onUnmounted(clearAutoOpenTimeout);

  return {
    activeTour,
    isOpen: computed(() => isOpen.value),
    hasUnseenRelease,
    openTour,
    completeTour,
  };
}
