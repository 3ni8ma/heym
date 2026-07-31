<script setup lang="ts">
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  updateNodeData,
} = usePropertiesPanelContext();

const conversionOptions = [
  { value: "csvToJson", label: "CSV → JSON" },
  { value: "jsonToCsv", label: "JSON → CSV" },
];
</script>

<template>
  <template v-if="selectedNode">
    <div
      class="space-y-2"
      data-testid="converter-conversion-field"
    >
      <Label>Conversion</Label>
      <Select
        :model-value="selectedNode.data.conversion || 'csvToJson'"
        :options="conversionOptions"
        @update:model-value="updateNodeData('conversion', $event || 'csvToJson')"
      />
      <p class="text-xs text-muted-foreground">
        Choose the direction of the conversion.
      </p>
    </div>

    <div
      class="space-y-2"
      data-testid="converter-source-field"
    >
      <Label>Source</Label>
      <ExpressionInput
        :model-value="selectedNode.data.source || ''"
        placeholder="$input.text"
        :rows="2"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Source"
        field-key="source"
        @update:model-value="updateNodeData('source', $event)"
      />
      <p class="text-xs text-muted-foreground">
        The data to convert. Leave empty to use this node's first input.
      </p>
    </div>

    <div
      class="space-y-2"
      data-testid="converter-delimiter-field"
    >
      <Label>Delimiter</Label>
      <Input
        :model-value="selectedNode.data.delimiter || ','"
        placeholder=","
        @update:model-value="updateNodeData('delimiter', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Single-character field separator (default <code>,</code>).
      </p>
    </div>

    <div
      v-if="(selectedNode.data.conversion || 'csvToJson') === 'csvToJson'"
      class="space-y-2"
      data-testid="converter-has-header-field"
    >
      <div class="flex items-center gap-2">
        <input
          id="converter-has-header"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background"
          :checked="selectedNode.data.hasHeader !== false"
          @change="updateNodeData('hasHeader', ($event.target as HTMLInputElement).checked)"
        >
        <Label
          for="converter-has-header"
          class="text-sm font-medium"
        >
          First row is a header
        </Label>
      </div>
      <p class="text-xs text-muted-foreground">
        When enabled, header values become the keys of each row object.
      </p>
    </div>

    <template v-if="(selectedNode.data.conversion || 'csvToJson') === 'jsonToCsv'">
      <div
        class="space-y-2"
        data-testid="converter-include-header-field"
      >
        <div class="flex items-center gap-2">
          <input
            id="converter-include-header"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="selectedNode.data.includeHeader !== false"
            @change="updateNodeData('includeHeader', ($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="converter-include-header"
            class="text-sm font-medium"
          >
            Include header row
          </Label>
        </div>
        <p class="text-xs text-muted-foreground">
          Write a header row derived from the object keys.
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="converter-columns-field"
      >
        <Label>Columns (optional)</Label>
        <Input
          :model-value="selectedNode.data.converterColumns || ''"
          placeholder="name, age, email"
          @update:model-value="updateNodeData('converterColumns', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Comma-separated column order. Leave empty to infer from the data.
        </p>
      </div>
    </template>

    <div class="space-y-2 pt-2 border-t">
      <Label class="text-muted-foreground">Output</Label>
      <p class="text-xs text-muted-foreground">
        The converted value is available as <code>${{ selectedNode.data.label || 'converter' }}.result</code>.
      </p>
    </div>
  </template>
</template>
