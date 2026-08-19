<script setup lang="ts">
import { computed } from "vue";
import {
  Bell,
  CreditCard,
  Folder,
  Globe,
  Rocket,
  ShoppingBag,
  Sparkles,
  Zap,
} from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

const PICKER_ICONS = [
  { key: "rocket", component: Rocket },
  { key: "credit-card", component: CreditCard },
  { key: "bell", component: Bell },
  { key: "globe", component: Globe },
  { key: "shopping-bag", component: ShoppingBag },
  { key: "zap", component: Zap },
];

const SELECTION_ORDER = [0, 2, 4, 1];

const step = useCycleStep(SELECTION_ORDER.length, 1400);

const selectedIndex = computed(() => SELECTION_ORDER[step.value] ?? 0);
const selectedIcon = computed(() => PICKER_ICONS[selectedIndex.value]?.component ?? Folder);
</script>

<template>
  <div class="flex h-full w-full gap-2 p-3">
    <div class="flex w-[42%] flex-col gap-1.5">
      <div class="flex items-center gap-2 rounded-md border border-primary/35 bg-primary/10 px-2 py-1.5">
        <component
          :is="selectedIcon"
          class="h-3.5 w-3.5 shrink-0 text-primary"
        />
        <span class="truncate text-[11px] font-semibold text-foreground">Billing</span>
      </div>
      <div class="flex items-center gap-2 rounded-md border border-border px-2 py-1.5 opacity-70">
        <Folder class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span class="truncate text-[11px] text-muted-foreground">Scraping</span>
      </div>
      <div class="flex items-center gap-2 rounded-md border border-border px-2 py-1.5 opacity-70">
        <Folder class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span class="truncate text-[11px] text-muted-foreground">Internal</span>
      </div>
    </div>

    <div class="flex flex-1 flex-col rounded-lg border border-border bg-surface-sunken p-2">
      <div class="mb-1.5 flex items-center gap-1">
        <Sparkles class="h-3 w-3 text-primary" />
        <span class="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          Change icon
        </span>
      </div>
      <div class="grid flex-1 grid-cols-3 gap-1.5">
        <div
          v-for="(icon, index) in PICKER_ICONS"
          :key="icon.key"
          class="flex items-center justify-center rounded-md border transition-all duration-300"
          :class="selectedIndex === index
            ? 'scale-105 border-primary bg-primary/15'
            : 'scale-100 border-border bg-card'"
        >
          <component
            :is="icon.component"
            class="h-3.5 w-3.5 transition-colors duration-300"
            :class="selectedIndex === index ? 'text-primary' : 'text-muted-foreground'"
          />
        </div>
      </div>
    </div>
  </div>
</template>
