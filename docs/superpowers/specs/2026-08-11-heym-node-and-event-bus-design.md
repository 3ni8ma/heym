# Heym Node + Internal Event Bus — Design

Date: 2026-08-11
Status: Approved for planning

## Summary

Heym can automate every system except itself. This spec adds two node types and the
persistence behind them:

- **`heym`** — an action node that reads Heym's own data: the workflows the owner can
  reach, one workflow's detail, and execution-history counts for a workflow.
- **`heymTrigger`** — a trigger node that starts a workflow when a platform event is
  published (`heym.started`, `workflow.created`, `workflow.updated`, `workflow.deleted`).

Events live in an append-only Postgres log. Delivery is claimed per subscriber through a
unique constraint, so an event fires exactly once per subscribing node no matter how many
uvicorn workers, containers, or machines are running.

## Goals

1. A workflow can list, inspect, and count executions of the owner's workflows.
2. A workflow can react to platform lifecycle events without polling an HTTP API.
3. Delivery is exactly-once per subscribing node across a multi-instance deployment.
4. Every event delivery carries an array, so a burst inside one poll window is one run.

## Non-goals

- `execution.completed` / `execution.failed` events. High volume, they add a write to the
  executor's hot path, and they invite event → run → event loops. Deferred deliberately.
- A workflow-authored `emitEvent` operation (workflow-to-workflow event bus). Deferred.
- Push delivery via `pg_notify`. The claim table makes this a safe later upgrade; v1 polls.
- Mutating operations on the `heym` node (create/update/delete workflows). Read-only in v1.

## Data model

Two new tables in `backend/app/db/models.py`, one Alembic migration.

### `heym_events`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID, pk | |
| `name` | String(100), not null, index | `heym.started`, `workflow.created`, `workflow.updated`, `workflow.deleted` |
| `payload` | JSON, not null, default `{}` | Event body |
| `owner_id` | UUID, nullable, index | User the event belongs to; NULL for instance-wide events (`heym.started`) |
| `workflow_id` | UUID, nullable, index | Subject workflow. **No foreign key** — `workflow.deleted` references a row that no longer exists |
| `dedupe_key` | String(200), nullable, unique | Publish-time collapse key; Postgres allows many NULLs under a unique constraint |
| `created_at` | timestamptz, server default `now()`, index | Dispatch ordering and retention |

### `heym_event_claims`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID, pk | |
| `event_id` | UUID, not null, FK → `heym_events.id` ON DELETE CASCADE | |
| `workflow_id` | UUID, not null | Subscribing workflow |
| `node_id` | String(255), not null | Subscribing `heymTrigger` node |
| `claimed_by` | String(128), nullable | Worker id, for debugging |
| `claimed_at` | timestamptz, server default `now()`, index | |

Constraint `uq_heym_event_claim` on `(event_id, workflow_id, node_id)`.

This mirrors `cron_slot_claims` exactly, and for the same reason: in-memory state is
per-worker, so "has anyone delivered this yet?" can only be answered in Postgres.

### Retention

`HEYM_EVENT_RETENTION_DAYS = 7`, a module constant — no environment variable, matching the
project's rule that platform limits are constants. The dispatcher deletes events older than
the window once an hour; claims disappear via CASCADE.

## Publishing

New module `backend/app/services/heym_event_service.py`.

```python
async def publish_event(
    db: AsyncSession,
    *,
    name: str,
    payload: dict[str, Any],
    owner_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
) -> None
```

Inserts one row with `on_conflict_do_nothing` against `uq_heym_event_dedupe_key`. The
function never raises: failures are logged and swallowed, the same discipline the tracing
module follows. Publishing an event must never break a workflow save.

### Call sites and dedupe keys

