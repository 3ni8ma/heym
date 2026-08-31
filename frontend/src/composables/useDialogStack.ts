import { computed, onScopeDispose, ref, watch, type ComputedRef } from "vue";

/** Ids of the currently open dialogs, bottom-most first. */
const dialogStack = ref<symbol[]>([]);

function syncBodyScrollLock(): void {
  document.body.style.overflow = dialogStack.value.length > 0 ? "hidden" : "";
}

export function addToDialogStack(dialogId: symbol): void {
  dialogStack.value = [...dialogStack.value.filter((id) => id !== dialogId), dialogId];
  syncBodyScrollLock();
}

export function removeFromDialogStack(dialogId: symbol): void {
  dialogStack.value = dialogStack.value.filter((id) => id !== dialogId);
  syncBodyScrollLock();
}

export function isTopmostDialog(dialogId: symbol): boolean {
  const stack = dialogStack.value;
  return stack[stack.length - 1] === dialogId;
}

export function isBottommostDialog(dialogId: symbol): boolean {
  return dialogStack.value[0] === dialogId;
}

export function dialogStackPosition(dialogId: symbol): number {
  return Math.max(dialogStack.value.indexOf(dialogId), 0);
}

export function hasOpenDialog(): boolean {
  return dialogStack.value.length > 0;
}

const OVERLAY_BASE_Z_INDEX = 50;
const OVERLAY_Z_INDEX_STEP = 10;

/** Every overlay in the stack reads its depth from the same scale, so whatever
 *  opened last paints on top of what it was opened from. */
export function overlayZIndex(dialogId: symbol): number {
  return OVERLAY_BASE_Z_INDEX + dialogStackPosition(dialogId) * OVERLAY_Z_INDEX_STEP;
}

/** Joins an overlay that is not a `Dialog` - a bottom sheet - to the same stack,
 *  so a dialog opened from it stacks above instead of behind. */
export function useDialogStackLayer(isOpen: () => boolean): ComputedRef<number> {
  const layerId = Symbol("overlay-layer");

  watch(
    isOpen,
    (open) => {
      if (open) {
        addToDialogStack(layerId);
      } else {
        removeFromDialogStack(layerId);
      }
    },
    { immediate: true },
  );

  onScopeDispose(() => removeFromDialogStack(layerId));

  return computed(() => overlayZIndex(layerId));
}
