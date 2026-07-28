<script setup lang="ts">
import { useVueFlow } from "@vue-flow/core";

/** Below this, the gesture counts as a click, not a move (see AgentMemoryGraphFlowPane.vue). */
const DRAG_MOVEMENT_THRESHOLD_PX = 1.5;

const { findNode, updateNode } = useVueFlow();

let anchorId: string | null = null;
let startPositions = new Map<string, { x: number; y: number }>();

/** Vue Flow only moves the node under the cursor; recording the group's start positions lets
 * updateGroupDrag re-apply the anchor's delta to the rest, preserving relative spacing. */
function startGroupDrag(draggedNodeId: string, groupIds: string[]): void {
  anchorId = draggedNodeId;
  startPositions = new Map();
  for (const id of new Set([draggedNodeId, ...groupIds])) {
    const node = findNode(id);
    if (node) {
      startPositions.set(id, { x: node.position.x, y: node.position.y });
    }
  }
}

function anchorDelta(): { dx: number; dy: number } | null {
  if (anchorId === null) {
    return null;
  }
  const start = startPositions.get(anchorId);
  const node = findNode(anchorId);
  if (!start || !node) {
    return null;
  }
  return { dx: node.position.x - start.x, dy: node.position.y - start.y };
}

function updateGroupDrag(draggedNodeId: string): void {
  if (anchorId !== draggedNodeId) {
    return;
  }
  const delta = anchorDelta();
  if (!delta) {
    return;
  }
  for (const [id, start] of startPositions) {
    if (id === anchorId) {
      continue;
    }
    updateNode(id, { position: { x: start.x + delta.dx, y: start.y + delta.dy } });
  }
}

function endGroupDrag(): { movedIds: string[]; moved: boolean } {
  const delta = anchorDelta();
  const moved =
    delta !== null && Math.hypot(delta.dx, delta.dy) > DRAG_MOVEMENT_THRESHOLD_PX;
  const movedIds = [...startPositions.keys()];
  anchorId = null;
  startPositions = new Map();
  return { movedIds, moved };
}

defineExpose({ startGroupDrag, updateGroupDrag, endGroupDrag });
</script>

<template>
  <span
    class="sr-only"
    aria-hidden="true"
  />
</template>
