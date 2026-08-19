<script setup lang="ts">
import Button from "@/components/ui/Button.vue";

interface Props {
  label: string;
  hasUnseenRelease: boolean;
}

defineProps<Props>();

const emit = defineEmits<{
  (e: "open"): void;
}>();
</script>

<template>
  <Button
    variant="ghost"
    size="sm"
    class="release-tour-launcher relative ml-2 gap-2 min-h-[44px] sm:min-w-auto text-foreground"
    :aria-label="`${label} — open the release tour`"
    @click="emit('open')"
  >
    <span>{{ label }}</span>
    <span
      v-if="hasUnseenRelease"
      class="release-tour-launcher__dot absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-accent-orange ring-2 ring-background"
      aria-hidden="true"
    />
  </Button>
</template>

<style scoped>
.release-tour-launcher__dot {
  animation: release-tour-dot-pulse 2.8s ease-in-out infinite;
}

@keyframes release-tour-dot-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 hsl(var(--accent-orange) / 0.5);
  }
  50% {
    box-shadow: 0 0 0 3px hsl(var(--accent-orange) / 0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .release-tour-launcher__dot {
    animation: none !important;
  }
}
</style>