| Event | Where | `dedupe_key` |
| --- | --- | --- |
| `heym.started` | `main.py` lifespan startup | `heym.started:<UTC timestamp floored to 5 minutes>` |
| `workflow.created` | `api/workflows.py::create_workflow` | `workflow.created:<workflow_id>` |
| `workflow.updated` | `api/workflows.py::update_workflow` | `workflow.updated:<workflow_id>:<updated_at ISO>` |
| `workflow.deleted` | `api/workflows.py::delete_workflow` | `workflow.deleted:<workflow_id>` |

`heym.started` needs the bucket key because the deployment runs 8 uvicorn workers. Without
it, one boot writes 8 distinct rows, and the claim table cannot help — those are 8 different
events, so a subscribing workflow would run 8 times. The 5-minute bucket collapses all
workers of all containers onto one row atomically, with no lock. Known limit: containers
that start more than 5 minutes apart publish two events. This is acceptable and documented.

`workflow.updated` keys on `updated_at` so a retried or duplicated save collapses. Saving is
an explicit user action (Cmd+S / save button, verified: no keystroke autosave), so volume is
bounded.

Payload shapes:

- `heym.started` — `{ "version": str, "started_at": ISO8601 }`
- `workflow.*` — `{ "workflow_id": str, "name": str, "owner_id": str, "actor_user_id": str | None, "updated_at": ISO8601 }`

`workflow.deleted` carries the name captured before deletion, since the row is gone.

## Dispatching

New module `backend/app/services/heym_event_dispatcher.py`, class `HeymEventDispatcher`,
built on the `ImapTriggerManager` skeleton and started/stopped in `main.py`'s lifespan
alongside the other trigger managers.

Constants: `DISPATCH_INTERVAL_SECONDS = 5`, `DISPATCH_LOOKBACK_MINUTES = 5`,
`CLEANUP_INTERVAL_MINUTES = 60`.

Each 5-second tick:

1. Load workflows containing at least one `heymTrigger` node that is not
   `data.active === false`. Skip the rest of the tick if there are none.
2. Select events with `created_at >= now() - DISPATCH_LOOKBACK_MINUTES`, ordered by
   `created_at` ascending. The lookback bounds backlog replay after downtime — the same
   reasoning as the cron scheduler's misfire grace. Events older than the window are never
   delivered, only retained for inspection until cleanup.
3. For each `(workflow, heymTrigger node)` pair, filter the events by the node's
   `eventNames` list (empty list means all) and by visibility: an event with a non-NULL
   `owner_id` is only delivered to workflows owned by that user; `owner_id IS NULL` events
   are delivered to everyone.
4. Claim each surviving event with `claim_heym_event(event_id, workflow_id, node_id)`.
   Losing a claim is normal — another instance took that event and will deliver it in its
   own batch. A database error returns `False` (fail closed, nothing runs).
5. If at least one event was claimed, run the workflow **once** with all claimed events in
   one array, ordered by `created_at` ascending.
6. Once an hour, delete events older than `HEYM_EVENT_RETENTION_DAYS`.

Batching is the delivery contract, not an optimization: importing 100 workflows produces one
run, not 100. The cost is that downstream nodes read an array — via a Loop node or
`$json.events[0]`. Documented on the node page.

The execution path is the one `_execute_workflow_for_email` already uses:
`collect_referenced_workflows` → `get_credentials_context` → `get_global_variables_context`
→ `register_execution` → `execute_workflow` → `ExecutionHistory` row + analytics snapshot +
sub-workflow histories + `_persist_global_variables_from_execution`. `trigger_source` is
`"heym_event"`.

Trigger inputs written into `_initial_inputs`:

```json
{
  "triggered_by": "heym_event",
  "trigger_node_id": "<node id>",
  "triggered_at": "<ISO8601>",
  "events": [
    {
      "id": "<uuid>",
      "name": "workflow.created",
      "payload": { },
      "workflow_id": "<uuid|null>",
      "created_at": "<ISO8601>"
    }
  ]
}
```

## Nodes

Both handlers live under `backend/app/services/node_execution/nodes/` and register in
`registry.py`. No branch is added to `WorkflowExecutor._execute_node_logic`.

### `heymTrigger` — `heym_trigger_node.py`

