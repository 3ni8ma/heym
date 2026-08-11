<script setup lang="ts">
import Label from "@/components/ui/Label.vue";
import { heymEventNameOptions } from "../operationOptions";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const { selectedNode, updateNodeData } = usePropertiesPanelContext();

function isSelected(value: string): boolean {
  const selected = selectedNode.value?.data.eventNames;
  return Array.isArray(selected) && selected.includes(value);
}

function toggleEvent(value: string): void {
  const current = selectedNode.value?.data.eventNames;
  const selected = Array.isArray(current) ? [...current] : [];
  const index = selected.indexOf(value);
  if (index >= 0) {
    selected.splice(index, 1);
  } else {
    selected.push(value);
  }
  updateNodeData("eventNames", selected);
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Events</Label>
      <div class="space-y-1">
        <label
          v-for="option in heymEventNameOptions"
          :key="option.value"
          class="flex items-center gap-2 text-sm"
        >
          <input
            type="checkbox"
            :checked="isSelected(option.value)"
            @change="toggleEvent(option.value)"
          >
          {{ option.label }}
        </label>
      </div>
      <p class="text-xs text-muted-foreground">
        Select none to receive every event.
      </p>
      <p class="text-xs text-muted-foreground">
        Events published within the same five second window arrive together in one run.
        <code>${{ selectedNode.data.label || "heymTrigger" }}.events</code> is always an array,
        even for a single event.
      </p>
    </div>
  </template>
</template>
