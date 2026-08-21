<script setup lang="ts">
import { computed } from "vue";
import { Copy, Pin, PinOff, RotateCcw, Settings, Trash2 } from "lucide-vue-next";

import type { WorkflowListItem, WorkflowRowStatus } from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import WorkflowStatusBadge from "@/components/Workflows/WorkflowStatusBadge.vue";
import { isTileFillingIcon, nodeIcons } from "@/lib/nodeIcons";
import { cn, formatDate } from "@/lib/utils";
import { Workflow as WorkflowIcon } from "lucide-vue-next";

interface Props {
  workflow: WorkflowListItem;
  status: WorkflowRowStatus;
  selected?: boolean;
  pinned?: boolean;
  /** Nested rows inside a folder use tighter spacing and a smaller icon. */
  compact?: boolean;
  copyingId?: string | null;
  isDragging?: boolean;
  isMobile?: boolean;
  index?: number;
  onTouchStartRow?: (e: TouchEvent, workflow: WorkflowListItem) => void;
  onTouchEndRow?: () => void;
  onTouchMoveRow?: () => void;
}

const props = withDefaults(defineProps<Props>(), {
  selected: false,
  pinned: false,
  compact: false,
  copyingId: null,
  isDragging: false,
  isMobile: false,
  index: 0,
  onTouchStartRow: undefined,
  onTouchEndRow: undefined,
  onTouchMoveRow: undefined,
});

const emit = defineEmits<{
  select: [workflow: WorkflowListItem];
  open: [id: string, event: MouseEvent];
  edit: [workflow: WorkflowListItem, event: Event];
  copy: [id: string, event: Event];
  delete: [id: string, event: Event];
  restore: [id: string, event: Event];
  togglePin: [id: string];
  dragStart: [event: DragEvent, id: string];
  dragEnd: [];
}>();

const isTrashed = computed((): boolean => props.workflow.scheduled_for_deletion !== null);

const iconComponent = computed(() => {
  const type = props.workflow.first_node_type;
  return type && nodeIcons[type] ? nodeIcons[type] : WorkflowIcon;
});

const iconFillsTile = computed((): boolean => {
  const type = props.workflow.first_node_type;
  return type !== null && isTileFillingIcon(type);
});

const timestampLabel = computed((): string => {
  if (isTrashed.value && props.workflow.scheduled_for_deletion) {
    return `Scheduled ${formatDate(props.workflow.scheduled_for_deletion)}`;
  }
  return formatDate(props.workflow.updated_at);
});

/** Click selects for the preview panel; Ctrl/Cmd-click and double-click go straight to the editor. */
function handleRowClick(event: MouseEvent): void {
  if (event.ctrlKey || event.metaKey) {
    emit("open", props.workflow.id, event);
    return;
  }
  emit("select", props.workflow);
}

function handleRowDoubleClick(event: MouseEvent): void {
  emit("open", props.workflow.id, event);
}

function handleRowKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter") {
    emit("open", props.workflow.id, event as unknown as MouseEvent);
    return;
  }
  emit("select", props.workflow);
}
</script>

