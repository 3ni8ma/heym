<script setup lang="ts">
import { computed, ref } from "vue";
import { Background } from "@vue-flow/background";
import { VueFlow } from "@vue-flow/core";
import type { Edge, Node } from "@vue-flow/core";

import AgentMemoryGraphEdge from "@/components/Dialogs/AgentMemoryGraphEdge.vue";
import AgentMemoryGraphForceSim from "./AgentMemoryGraphForceSim.vue";
import AgentMemoryGraphDragGroup from "./AgentMemoryGraphDragGroup.vue";
import AgentMemoryGraphFlowHotkeys from "./AgentMemoryGraphFlowHotkeys.vue";
import AgentMemoryFlowViewportFitter from "./AgentMemoryFlowViewportFitter.vue";

const props = withDefaults(
  defineProps<{
    flowId: string;
    nodes: Node[];
    edges: Edge[];
    hotkeysEnabled?: boolean;
    selectedNodeId?: string | null;
    /** The selected hub plus its directly connected leaves. Dragging the hub moves this whole
     * set together; dragging any other node (a leaf included) moves only that node. */
    selectionGroupIds?: string[];
  }>(),
  { hotkeysEnabled: true, selectedNodeId: null, selectionGroupIds: () => [] },
);

const emit = defineEmits<{
  nodeClick: [payload: { node: Node }];
  edgeClick: [payload: { edge: Edge }];
  edgeMouseEnter: [payload: { edge: Edge }];
  edgeMouseLeave: [payload: { edge: Edge }];
  paneClick: [];
  deleteSelection: [payload: { nodeIds: string[]; edgeIds: string[] }];
}>();

const fitterRef = ref<InstanceType<typeof AgentMemoryFlowViewportFitter> | null>(null);
const simRef = ref<InstanceType<typeof AgentMemoryGraphForceSim> | null>(null);
const dragGroupRef = ref<InstanceType<typeof AgentMemoryGraphDragGroup> | null>(null);

const simLinks = computed(() => props.edges.map((e) => ({ source: e.source, target: e.target })));

/** Nodes the sim must leave alone, so a drag sticks instead of being pulled back by the next
 * reheat. Reset by tidy(). */
const pinnedNodeIds = ref<string[]>([]);
let pinsBeforeDrag: string[] = [];

function dragGroupIdsFor(nodeId: string): string[] {
  return nodeId === props.selectedNodeId ? props.selectionGroupIds : [nodeId];
}

function handleNodeDragStart(payload: { node: Node }): void {
  const groupIds = dragGroupIdsFor(payload.node.id);
  pinsBeforeDrag = [...pinnedNodeIds.value];
  dragGroupRef.value?.startGroupDrag(payload.node.id, groupIds);
  // Pin up front, not on drop: mid-drag the sim would otherwise fight handleNodeDrag's offsets.
  pinnedNodeIds.value = [...new Set([...pinnedNodeIds.value, payload.node.id, ...groupIds])];
}

function handleNodeDrag(payload: { node: Node }): void {
  dragGroupRef.value?.updateGroupDrag(payload.node.id);
}

function handleNodeDragStop(): void {
  const result = dragGroupRef.value?.endGroupDrag();
  if (result && !result.moved) {
    pinnedNodeIds.value = pinsBeforeDrag;
  }
  pinsBeforeDrag = [];
  simRef.value?.reheat();
}

async function fitViewAfterLoad(opts?: { padding?: number; duration?: number }): Promise<void> {
  await fitterRef.value?.fitViewAfterLoad(opts);
}

async function focusNodes(ids: string[]): Promise<void> {
  await fitterRef.value?.focusOnNodes(ids);
}

function reheat(): void {
  simRef.value?.reheat();
}

function snapshotPositions(): Map<string, { x: number; y: number }> {
  return simRef.value?.snapshotPositions() ?? new Map();
}

/** Releases hand-placed nodes back to the simulation, then re-settles. */
function tidy(): void {
  pinnedNodeIds.value = [];
  simRef.value?.reheat();
}

defineExpose({ fitViewAfterLoad, focusNodes, reheat, snapshotPositions, tidy });
</script>

<template>
  <VueFlow
    :id="flowId"
    class="agent-memory-vue-flow flex-1 min-h-[200px] lg:min-h-0 w-full h-full bg-background"
    :nodes="nodes"
    :edges="edges"
    :delete-key-code="null"
    :fit-view-on-init="true"
    :min-zoom="0.2"
    :max-zoom="1.5"
    @node-click="emit('nodeClick', $event)"
    @edge-click="emit('edgeClick', $event)"
    @edge-mouse-enter="emit('edgeMouseEnter', $event)"
    @edge-mouse-leave="emit('edgeMouseLeave', $event)"
    @pane-click="emit('paneClick')"
    @node-drag-start="handleNodeDragStart"
    @node-drag="handleNodeDrag"
    @node-drag-stop="handleNodeDragStop"
  >
    <AgentMemoryFlowViewportFitter ref="fitterRef" />
    <AgentMemoryGraphForceSim
      ref="simRef"
      :links="simLinks"
      :active="nodes.length > 0"
      :focus-node-id="selectedNodeId"
      :pinned-ids="pinnedNodeIds"
    />
    <AgentMemoryGraphDragGroup ref="dragGroupRef" />
    <AgentMemoryGraphFlowHotkeys
      :enabled="hotkeysEnabled"
      @delete-selection="emit('deleteSelection', $event)"
    />
    <template #node-default="slotProps">
      <slot
        name="node-default"
        v-bind="slotProps"
      />
    </template>
    <template #edge-agentMemory="edgeSlotProps">
      <AgentMemoryGraphEdge v-bind="edgeSlotProps" />
    </template>
    <Background pattern-color="hsl(var(--muted-foreground) / 0.18)" />
  </VueFlow>
</template>
