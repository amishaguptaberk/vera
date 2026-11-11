# Vera tickets

Format and execution rules: docs/spec/Vera_Fable_Backend_Orchestration_Prompt.md.

| Ticket | Title | Blocked by |
|---|---|---|
| [VER-001](VER-001.md) | Persist and read CHG-1042 | — |
| [VER-002](VER-002.md) | Canonical commands and available actions | VER-001 |
| [VER-004](VER-004.md) | Evidence provenance, snapshots and conflicts | VER-002 |
| [VER-003](VER-003.md) | Model-backed investigation on LangGraph | VER-002, VER-004 |
| [VER-005](VER-005.md) | Follow-up, approval, reply and attachment | VER-004, VER-003 |
| [VER-006](VER-006.md) | OTP and push identity verification | VER-005 |
| [VER-007](VER-007.md) | Analyst-approved callback | VER-006 |
| [VER-008](VER-008.md) | Deterministic Policy Controller | VER-004 |
| [VER-009](VER-009.md) | Decision packet and reviewer action | VER-007, VER-008 |
| [VER-010](VER-010.md) | Credit, dispute and card controls | VER-009 |
| [VER-011](VER-011.md) | Final communication and closure | VER-010 |
| [VER-013](VER-013.md) | Evaluation suite and CI | VER-002 |
| [VER-014](VER-014.md) | Automations versioning | VER-003, VER-008 |
| [VER-015](VER-015.md) | Dashboard exposure: gross and net | VER-002 |
| [VER-012-F0](VER-012-F0.md) | Next.js scaffold, tokens and parity harness | — |
| [VER-012-F1](VER-012-F1.md) | Design-system primitives and app shell | VER-012-F0, VER-002 |
| [VER-012-F2](VER-012-F2.md) | Cases queue | VER-012-F1, VER-001 |
| [VER-012-F3](VER-012-F3.md) | Case workspace shell and task card | VER-012-F1, VER-002 |
| [VER-012-F4](VER-012-F4.md) | Evidence, activity and run details | VER-012-F3, VER-003, VER-004 |
| [VER-012-F5](VER-012-F5.md) | Communications and cardholder request | VER-012-F3, VER-005 |
| [VER-012-F6](VER-012-F6.md) | Identity verification and call detail | VER-012-F5, VER-006, VER-007 |
| [VER-012-F7](VER-012-F7.md) | Decision tab and reviewer screen | VER-012-F4, VER-009 |
| [VER-012-F8](VER-012-F8.md) | Credit, tracks, controls and closure | VER-012-F7, VER-010, VER-011 |
| [VER-012-F9](VER-012-F9.md) | Vera rail | VER-012-F3, VER-009 |
| [VER-012-F10](VER-012-F10.md) | Automations: workflows, specialists, policies | VER-012-F1, VER-014 |
| [VER-012-F11](VER-012-F11.md) | Responsive, motion and role journeys | VER-012-F8, VER-012-F9, VER-012-F10 |

First frontier: VER-001 and VER-012-F0 (no blockers, disjoint ownership).
