import { computed, onUnmounted, ref } from "vue";
import type { ComputedRef, Ref } from "vue";

import type { WorkflowListItem, WorkflowRowStatus } from "@/types/workflow";
import { workflowApi } from "@/services/api";

const POLL_INTERVAL_MS = 15_000;

/**
 * Module-scoped so several dashboard sections share one poll of the active-execution
 * registry instead of each mounting its own timer.
 */
const runningWorkflowIds = ref<Set<string>>(new Set());
let subscriberCount = 0;
let pollTimer: number | null = null;
let requestInFlight = false;

async function refreshRunningWorkflowIds(): Promise<void> {
  if (requestInFlight) return;
  requestInFlight = true;
  try {
    const executions = await workflowApi.getActiveExecutions();
    runningWorkflowIds.value = new Set(executions.map((item) => item.workflow_id));
  } catch {
    // A failed refresh keeps the previous statuses; the listing must not break on it.
  } finally {
    requestInFlight = false;
  }
}

function startPolling(): void {
  if (pollTimer !== null) return;
  void refreshRunningWorkflowIds();
  pollTimer = window.setInterval(() => {
    void refreshRunningWorkflowIds();
  }, POLL_INTERVAL_MS);
}

function stopPolling(): void {
  if (pollTimer === null) return;
  window.clearInterval(pollTimer);
  pollTimer = null;
}

export interface WorkflowRowStatusApi {
  runningWorkflowIds: Ref<Set<string>>;
  /** Resolve the chip a listing row should show for one workflow. */
  statusFor: (workflow: WorkflowListItem) => WorkflowRowStatus;
  runningCount: ComputedRef<number>;
  refresh: () => Promise<void>;
}

export function useWorkflowRowStatus(): WorkflowRowStatusApi {
  subscriberCount += 1;
  startPolling();

  onUnmounted(() => {
    subscriberCount -= 1;
    if (subscriberCount <= 0) {
      subscriberCount = 0;
      stopPolling();
    }
  });

  function statusFor(workflow: WorkflowListItem): WorkflowRowStatus {
    if (workflow.scheduled_for_deletion) return "removeScheduled";
    if (runningWorkflowIds.value.has(workflow.id)) return "running";
    return workflow.trigger_status ?? "manual";
  }

  return {
    runningWorkflowIds,
    statusFor,
    runningCount: computed((): number => runningWorkflowIds.value.size),
    refresh: refreshRunningWorkflowIds,
  };
}
