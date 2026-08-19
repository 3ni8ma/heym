<script setup lang="ts">
import { computed } from "vue";
import { Check, Code2, Loader2 } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

const CODE_LINES = [
  { indent: 0, text: "rows = items[0][\"data\"]" },
  { indent: 0, text: "top = [r for r in rows if r[\"score\"] > 80]" },
  { indent: 0, text: "return {\"count\": len(top), \"top\": top}" },
];

const step = useCycleStep(5, 1100);

const activeLine = computed(() => (step.value < CODE_LINES.length ? step.value : -1));
const isRunning = computed(() => step.value === CODE_LINES.length);
const isDone = computed(() => step.value > CODE_LINES.length);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2 p-3">
    <div class="flex items-center gap-2">
      <div class="flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2 py-1">
        <Code2 class="h-3.5 w-3.5 text-primary" />
        <span class="text-[11px] font-semibold text-foreground">Code</span>
      </div>
      <span class="rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
        Python
      </span>
      <div class="ml-auto flex items-center gap-1">
        <Loader2
          v-if="isRunning"
          class="h-3 w-3 animate-spin text-primary"
        />
        <Check
          v-else-if="isDone"
          class="h-3 w-3 text-emerald-500"
        />
        <span
          class="text-[10px] font-medium transition-colors duration-300"
          :class="isDone ? 'text-emerald-500' : 'text-muted-foreground'"
        >
          {{ isRunning ? "Running" : isDone ? "Done" : "Sandboxed" }}
        </span>
      </div>
    </div>

    <div class="flex flex-1 flex-col justify-center gap-0.5 overflow-hidden rounded-lg border border-border bg-surface-sunken p-2">
      <div
        v-for="(line, index) in CODE_LINES"
        :key="line.text"
        class="flex items-center gap-2 rounded px-1.5 py-0.5 transition-colors duration-300"
        :class="activeLine === index ? 'bg-primary/12' : 'bg-transparent'"
      >
        <span class="w-3 shrink-0 text-right font-mono text-[10px] leading-[15px] text-muted-foreground/60">
          {{ index + 1 }}
        </span>
        <span
          class="truncate font-mono text-[10.5px] leading-[15px] transition-colors duration-300"
          :class="activeLine === index ? 'text-foreground' : 'text-muted-foreground'"
        >{{ line.text }}</span>
      </div>
    </div>

    <div
      class="flex items-center gap-2 rounded-lg border px-2 py-1.5 transition-all duration-500"
      :class="isDone
        ? 'border-emerald-500/40 bg-emerald-500/10 opacity-100'
        : 'border-border bg-muted/40 opacity-60'"
    >
      <span class="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        Output
      </span>
      <span
        class="truncate font-mono text-[10.5px] transition-opacity duration-500"
        :class="isDone ? 'text-foreground opacity-100' : 'text-muted-foreground opacity-40'"
      >{{ isDone ? '{ "count": 3, "top": [ … ] }' : "waiting…" }}</span>
    </div>
  </div>
</template>
