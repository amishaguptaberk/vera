from enum import StrEnum


class CaseState(StrEnum):
    REPORTED = "reported"
    INVESTIGATING = "investigating"
    WAITING_ON_CARDHOLDER = "waiting_on_cardholder"
    RESPONSE_RECEIVED = "response_received"
    EVIDENCE_REVIEW = "evidence_review"
    CALLBACK_PENDING = "callback_pending"
    CALLBACK_COMPLETED = "callback_completed"
    DECISION_PENDING = "decision_pending"
    POLICY_BLOCKED = "policy_blocked"
    CREDIT_ELIGIBLE = "credit_eligible"
    REVIEWER_PENDING = "reviewer_pending"
    CREDIT_APPROVED = "credit_approved"
    CREDIT_ISSUED = "credit_issued"
    DISPUTE_PREPARED = "dispute_prepared"
    REMEDIATION_PENDING = "remediation_pending"
    MONITORING = "monitoring"
    CLOSED = "closed"
    HELD = "held"


class CaseStep(StrEnum):
    INTAKE = "intake"
    WORKING = "working"
    DRAFT = "draft"
    WAITING = "waiting"
    NORESP1 = "noresp1"
    NORESP2 = "noresp2"
    RESPONSE = "response"
    IDV = "idv"
    VERIFY = "verify"
    CALLFAIL = "callfail"
    PACKET = "packet"
    DECIDE = "decide"
    RETURNED = "returned"
    STALE = "stale"
    WAITRV = "waitrv"
    ISSUE = "issue"
    CREDIT_CHECK = "credit_check"
    CONTROLS = "controls"
    CTL_PREP = "ctl_prep"
    DSP_PREPARE = "dsp_prepare"
    DSP_OPEN = "dsp_open"
    DSP_REVIEW = "dsp_review"
    DSP_SUBMIT = "dsp_submit"
    DSP_FAILED = "dsp_failed"
    WAITCTL = "waitctl"
    CTL_APPLY = "ctl_apply"
    FINALPREP = "finalprep"
    FINAL = "final"
    CLOSE = "close"
    MONITORING = "monitoring"
    CLOSED = "closed"
    ONHOLD = "onhold"


class StateKind(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    REVIEW = "review"
    WAITING = "waiting"


class Role(StrEnum):
    ANALYST = "analyst"
    OPS_ADMIN = "ops_admin"
    REVIEWER = "reviewer"
    CARD_ADMIN = "card_admin"
    CARDHOLDER = "cardholder"
    SYSTEM = "system"
    SPECIALIST = "specialist"
    POLICY_CONTROLLER = "policy_controller"
    ADAPTER = "adapter"


class EventType(StrEnum):
    REPORT_RECEIVED = "report.received"
    CASE_CREATED = "case.created"
    REPORT_LINKED = "report.linked"
    CASE_OPENED = "case.opened"
    CASE_HELD = "case.held"
    CASE_RESUMED = "case.resumed"
    CASE_REASSIGNED = "case.reassigned"
    POLICY_EVALUATED = "policy.evaluated"


class RunEventType(StrEnum):
    """Stream events for specialist steps (plan §8)."""

    RUN_STEP_STARTED = "run.step_started"
    RUN_STEP_SUCCEEDED = "run.step_succeeded"
    RUN_STEP_FAILED = "run.step_failed"
