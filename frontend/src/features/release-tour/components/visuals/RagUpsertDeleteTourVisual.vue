<script setup lang="ts">
import { computed } from "vue";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: collection at rest · 1: upsert replaces crm-118 ·
// 2: the new version is stored · 3: delete removes crm-204.
const step = useCycleStep(4, 1700);

interface MockDocument {
  docId: string;
  title: string;
  state: "stored" | "replacing" | "fresh" | "removed";
}

const documents = computed<MockDocument[]>(() => [
  {
    docId: "crm-118",
    title: "Refund policy",
    state: step.value === 1 ? "replacing" : step.value === 2 ? "fresh" : "stored",
  },
  { docId: "crm-204", title: "Shipping SLA", state: step.value === 3 ? "removed" : "stored" },
  { docId: "crm-311", title: "Onboarding FAQ", state: "stored" },
]);

const operation = computed<string>(() => (step.value === 3 ? "delete" : "upsert"));
const documentId = computed<string>(() => (step.value === 3 ? "crm-204" : "crm-118"));

const resultLabel = computed<string>(() => {
  if (step.value === 1) return "replacing the stored version";
  if (step.value === 2) return "replaced: true";
  if (step.value === 3) return "deleted: true";
  return "addressed by doc_id";
});
</script>

<template>
  <div class="w-full rounded-lg border border-border bg-card p-4">
    <div class="mb-3 flex items-center justify-between">
      <span class="text-sm font-medium text-foreground">RAG &middot; Vector Store</span>
      <span class="text-xs text-muted-foreground">{{ resultLabel }}</span>
    </div>

    <div class="mb-3 grid grid-cols-3 gap-2">
      <div class="rounded-md border border-border bg-background px-2 py-1.5">
        <p class="text-[10px] text-muted-foreground">
          Operation
        </p>
        <p class="text-xs font-medium text-primary transition-colors duration-500">
          {{ operation }}
        </p>
      </div>
      <div class="rounded-md border border-border bg-background px-2 py-1.5">
        <p class="text-[10px] text-muted-foreground">
          Document ID Field
        </p>
        <p class="font-mono text-xs text-foreground">
          doc_id
        </p>
      </div>
      <div class="rounded-md border border-border bg-background px-2 py-1.5">
        <p class="text-[10px] text-muted-foreground">
          Document ID
        </p>
        <p class="font-mono text-xs text-foreground transition-colors duration-500">
          {{ documentId }}
        </p>
      </div>
    </div>

    <div class="space-y-1.5">
      <div
        v-for="document in documents"
        :key="document.docId"
        class="flex items-center gap-3 rounded-md border bg-background px-3 py-2 transition-all duration-500"
        :class="{
          'border-border opacity-100': document.state === 'stored',
          'border-border opacity-30 line-through': document.state === 'replacing',
          'border-primary/60 opacity-100': document.state === 'fresh',
          'border-border opacity-0': document.state === 'removed',
        }"
      >
        <span class="font-mono text-xs text-muted-foreground">{{ document.docId }}</span>
        <span class="flex-1 truncate text-sm text-foreground">{{ document.title }}</span>
        <span
          v-if="document.state === 'fresh'"
          class="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] text-primary"
        >new version</span>
      </div>
    </div>

    <p class="mt-3 text-xs text-muted-foreground">
      The ID lives in the payload, so a document keeps the identifier your own system already
      uses. Both backends, Qdrant and Postgres, behave the same.
    </p>
  </div>
</template>
