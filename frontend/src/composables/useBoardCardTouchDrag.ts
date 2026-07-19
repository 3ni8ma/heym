import { onUnmounted, ref } from "vue";
import type { Ref } from "vue";

export const BOARD_CARD_TOUCH_DRAG_EVENT = "heym:board-card-touch-drag";

export type BoardCardTouchDragPhase = "start" | "move" | "end" | "cancel";

export interface BoardCardTouchDragDetail {
  phase: BoardCardTouchDragPhase;
  cardId: string;
  clientX: number;
  clientY: number;
}

interface UseBoardCardTouchDragOptions {
  cardId: () => string;
  enabled: () => boolean;
  sourceElement: Ref<HTMLElement | null>;
}

interface TouchPoint {
  clientX: number;
  clientY: number;
}

interface BoardCardTouchDragHandlers {
  onTouchStart: (event: TouchEvent) => void;
  onTouchMove: (event: TouchEvent) => void;
  onTouchEnd: (event: TouchEvent) => void;
  onTouchCancel: (event: TouchEvent) => void;
}

interface UseBoardCardTouchDragResult {
  handlers: BoardCardTouchDragHandlers;
  isTouchDragging: Ref<boolean>;
  consumeTouchDragClick: () => boolean;
}

const LONG_PRESS_MS = 300;
const MOVE_TOLERANCE_PX = 10;
const EDGE_SCROLL_ZONE_PX = 48;
const EDGE_SCROLL_STEP_PX = 18;
const CLICK_SUPPRESSION_MS = 700;
const captureOptions = { capture: true };

function findTouch(touches: TouchList, identifier: number): Touch | null {
  for (let index = 0; index < touches.length; index += 1) {
    const touch = touches.item(index);
    if (touch?.identifier === identifier) return touch;
  }
  return null;
}

export function useBoardCardTouchDrag(
  options: UseBoardCardTouchDragOptions,
): UseBoardCardTouchDragResult {
  const isTouchDragging = ref(false);
  let longPressTimer: ReturnType<typeof setTimeout> | null = null;
  let touchIdentifier: number | null = null;
  let startPoint: TouchPoint | null = null;
  let latestPoint: TouchPoint | null = null;
  let suppressClickUntil = 0;

  function clearLongPressTimer(): void {
    if (longPressTimer === null) return;
    clearTimeout(longPressTimer);
    longPressTimer = null;
  }

  function dispatchTouchDrag(phase: BoardCardTouchDragPhase, point: TouchPoint): void {
    window.dispatchEvent(
      new CustomEvent<BoardCardTouchDragDetail>(BOARD_CARD_TOUCH_DRAG_EVENT, {
        detail: {
          phase,
          cardId: options.cardId(),
          clientX: point.clientX,
          clientY: point.clientY,
        },
      }),
    );
  }

  function resetGesture(): void {
    clearLongPressTimer();
    window.removeEventListener("touchstart", onAdditionalTouchStart, captureOptions);
    isTouchDragging.value = false;
    touchIdentifier = null;
    startPoint = null;
    latestPoint = null;
  }

  function cancelGesture(): void {
    if (isTouchDragging.value && latestPoint) {
      dispatchTouchDrag("cancel", latestPoint);
      suppressClickUntil = Date.now() + CLICK_SUPPRESSION_MS;
    }
    resetGesture();
  }

  function scrollBoardAtEdge(point: TouchPoint): void {
    const canvas = options.sourceElement.value?.closest<HTMLElement>("[data-testid='board-canvas']");
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (point.clientX < rect.left + EDGE_SCROLL_ZONE_PX) {
      canvas.scrollLeft -= EDGE_SCROLL_STEP_PX;
    } else if (point.clientX > rect.right - EDGE_SCROLL_ZONE_PX) {
      canvas.scrollLeft += EDGE_SCROLL_STEP_PX;
    }
  }

  function onAdditionalTouchStart(event: TouchEvent): void {
    if (touchIdentifier !== null && event.touches.length !== 1) cancelGesture();
  }

  function onTouchStart(event: TouchEvent): void {
    if (!options.enabled() || event.touches.length !== 1) {
      cancelGesture();
      return;
    }
    const target = event.target;
    if (
      target instanceof Element &&
      target.closest("button, input, textarea, a, select, [contenteditable='true']")
    ) {
      return;
    }
    const touch = event.touches.item(0);
    if (!touch) return;

    cancelGesture();
    touchIdentifier = touch.identifier;
    startPoint = { clientX: touch.clientX, clientY: touch.clientY };
    latestPoint = startPoint;
    window.addEventListener("touchstart", onAdditionalTouchStart, captureOptions);
    longPressTimer = setTimeout(() => {
      longPressTimer = null;
      if (!options.enabled() || touchIdentifier === null || !latestPoint) {
        resetGesture();
        return;
      }
      isTouchDragging.value = true;
      suppressClickUntil = Number.POSITIVE_INFINITY;
      dispatchTouchDrag("start", latestPoint);
    }, LONG_PRESS_MS);
  }

  function onTouchMove(event: TouchEvent): void {
    if (touchIdentifier === null || !startPoint) return;
    if (event.touches.length !== 1) {
      cancelGesture();
      return;
    }
    const touch = findTouch(event.touches, touchIdentifier);
    if (!touch) {
      cancelGesture();
      return;
    }

    const point = { clientX: touch.clientX, clientY: touch.clientY };
    latestPoint = point;
    if (!isTouchDragging.value) {
      const distance = Math.hypot(
        point.clientX - startPoint.clientX,
        point.clientY - startPoint.clientY,
      );
      if (distance > MOVE_TOLERANCE_PX) resetGesture();
      return;
    }

    if (event.cancelable) event.preventDefault();
    scrollBoardAtEdge(point);
    dispatchTouchDrag("move", point);
  }

  function onTouchEnd(event: TouchEvent): void {
    if (touchIdentifier === null) return;
    const touch = findTouch(event.changedTouches, touchIdentifier);
    if (!isTouchDragging.value) {
      resetGesture();
      return;
    }
    if (!touch) {
      cancelGesture();
      return;
    }

    if (event.cancelable) event.preventDefault();
    event.stopPropagation();
    const point = { clientX: touch.clientX, clientY: touch.clientY };
    dispatchTouchDrag("end", point);
    suppressClickUntil = Date.now() + CLICK_SUPPRESSION_MS;
    resetGesture();
  }

  function onTouchCancel(_event: TouchEvent): void {
    cancelGesture();
  }

  function consumeTouchDragClick(): boolean {
    if (Date.now() > suppressClickUntil) return false;
    suppressClickUntil = 0;
    return true;
  }

  onUnmounted(cancelGesture);

  return {
    handlers: { onTouchStart, onTouchMove, onTouchEnd, onTouchCancel },
    isTouchDragging,
    consumeTouchDragClick,
  };
}
