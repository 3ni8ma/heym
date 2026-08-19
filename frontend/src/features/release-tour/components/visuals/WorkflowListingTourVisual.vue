<script setup lang="ts">
import { computed } from "vue";
import { Play, Zap } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

interface MockRow {
  name: string;
  status: string;
  chip: string;
  dot: string;
  trigger: string;
  steps: string[];
}

const ROWS: MockRow[] = [
  {
    name: "github-agent",
    status: "Running",
    chip: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20",
    dot: "bg-emerald-500",
    trigger: "Webhook",
    steps: ["Parse issue", "Write branch", "Open PR"],
  },
  {
    name: "weather-brief",
    status: "Scheduled",
    chip: "bg-amber-500/10 text-amber-600 dark:text-amber-400 ring-amber-500/20",
    dot: "bg-amber-500",
    trigger: "Cron: 0 */12 * * *",
    steps: ["Fetch forecast", "Summarize", "Send digest"],
  },
  {
    name: "incident-router",
    status: "Paused",
    chip: "bg-muted text-muted-foreground ring-border/60",
    dot: "bg-muted-foreground/60",
    trigger: "Trigger off",
    steps: ["Classify alert", "Page on-call"],
  },
];

const step = useCycleStep(ROWS.length, 1800);

const selected = computed((): MockRow => ROWS[step.value] ?? ROWS[0]);

// The tour renders this inside a fixed 344x168 box, and <Transition mode="out-in"> needs a
// single root element - a comment or second root here silently blanks the whole slide.
</script>

<template>
  <div class="flex h-full w-full gap-1.5 overflow-hidden p-2">
    <div class="flex w-[44%] shrink-0 flex-col justify-between gap-1">
      <div
        v-for="(row, index) in ROWS"
        :key="row.name"
        class="flex min-w-0 flex-1 flex-col justify-center gap-0.5 rounded-md border px-1.5 py-1 transition-all duration-300"
        :class="step === index
          ? 'border-primary bg-primary/10'
          : 'border-border bg-card opacity-70'"
      >
        <span class="truncate text-[9px] font-semibold leading-tight text-foreground">
          {{ row.name }}
        </span>
        <span
          class="inline-flex w-fit max-w-full items-center gap-1 rounded-full px-1 py-px text-[8px] font-medium leading-tight ring-1 ring-inset"
          :class="row.chip"
        >
          <span
            class="h-1 w-1 shrink-0 rounded-full"
            :class="row.dot"
          />
          <span class="truncate">{{ row.status }}</span>
        </span>
      </div>
    </div>

    <div class="flex min-w-0 flex-1 flex-col gap-1 rounded-md border border-border bg-surface-sunken p-1.5">
      <div class="flex min-w-0 items-center justify-between gap-1">
        <span class="truncate text-[9px] font-semibold leading-tight text-foreground">
          {{ selected.name }}
        </span>
        <span class="flex shrink-0 items-center gap-0.5 rounded bg-primary px-1 py-px text-[8px] font-medium leading-tight text-primary-foreground">
          <Play class="h-2 w-2" />
          Run
        </span>
      </div>

      <div class="flex min-w-0 items-center gap-1 rounded border border-border bg-card px-1.5 py-1">
        <Zap class="h-2 w-2 shrink-0 text-amber-500" />
        <span class="truncate text-[8px] leading-tight text-foreground">{{ selected.trigger }}</span>
      </div>

      <div class="flex min-w-0 flex-1 flex-col gap-1">
        <div
          v-for="(label, index) in selected.steps"
          :key="label"
          class="flex min-w-0 flex-1 items-center gap-1 rounded border border-border bg-card px-1.5 py-1"
        >
          <span class="shrink-0 text-[8px] font-semibold leading-tight tabular-nums text-muted-foreground">
            {{ String(index + 1).padStart(2, "0") }}
          </span>
          <span class="truncate text-[8px] leading-tight text-foreground">{{ label }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
