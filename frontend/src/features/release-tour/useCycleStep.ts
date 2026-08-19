import { ref, type Ref } from "vue";
import { useIntervalFn } from "@vueuse/core";

/**
 * Cycles 0..length-1 on an interval so a tour visual can loop through
 * realistic states. Pauses itself when the tab is hidden.
 */
export function useCycleStep(length: number, intervalMs = 1200): Ref<number> {
  const step = ref(0);

  useIntervalFn(
    () => {
      if (typeof document !== "undefined" && document.hidden) return;
      step.value = (step.value + 1) % length;
    },
    intervalMs,
    { immediateCallback: false },
  );

  return step;
}
