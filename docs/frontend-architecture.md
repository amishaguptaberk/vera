# Vera — Frontend Architecture (Next.js port)

Status: design for sign-off · Nov 10, 2026 · Implements decision D-A in `backend-implementation-plan.md` §17.

The prototype (`apps/web/prototype/Main.dc.html`) is the pixel-level visual and interaction reference. This port rebuilds it as maintainable React without redesigning or simplifying anything. The backend contracts (`CaseView`, `available_actions`, command envelope, events) are the source of truth; the frontend holds no business logic.

## 1. What the prototype is

| Part | Lines | Becomes |
|---|---|---|
| `<helmet><style>` — all CSS, 46 media queries, 29 keyframes | 12–1502 | design-system tokens + component styles, ported rule for rule |
| `<x-dc>` template — markup for every screen | 1503–2264 | React components |
| Logic class — state, commands, policy, step derivation, Q&A, workflow validation and dry run | 2265–4717 | **deleted from the client**; replaced by API calls (plan §3). Only view-only code survives: canvas geometry, pan/zoom, splitters, character rendering |
| `assets/*.json` (glTF characters), `3c497….js` (three.js r160), PNGs | — | `public/characters/`, `three` npm dependency, `public/img/` |
| `window.__vera` hook | 2329 | used by the parity harness to put the prototype into a given state |

## 2. Stack

