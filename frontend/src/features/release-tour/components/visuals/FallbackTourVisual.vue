<script setup lang="ts">
import { Sparkles } from "lucide-vue-next";
</script>

<template>
  <div class="flex h-full w-full items-center justify-center p-3">
    <div class="flex flex-col items-center gap-2 text-center">
      <div class="flex h-9 w-9 items-center justify-center rounded-full border border-primary/30 bg-primary/10">
        <Sparkles class="h-4 w-4 text-primary" />
      </div>
      <p class="text-[11px] font-medium text-muted-foreground">
        Something new landed in this release.
      </p>
    </div>
  </div>
</template>