Reads `_initial_inputs` and returns `{ events, count, triggered_at }`. `count` is
`len(events)`. The output is always an array-shaped payload, including the single-event case,
so downstream expressions never change shape. Handler is ~20 lines, matching
`imap_trigger_node.py` and `websocket_trigger_node.py`.

Node data field: `eventNames: string[]`, a multi-select over the four known event names.
Empty means every event.

### `heym` — `heym_node.py`

Uses `SessionLocal` (the synchronous session), the pattern `data_table_node.py` already
uses, since node handlers run in executor threads.

Field: `heymOperation` — `listWorkflows` | `getWorkflow` | `countExecutions`.

| Operation | Fields | Output |
| --- | --- | --- |
| `listWorkflows` | `heymLimit` (optional, default 100, capped at 500) | `{ workflows: [{ id, name, description, active, folder_id, updated_at, node_count }], total }` where `total` is the full accessible count before the limit is applied |
| `getWorkflow` | `heymWorkflowId` (required) | `{ id, name, description, active, updated_at, nodes: [{ id, type, label }], edges: [{ id, source, target }], input_fields }` |
| `countExecutions` | `heymWorkflowId` (required), `heymStatus` (optional), `heymSinceDays` (optional) | `{ workflow_id, total, by_status: { success: n, error: n, ... }, since }` |

`getWorkflow` returns node identity only — id, type, label — not `data`. Node data holds
credential ids and prompt text; there is no reason to hand a whole configuration blob to an
arbitrary downstream node.

A missing or inaccessible `heymWorkflowId` raises `ValueError` with a clear message, which
the executor packages as a node error. Access denial and non-existence produce the same
message, so the node cannot be used to probe for workflow ids.

### Access scope

Every operation resolves against the **owning workflow's `owner_id`** — the workflow the
`heym` node lives in — not the actor who triggered the run. Owner scoping matches how the
codebase already resolves credentials (`get_credentials_context(db, workflow.owner_id)`) and
global variables, and it keeps results identical across manual, cron, portal, and event
triggered runs. Actor scoping would return an empty list on every unattended run.

Visible set: workflows the owner owns, plus `WorkflowShare` rows for that user, plus
`WorkflowTeamShare` rows for teams the user belongs to.

`api/workflows.py` currently inlines this subquery three times (around lines 353, 571, and
630). This design extracts it into a reusable helper — `accessible_workflow_ids(user_id)` —
and points the existing three call sites plus the new node at it. That is a targeted cleanup
inside the code being touched, not a general refactor.

## Frontend

`heym` gets `HeymNodeProperties.vue`, `heymTrigger` gets `HeymTriggerNodeProperties.vue`,
both under `components/Panels/propertiesPanel/nodes/`. `PropertiesPanel.vue` stays a shell —
no `selectedNode.type` branches are added there.

`heymWorkflowId` uses the existing `SearchableSelect` bound to `workflowOptions` from
`usePropertiesPanelContext()`, the same control the `execute` node uses for its target
workflow. This satisfies the "search dropdown" requirement with no new API surface.

Files touched: `types/node.ts`, `types/workflow.ts`, `stores/workflow.ts`, `BaseNode.vue`,
`NodePanel.vue`, `nodeIcons.ts`, `canvasConnectionRules.ts` (`heymTrigger` registers as a
trigger: no input handle, valid workflow start), `operationOptions.ts`,
`usePropertiesPanelController.ts`, `NodePropertiesForm.vue`, `DebugPanel.vue`,
`WorkflowCanvas.vue`.

No frontend UI tests are written, per the project's standing rule. Verification is
`bun run lint` + `bun run typecheck` + manual check.

## Testing

New backend tests, all with `unittest.IsolatedAsyncioTestCase` and `AsyncMock`:

- `test_heym_event_service.py` — publish writes a row; a duplicate `dedupe_key` is a no-op;
  a database error is swallowed rather than raised; `heym.started` published by eight
  simulated workers inside one bucket yields one row.
