import json

from vera_domain.voice import (
    CallStatus,
    Question,
    StartVerificationCall,
    dynamic_variables,
    extract_answers,
    mask_number,
    parse_elevenlabs,
)

QS = (
    Question("q1", "Did you place the Bayline Industrial Supply order?"),
    Question("q2", "Do you authorize the charge?"),
)


def _transcript(results: dict, lines=None) -> bytes:
    lines = lines or [
        {"role": "agent", "message": "Did you place the Bayline Industrial Supply order?"},
        {"role": "user", "message": "Yes, I placed it."},
        {"role": "agent", "message": "Do you authorize the charge?"},
        {"role": "user", "message": "I authorize it."},
    ]
    return json.dumps(
        {
            "type": "post_call_transcription",
            "event_timestamp": 1,
            "data": {
                "conversation_id": "conv_1",
                "status": "done",
                "transcript": lines,
                "analysis": {
                    "data_collection_results": results,
                    "call_successful": "success",
                    "transcript_summary": "Confirmed.",
                },
            },
        }
    ).encode()


def test_mask_number_keeps_only_last_four():
    assert mask_number("+15551234567") == "+1 *** *** 4567"
    assert "555123" not in mask_number("(555) 123-4567")


def test_dynamic_variables_carry_questions_not_number():
    inp = StartVerificationCall(
        "CASE-1", "CALL-1-1", 1, "+15551234567", "+1 *** *** 4567", "Confirm order", QS, True
    )
    dv = dynamic_variables(inp)
    assert dv["questions"].startswith("1. Did you place")
    assert dv["question_ids"] == "q1,q2"
    assert "5551234567" not in json.dumps(dv)


def test_grounded_answers_cite_transcript_lines_and_confidence():
    ev = parse_elevenlabs(
        _transcript(
            {
                "q1": {"data_collection_id": "q1", "value": "Yes, I placed it"},
                "q2": {"data_collection_id": "q2", "value": "I authorize it"},
            }
        )
    )
    assert ev.kind == "transcript_final" and ev.provider_call_id == "conv_1"
    ex = extract_answers(ev, QS)
    assert [(a.question_id, a.line_index) for a in ex.answers] == [("q1", 1), ("q2", 3)]
    assert ex.confidence == 1.0 and ex.rejected == ()


def test_non_approved_question_and_actions_are_rejected():
    ev = parse_elevenlabs(
        _transcript(
            {
                "approve_credit": {"data_collection_id": "approve_credit", "value": "yes"},
                "q1": {
                    "data_collection_id": "q1",
                    "value": "Yes, I placed it",
                    "action": "close_case",
                },
                "q2": {"data_collection_id": "q2", "value": "approve credit limit increase"},
            }
        )
    )
    ex = extract_answers(ev, QS)
    assert ex.answers == ()
    assert ex.confidence == 0.0
    assert len(ex.rejected) == 3


def test_agent_lines_do_not_ground_answers():
    ev = parse_elevenlabs(_transcript({"q2": {"value": "Do you authorize the charge"}}))
    assert extract_answers(ev, QS).answers == ()


def test_initiation_failure_maps_status_and_event_id_is_stable():
    raw = json.dumps(
        {
            "type": "call_initiation_failure",
            "data": {
                "conversation_id": "conv_2",
                "failure_reason": "busy",
                "metadata": {"type": "twilio", "body": {"CallSid": "CA1"}},
            },
        }
    ).encode()
    a, b = parse_elevenlabs(raw), parse_elevenlabs(raw)
    assert a.kind == "initiation_failure" and a.status is CallStatus.BUSY
    assert a.event_id == b.event_id and a.event_id.startswith("sha256:")
    assert parse_elevenlabs(b'{"type":"post_call_audio","data":{}}').kind == "ignored"