Next.js (App Router) · React · TypeScript strict · CSS Modules + CSS custom properties (no utility framework: the prototype's class-based CSS ports directly, which is the lowest-risk route to pixel parity) · TanStack Query for server state · `openapi-typescript` for generated API types · `three` for characters · Vitest + Testing Library · Playwright.

The app is a client of the FastAPI service. Next.js route handlers are not used for business endpoints; `next.config` rewrites `/api/*` to the API service so cookies and SSE are same-origin.

## 3. Directory layout and layer rules

```text
apps/web/
  prototype/                 reference only; never imported
  public/characters, img/
  src/
    app/                     routes, layouts, loading/error boundaries — composition only
    design-system/
      tokens.css             Handoff §9 colors, type, spacing, radius, motion
      primitives/            Button, RefChip, StatusSlot, Tabs, FilterTabs, Table, Drawer,
                             Splitter, Menu, Tooltip, Field, Skeleton, Banner
    components/              presentation components, grouped by area
      shell/ cases/ case/ evidence/ communications/ decision/ run/ activity/
      vera/ cardholder/ reviewer/ workflows/ specialists/ policies/ characters/
    features/                containers: one hook + one container per screen region
    api/
      schema.d.ts            generated from the backend OpenAPI document
      client.ts              typed fetch, error mapping to the typed error codes
      queries.ts             query keys and query functions
      commands.ts            runCommand()
      stream.ts              SSE subscription
    state/
      ui-store.ts            panel sizes, drawer open, canvas zoom, collapsed sections
      drafts.ts              in-progress text keyed by record id
    lib/                     formatting (money, dates), a11y helpers, reduced-motion hook
  tests/                     unit, parity, e2e
```

| Layer | May import | Must not |
|---|---|---|
| `design-system` | nothing internal | know about cases or the API |
| `components` | `design-system`, `lib`, types from `api/schema` | fetch, read stores, call commands, derive state from other fields |
| `features` | `components`, `api`, `state` | contain markup beyond composing components |
| `app` | `features` | contain logic |
| `api` | generated schema | hold state other than the query cache |

Enforced with ESLint `no-restricted-imports` per directory, so the boundary is checked in CI rather than by convention.

## 4. Component boundaries

Components are the ones contracted in Handoff §2; each is props-in, callbacks-out.

| Area | Presentation components | Container (`features/`) | Data |
|---|---|---|---|
| Shell | `Sidebar`, `TopBar`, `RoleSelector`, `EnvironmentPill` | `AppShell` | `GET /api/session` |
| Cases | `SummaryStrip`, `QueueTable`, `QueueRow`, `QueueFilters`, `RecentActivity` | `CasesScreen` | `/api/cases`, `/api/cases/summary` |
| Case | `CaseHeader`, `StatusRail`, `ProgressSteps`, `TaskCard`, `ActionBar`, `DraftEditor`, `IdentityVerification`, `DecisionChoices`, `ControlPlan`, `ParallelTracks`, `ClosureChecklist`, `ChargeImpact`, `CaseTabs` | `CaseWorkspace`, `TaskRegion` | `CaseView` |
| Evidence | `ComparisonTable`, `EvidenceRegister`, `RecordView` | `EvidenceTab` | `/evidence`, `/evidence/{id}` |
| Communications | `CommsList`, `MessageDetail`, `CallDetail`, `Transcript`, `IdentityDetail` | `CommunicationsTab` | `/communications` |
| Decision | `DecisionPanel`, `CreditTimeline`, `PacketView` | `DecisionTab` | `CaseView`, `/decision-packet` |
| Run | `RunMeta`, `ExecutionSafety`, `TraceTable` | `RunDetailsTab` | `/runs`, `/executions` |
| Activity | `ActivityTable`, `ActivityRow` | `ActivityRegion` | `/activity` + stream |
| Vera | `VeraRail`, `Message`, `WorkEntry`, `Composer`, `Chips` | `VeraPanel` | `/conversation`, `POST /ask`, stream |
| Cardholder | `RequestCard`, `AnswerOptions`, `AttachmentList`, `CardholderVerification` | `CardholderRequest` | `/api/requests/{id}` |
| Reviewer | `ReviewTask`, `PacketSections`, `ApprovalHistory`, `ControlApproval` | `ReviewScreen` | `CaseView` (reviewer / card-admin scope) |
| Workflows | `WorkflowToolbar`, `WorkflowCanvas`, `Minimap`, `StepLibrary`, `NodeInspector`, `ChecksPanel` | `WorkflowBuilder` | workflow version, draft, validation, checks |
| Specialists | `SpecialistList`, `SpecialistDetail`, `PermissionsDrawer`, `NewSpecialistDrawer`, `AddToWorkflowPanel`, `AppearanceEditor` | `SpecialistsScreen` | `/api/specialists` |
| Policies | `PolicyView`, `RuleGroup`, `PolicyDraftEditor` | `PoliciesScreen` | `/api/policies` |
| Characters | `SpecialistCharacter` (three.js canvas, working/waiting/idle) | — | appearance from specialist definition |

Two rules that keep business logic out:

1. **`ActionBar` renders `available_actions` verbatim** — label, style, enabled, `blocked_reason`, `safe_note`, `confirm`. Index 0 is the single primary button. There is no client-side mapping from step to buttons.
2. **`TaskCard` renders `CaseView.task`** — a discriminated union of blocks (`paragraphs`, `facts`, `questions`, `draft`, `idv`, `choices`, `controls`, `checklist`, `parallel_tracks`, `run_sequence`, notes). The component switches on block type, never on `step`.

`WorkflowCanvas` is ported from the prototype's own SVG renderer (edge geometry, ports, pan/zoom, minimap) rather than replaced with a graph library, because a library would change routing and spacing. Validation, dry-run and compare results come from the server; the canvas only displays them.

## 5. State ownership

| State | Owner | Notes |
|---|---|---|
| Case state, step, task, actions, policy, evidence, comms, activity, runs, conversation | **Server** → TanStack Query cache | never recomputed or patched optimistically for consequential commands |
| Workflow versions, drafts, validation, checks; specialists; policies | **Server** → Query cache | canvas drags apply to a local working copy and are sent as `PATCH` ops; server response replaces it |
| Tab, selected record/item, filter, sort, workflow version | **URL** search params | refresh and back/forward restore the view (US-J06) |
| Role being viewed | **Server session** | `POST /api/session/role`, then refetch; never a case command (US-K02) |
| Panel sizes, sidebar width/collapse, drawer open, canvas zoom/pan, expanded sections | `ui-store` (sessionStorage) | never sent to the server |
| Unsent text (draft edits, rationale, return note, cardholder note, composer) | `drafts` store keyed by record id | survives refetch and refresh; cleared on successful command |
| Scroll position | DOM | panels are never unmounted on refetch |

There is no client copy of the case model. A component that needs a value not present in `CaseView` is a backend change to the projection, not a client derivation.

## 6. API integration

**Types.** `schema.d.ts` is generated from the API's OpenAPI document; CI regenerates it and fails on a diff, so contract drift breaks the build (prompt: "API drift").

**Queries.** Keys: `['case', id]`, `['case', id, 'evidence']`, `['case', id, 'communications']`, `['case', id, 'activity']`, `['case', id, 'runs']`, `['cases', filter, sort]`, `['cases', 'summary']`, `['workflow', id, version]`, …  `placeholderData: keepPreviousData` everywhere so panels never blank; skeletons only when there is no cached data.

**Commands.** One function:

```ts
runCommand(caseId, action: ActionView, payload) →
  POST /api/cases/{id}/commands/{action.command}
  { idempotency_key: action.idempotency_key, expected_case_version, payload }
```

- `idempotency_key` is supplied by the server in each `ActionView` (the key templates in Handoff §10.6 are server logic; the client echoes the value). This is a small addition to the `ActionView` type.
- On success the returned `CaseView` is written straight into the query cache and dependent lists are invalidated.
- `409 stale_case_version` → refetch and re-render; consequential commands are never auto-retried.
- `502 adapter_failed_before_effect` and `504 adapter_uncertain` → no client retry loop; the UI shows what the refreshed `CaseView` says (`Nothing was issued. Safe to retry.` / `Checking the existing result`).
- Other typed errors render `blocked_reason` inline under the actions.

**Stream.** One SSE connection per open case. Audit events with a newer `case_version` trigger a `CaseView` refetch and append one Activity row; `run.step_*` events update work entries and the live transcript in place. If the stream drops, the client falls back to polling `CaseView` every few seconds and reconnects.

**Q&A.** `POST /ask` returns paragraphs, cites and `actions`; action buttons in a message go through the same `runCommand` or are navigation. Chat text is never interpreted client-side.

## 7. Visual and behavioral parity

Parity is tested, not eyeballed.

1. **Parity harness** (`tests/parity`): Playwright serves the prototype statically and the Next app against a seeded API, drives both to the same named state, and compares screenshots per region at 1440, 1200, 900 and 390 px. The prototype is put into each state through `window.__vera`; the app through replay fixtures. A states manifest lists each pair (e.g. `case/draft`, `case/idv-awaiting`, `review/stale`, `workflow/checks-compact`).
2. **Computed-style assertions** for tokens that screenshots can miss: font family/size/weight, colors, radii, min-widths, the 20 px status slot, the 364 px middle column, the 1280 px Vera drawer breakpoint.
3. **Interaction checks** ported from the handoff: splitter keyboard steps (±16, Shift ±64, Home/End), drawer slide 220 ms, local transitions 180–260 ms on the changed element only, no layout shift on status change, reduced-motion behavior, focus rings, row hover lean on queue characters.
4. **Budget:** per-region pixel difference threshold set after the first component lands and tightened, not loosened; any accepted difference is listed in `tests/parity/ACCEPTED.md` with the reason (expected for live data such as timestamps).

CSS is ported by moving each prototype rule into the owning component's module with its selectors intact, then replacing literals with tokens only where the value is identical. Breakpoints are kept exactly as authored (760, 899/900, 1100, 1200, 1279/1280 and the narrower ones) rather than normalized.

## 8. Migration sequence

Each slice is one or more small commits, lands behind a working route, and passes its parity states before the next starts. Backend dependencies refer to the tickets in the plan §14.

| Slice | Scope | Needs |
|---|---|---|
| F0 | Next.js scaffold, lint boundaries, tokens, fonts, parity harness with one trivial state | — |
| F1 | Primitives and shell: sidebar (resize, collapse, mobile drawer), top bar, role selector, environment pill | session endpoint (VER-002) |
| F2 | Cases: summary strip, queue, filters, sort, recent activity, queue characters | VER-001 |
| F3 | Case shell: header, status rail, progress steps, tabs, `TaskCard` + `ActionBar` from `available_actions`, charge impact | VER-002 |
| F4 | Evidence tab and record view; Activity; Run details | VER-003, VER-004 |
| F5 | Communications tab, draft editor, cardholder request view, attachments | VER-005 |
| F6 | Identity verification (analyst and cardholder sides), call detail and live transcript | VER-006, VER-007 |
| F7 | Decision tab, packet view, reviewer screen (approve, return, stale) | VER-008, VER-009 |
| F8 | Credit states, parallel tracks, dispute steps, control plan, card-admin approve/apply, closure checklist, monitoring | VER-010, VER-011 |
| F9 | Vera rail: conversation, work entries, chips, drawer below 1280 px | `/ask`, stream |
| F10 | Automations: workflow builder, checks panel, specialists, new-specialist drawer, policies | VER-014 |
| F11 | Full responsive and reduced-motion pass; Playwright role journeys; remove any remaining static fixtures | all |

VER-012 in the ticket list is therefore twelve frontend slices (VER-012-F0 … F11). F0 and F1 can start immediately in parallel with VER-001/002 because they own only `apps/web/src`.

## 9. Out of scope for the port

No new screens, copy changes, or restyling. No client-side policy, step, closure or workflow-validation logic. The prototype's demo drawer survives as calls to `/api/demo/*` and appears only when the session reports the synthetic environment.