- `test_heym_event_dispatcher.py` — a second claim on the same
  `(event_id, workflow_id, node_id)` returns `False`; a claim error returns `False` and
  nothing runs; two events inside one tick produce one run with a two-element `events` array
  ordered by `created_at`; events older than the lookback are not delivered; an event with
  `owner_id` set is not delivered to another owner's workflow; nodes with
  `data.active === false` are skipped; retention deletes past the window.
- `test_heym_node.py` — each of the three operations; a workflow owned by someone else and
  not shared is invisible to `listWorkflows` and raises on `getWorkflow`; `countExecutions`
  groups by status and honours `heymSinceDays`; `getWorkflow` output excludes node `data`.
- `test_heym_trigger_node.py` — output shape holds for one event and for many; a missing
  `_initial_inputs` yields an empty array rather than an error.

## Documentation and rollout

### heymrun

- `workflow_dsl_prompt.py` — both node types with operations, fields, defaults, dynamic and
  expression eligibility, and AI-autofill hints. `heymWorkflowId`, `heymLimit`, `heymStatus`,
  and `heymSinceDays` are all expression-capable, so the expression dialog can walk them with
  `1/n` navigation.
- `frontend/src/docs/content/nodes/heym-node.md` and `heym-trigger-node.md`, registered in
  `frontend/src/docs/manifest.ts`.
- `frontend/src/docs/content/reference/features.md` — per-node sections plus the node-types
  summary list; `node-types.md`; `reference/triggers.md` for `heymTrigger`.
- No credential is involved, so `integrations.md` / `credentials.md` /
  `credentials-sharing.md` need no change.

Documentation changes go through the `heym-documentation` skill.

### heymweb

Per the six-file rollout: `src/lib/marketingNodeCatalog.ts` (two entries),
`src/lib/node-doc-links.ts`, `src/components/sections/NodesSection.tsx`,
`src/components/templates/nodePreviewTokens.ts`,
`src/components/templates/TemplateCanvasNode.tsx`, and
`src/components/sections/DocumentationSection.tsx`.

`tests/seo/invariants.test.ts` hardcodes the node count in two places — the test title on
line 89 and `expect(MARKETING_NODE_COUNT).toBe(57)` on line 93. Both go to 59. Missing this
fails `bunx tsc --noEmit`, not just the test run, because Bun's `toBe` narrows to a literal
overload. The sibling `countFiles(docsRoot/nodes)` assertion self-corrects once the two new
node doc pages exist.

A template is added that uses both nodes — a `heymTrigger` on `workflow.updated` feeding a
`heym` `getWorkflow` call and a notification — and wired reciprocally with any related
article. Then `bun run sync-docs` and `bun run sync-dsl-prompt` (both read from `../heymrun`).

Verification on the heymweb side is `bunx tsc --noEmit` + `bun test tests/seo/invariants.test.ts`
+ `bun run build`. There is no lint step in that repo.

### Delivery

All changes stay local. Nothing is pushed.

## Verification

- `SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh`
  from the repo root — Ruff format, lint, frontend lint and typecheck, and the backend suite.
  `HEYM_OTEL_ENABLED=false` is required because the local `.env` enables OTel with no
  collector running, which hangs the suite.
- `cd backend && uv run alembic upgrade head` after the migration lands.
- Manual: start the stack, build a workflow with `heymTrigger` on `workflow.created`, create
  two workflows within five seconds, confirm one run with a two-element `events` array.

## Risks and open questions

- **Event volume.** `workflow.updated` fires on every explicit save. Retention plus the
  `updated_at` dedupe key bound the table, but a scripted client hammering the update
  endpoint would still write a row per distinct save. Acceptable for v1; revisit if the
  table grows.
- **Batch semantics leak into workflow authoring.** Users who expect one run per event will
  have to loop. This is stated on the node doc page and in the DSL description.
- **`heym.started` across slow rollouts.** Containers starting more than five minutes apart
  publish two events. Accepted; the alternative is a distributed lock with its own failure
  modes.
