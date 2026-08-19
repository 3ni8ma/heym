<script setup lang="ts">
import { computed } from "vue";
import { Check, Loader2, Maximize2, Sparkles } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

const AI_STEPS = [
  "Open the pricing page",
  "Accept the cookie banner",
  "Read every plan name and price",
];

const step = useCycleStep(AI_STEPS.length + 2, 1200);

function statusOf(index: number): "done" | "running" | "pending" {
  if (step.value > index) return "done";
  if (step.value === index) return "running";
  return "pending";
}

const isShotVisible = computed(() => step.value >= AI_STEPS.length);
const isLightboxOpen = computed(() => step.value > AI_STEPS.length);
</script>

<template>
  <div class="flex h-full w-full gap-2 p-3">
    <div class="flex flex-1 flex-col gap-1.5">
      <div class="flex items-center gap-1">
        <Sparkles class="h-3 w-3 text-primary" />
        <span class="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          AI steps
        </span>
      </div>

      <div
        v-for="(label, index) in AI_STEPS"
        :key="label"
        class="flex items-center gap-2 rounded-md border px-2 py-1.5 transition-all duration-300"
        :class="statusOf(index) === 'running'
          ? 'border-primary/45 bg-primary/10'
          : statusOf(index) === 'done'
            ? 'border-emerald-500/35 bg-emerald-500/8'
            : 'border-border bg-card'"
      >
        <Loader2
          v-if="statusOf(index) === 'running'"
          class="h-3 w-3 shrink-0 animate-spin text-primary"
        />
        <Check
          v-else-if="statusOf(index) === 'done'"
          class="h-3 w-3 shrink-0 text-emerald-500"
        />
        <span
          v-else
          class="h-3 w-3 shrink-0 rounded-full border border-border"
        />
        <span
          class="truncate text-[10.5px] transition-colors duration-300"
          :class="statusOf(index) === 'pending' ? 'text-muted-foreground' : 'text-foreground'"
        >{{ label }}</span>
      </div>
    </div>

    <div class="flex w-[38%] flex-col justify-end">
      <div
        class="relative overflow-hidden rounded-lg border bg-surface-sunken transition-all duration-500"
        :class="isLightboxOpen
          ? 'scale-105 border-primary/50 shadow-lg'
          : isShotVisible
            ? 'scale-100 border-border opacity-100'
            : 'scale-95 border-border opacity-40'"
      >
        <div class="flex items-center gap-1 border-b border-border/70 px-1.5 py-1">
          <span class="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
          <span class="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
          <Maximize2
            class="ml-auto h-2.5 w-2.5 transition-colors duration-300"
            :class="isLightboxOpen ? 'text-primary' : 'text-muted-foreground/60'"
          />
        </div>
        <div class="space-y-1 p-1.5">
          <div class="h-1.5 w-3/4 rounded bg-muted-foreground/25" />
          <div class="h-1.5 w-1/2 rounded bg-muted-foreground/20" />
          <div class="h-6 rounded bg-primary/15" />
          <div class="h-1.5 w-2/3 rounded bg-muted-foreground/20" />
        </div>
      </div>
      <p
        class="mt-1 text-center text-[9.5px] transition-colors duration-300"
        :class="isLightboxOpen ? 'text-primary' : 'text-muted-foreground'"
      >
        {{ isLightboxOpen ? "Opened full size" : "Screenshot" }}
      </p>
    </div>
  </div>
</template>
