"""Canonical synthetic seed and reset. Reset TRUNCATEs (row triggers do not fire); triggers stay."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session
from vera_domain.clock import Clock, demo_local
from vera_domain.enums import CaseState, CaseStep, Role

from vera_api.evidence import seed_evidence
from vera_api.intake import EMPTY_SNAPSHOT, POLICY_VERSION, WORKFLOW_VERSION, submit_report
from vera_api.models import (
    ALL_TABLES,
    Cardholder,
    CardTransaction,
    Case,
    Merchant,
    User,
    UserRole,
)
from vera_api.policy import seed_policy_v1

SAM = "usr-sam-rivera"
DANA = "usr-dana-okafor"
PRIYA = "chd-priya-shah"
PRIYA_USER = "usr-priya-shah"


@dataclass(frozen=True)
class DisplayRow:
    case_id: str
    merchant: str
    amount_cents: int
    label: str
    state: CaseState
    step: CaseStep
    due: tuple[int, int, int, int] | None  # month, day, hour, minute (2026)
    credit_cents: int = 0


DISPLAY_ROWS = [
    DisplayRow(
        "CHG-1029",
        "Brightline Logistics",
        118000,
        "Response overdue",
        CaseState.WAITING_ON_CARDHOLDER,
        CaseStep.NORESP1,
        (11, 10, 7, 0),
    ),
    DisplayRow(
        "CHG-1039",
        "Halcyon Travel",
        162000,
        "Waiting on reviewer",
        CaseState.REVIEWER_PENDING,
        CaseStep.WAITRV,
        (11, 10, 14, 0),
    ),
    DisplayRow(
        "CHG-1051",
        "Northstar Equipment",
        120000,
        "Needs investigation",
        CaseState.INVESTIGATING,
        CaseStep.INTAKE,
        (11, 10, 17, 0),
    ),
    DisplayRow(
        "CHG-1036",
        "Kessler Supply",
        396000,
        "Dispute submitted",
        CaseState.DISPUTE_PREPARED,
        CaseStep.DSP_SUBMIT,
        (11, 11, 10, 0),
        396000,
    ),
    DisplayRow(
        "CHG-1033",
        "Atlas Office Supply",
        42000,
        "Waiting on cardholder",
        CaseState.WAITING_ON_CARDHOLDER,
        CaseStep.WAITING,
        (11, 12, 12, 0),
    ),
]


def _merchant_id(name: str) -> str:
    return "mer-" + name.lower().replace(" ", "-")


def reset_database(session: Session, clock: Clock, tz: str) -> None:
    session.execute(text(f"truncate table {', '.join(ALL_TABLES)} restart identity cascade"))
    _seed(session, clock, tz)
    session.commit()


def _seed(session: Session, clock: Clock, tz: str) -> None:
    seed_policy_v1(session)
    session.add_all([User(id=SAM, name="Sam Rivera"), User(id=DANA, name="Dana Okafor")])
    session.flush()
    session.add_all(
        [
            UserRole(user_id=SAM, role=Role.ANALYST.value),
            UserRole(user_id=SAM, role=Role.OPS_ADMIN.value),
            UserRole(user_id=DANA, role=Role.REVIEWER.value),
            UserRole(user_id=DANA, role=Role.CARD_ADMIN.value),
        ]
    )
    session.add(
        Cardholder(
            id=PRIYA,
            name="Priya Shah",
            profile_id="PRF-4418",
            phone="(415) 555-0182",
            email="priya.shah@halden.example",
        )
    )
    session.flush()
    session.add(User(id=PRIYA_USER, name="Priya Shah", cardholder_id=PRIYA))
    session.flush()
    session.add(UserRole(user_id=PRIYA_USER, role=Role.CARDHOLDER.value))
    names = {"Northstar Equipment"} | {r.merchant for r in DISPLAY_ROWS}
    session.add_all([Merchant(id=_merchant_id(n), name=n) for n in sorted(names)])
    session.flush()

    posted = demo_local(tz, 2026, 11, 8, 14, 30)
    session.add(
        CardTransaction(
            id="TXN-1042",
            merchant_id=_merchant_id("Northstar Equipment"),
            cardholder_id=PRIYA,
            amount_cents=284000,
            currency="USD",
            card_last4="4418",
            posted_at=posted,
        )
    )
    for row in DISPLAY_ROWS:
        session.add(
            CardTransaction(
                id="TXN-" + row.case_id.removeprefix("CHG-"),
                merchant_id=_merchant_id(row.merchant),
                cardholder_id=PRIYA,
                amount_cents=row.amount_cents,
                currency="USD",
                card_last4="4418",
                posted_at=posted,
            )
        )
    session.flush()

    for row in DISPLAY_ROWS:
        session.add(
            Case(
                id=row.case_id,
                transaction_id="TXN-" + row.case_id.removeprefix("CHG-"),
                state=row.state.value,
                step=row.step.value,
                owner_id=SAM,
                due_at=demo_local(tz, 2026, *row.due) if row.due else None,
                workflow_version=WORKFLOW_VERSION,
                policy_version=POLICY_VERSION,
                evidence_snapshot=EMPTY_SNAPSHOT,
                credit_cents=row.credit_cents,
                credit_status="issued" if row.credit_cents else None,
                live=False,
                display_label=row.label,
            )
        )
    session.flush()

    submit_report(
        session,
        report_id="REP-1042",
        transaction_id="TXN-1042",
        statement="I do not recognize this charge.",
        now=demo_local(tz, 2026, 11, 10, 8, 52),
        due_at=demo_local(tz, 2026, 11, 10, 12, 0),
    )
    seed_evidence(session, clock.now())