<template>
  <div
    :data-testid="`workflow-card-${workflow.id}`"
    :data-selected="String(selected)"
    role="button"
    tabindex="0"
    :class="cn(
      'workflow-row group relative flex w-full cursor-pointer items-center gap-3 rounded-xl border transition-all duration-200',
      compact ? 'px-2.5 py-2' : 'px-3 py-2.5 sm:px-4 sm:py-3',
      isTrashed
        ? 'border-destructive/25 bg-destructive/[0.04] hover:border-destructive/45'
        : selected
          ? 'border-primary bg-primary/[0.07] shadow-sm dark:border-primary/55 dark:bg-primary/[0.09]'
          : 'border-border/50 bg-card hover:border-border hover:bg-muted/40',
      isDragging && 'workflow-card--dragging',
    )"
    :style="{ animationDelay: `${index * 40}ms` }"
    draggable="true"
    @click="handleRowClick"
    @dblclick="handleRowDoubleClick"
    @keydown.enter.prevent="handleRowKeydown"
    @keydown.space.prevent="emit('select', workflow)"
    @touchstart.passive="isMobile && onTouchStartRow?.($event, workflow)"
    @touchend="isMobile && onTouchEndRow?.()"
    @touchmove="isMobile && onTouchMoveRow?.()"
    @dragstart="emit('dragStart', $event, workflow.id)"
    @dragend="emit('dragEnd')"
  >
    <div
      :class="cn(
        'workflow-row-icon relative flex shrink-0 items-center justify-center rounded-lg',
        compact ? 'h-8 w-8' : 'h-9 w-9 sm:h-10 sm:w-10',
        isTrashed ? 'text-destructive' : 'text-primary dark:text-brand-primary-soft',
      )"
    >
      <div
        :class="cn(
          'absolute inset-0 rounded-lg bg-gradient-to-br',
          isTrashed
            ? 'from-destructive/15 via-destructive/10 to-destructive/5'
            : 'from-primary/15 via-primary/10 to-primary/5 dark:from-primary/[0.14] dark:via-primary/[0.08] dark:to-transparent',
        )"
      />
      <div
        :class="cn(
          'absolute inset-0 rounded-lg ring-1 ring-inset',
          isTrashed ? 'ring-destructive/20' : 'ring-primary/20 dark:ring-primary/25',
        )"
      />
      <component
        :is="iconComponent"
        :class="iconFillsTile
          ? 'relative z-10 h-full w-full'
          : cn('relative z-10', compact ? 'h-3.5 w-3.5' : 'h-4 w-4')"
      />
    </div>

    <div class="min-w-0 flex-1">
      <h3
        :class="cn(
          'workflow-row-title truncate font-semibold leading-snug transition-colors duration-200',
          compact ? 'text-[13px]' : 'text-sm',
        )"
        :title="workflow.name"
      >
        {{ workflow.name }}
      </h3>
      <p
        v-if="workflow.description"
        :class="cn(
          'truncate text-muted-foreground',
          compact ? 'text-[11px]' : 'text-xs',
        )"
        :title="workflow.description"
      >
        {{ workflow.description }}
      </p>
      <div class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span
          :class="cn('text-muted-foreground/80', compact ? 'text-[10px]' : 'text-[11px]')"
        >
          {{ timestampLabel }}
        </span>
        <WorkflowStatusBadge
          :status="status"
          :compact="compact"
        />
      </div>
    </div>

    <!-- On phones the row keeps its full width for the name; long-press opens the action sheet. -->
    <div
      class="hidden shrink-0 items-center gap-0.5 sm:flex"
      @click.stop
    >
      <Button
        variant="ghost"
        size="icon"
        class="h-8 w-8 rounded-lg text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary md:h-7 md:w-7"
        title="Edit workflow"
        @click="emit('edit', workflow, $event)"
      >
        <Settings class="h-3.5 w-3.5" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        class="h-8 w-8 rounded-lg text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary md:h-7 md:w-7"
        title="Copy workflow"
        :disabled="copyingId === workflow.id"
        @click="emit('copy', workflow.id, $event)"
      >
        <Copy
          class="h-3.5 w-3.5"
          :class="{ 'animate-spin-slow': copyingId === workflow.id }"
        />
      </Button>
      <Button
        v-if="isTrashed"
        variant="ghost"
        size="icon"
        class="h-8 w-8 rounded-lg text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary md:h-7 md:w-7"
        title="Restore workflow"
        @click="emit('restore', workflow.id, $event)"
      >
        <RotateCcw class="h-3.5 w-3.5" />
      </Button>
      <Button
        v-else
        variant="ghost"
        size="icon"
        class="h-8 w-8 rounded-lg transition-colors hover:bg-primary/10 md:h-7 md:w-7"
        :class="pinned ? 'text-primary' : 'text-muted-foreground hover:text-primary'"
        :title="pinned ? 'Unpin workflow' : 'Pin workflow'"
        @click="emit('togglePin', workflow.id)"
      >
        <PinOff
          v-if="pinned"
          class="h-3.5 w-3.5"
        />
        <Pin
          v-else
          class="h-3.5 w-3.5"
        />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        :data-testid="`workflow-delete-${workflow.id}`"
        class="h-8 w-8 rounded-lg text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive dark:hover:text-red-300 md:h-7 md:w-7"
        :title="isTrashed ? 'Delete immediately' : 'Delete workflow'"
        @click="emit('delete', workflow.id, $event)"
      >
        <Trash2 class="h-3.5 w-3.5" />
      </Button>
    </div>
  </div>
</template>

<style scoped>
.workflow-row {
  animation: workflow-row-in 0.28s ease-out both;
}

.workflow-row:hover .workflow-row-title {
  color: hsl(var(--primary));
}

@keyframes workflow-row-in {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .workflow-row {
    animation: none;
  }
}
</style>
