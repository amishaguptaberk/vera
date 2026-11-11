import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CallPanel } from "@/features/verify";
import type { CallbackDetail } from "@/features/verify/contract";
import { act, call, caseWith } from "../fixtures/verify/fixtures";
import { mockFetch, renderWithProviders, session } from "./helpers";

afterEach(() => vi.unstubAllGlobals());

const FULL = "+1 415 555 0142";
const notFound = () =>
  new Response(JSON.stringify({ code: "not_found", message: "nope" }), {
    status: 404,
  });

const startAct = act("start_callback", {
  label: "Start call",
  payload_defaults: {
    questions: [{ id: "q1", text: "Did you place the Bayline order?" }],
    target_record_id: "PRF-4418",
    masked_number: "•••• 0142",
    purpose: "Confirm whether the cardholder made the disputed purchase",
  },
});

function mockVoice(get: () => CallbackDetail | null, actions = caseWith([])) {
  return mockFetch((c) => {
    if (c.url === "/api/session") return session("analyst");
    if (c.url === "/api/cases/CHG-1042") return actions;
    if (c.url === "/api/cases/CHG-1042/callbacks") {
      const k = get();
      return k ? [k] : [];
    }
    if (c.url === "/api/cases/CHG-1042/callbacks/CB-0001") return get();
    if (c.method === "POST") return { ok: true };
    return notFound();
  });
}

describe("Voice verification call", () => {
  it("consent checkbox gates Start call and goes into the start_callback payload", async () => {
    const calls = mockVoice(() => null, caseWith([startAct]));
    renderWithProviders(<CallPanel caseId="CHG-1042" />);
    expect(
      await screen.findByText("Did you place the Bayline order?"),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Confirm whether the cardholder made the disputed purchase",
      ),
    ).toBeTruthy();
    const start = screen.getByRole("button", { name: "Start call" });
    expect((start as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(
      screen.getByLabelText("Cardholder consented to this verification call"),
    );
    expect((start as HTMLButtonElement).disabled).toBe(false);
    await userEvent.click(start);
    await waitFor(() =>
      expect(calls.some((x) => x.method === "POST")).toBe(true),
    );
    const body = JSON.parse(calls.find((x) => x.method === "POST")!.body!);
    expect(body.payload.consent_recorded).toBe(true);
    expect(body.payload.questions).toEqual([
      { id: "q1", text: "Did you place the Bayline order?" },
    ]);
  });

  it("no Start call button when the server does not offer start_callback", async () => {
    mockVoice(() => null, caseWith([]));
    renderWithProviders(<CallPanel caseId="CHG-1042" />);
    await screen.findByText("No messages or calls yet.");
    expect(screen.queryByRole("button", { name: /start call/i })).toBeNull();
  });

  it("appends transcript lines in place as 2 s polls return", async () => {
    let cur = call({
      status: "ringing",
      provider: "elevenlabs",
      transcript: [{ seq: 1, speaker: "agent", text: "Hi, this is Vera." }],
    });
    mockVoice(() => cur);
    renderWithProviders(<CallPanel caseId="CHG-1042" />);
    await screen.findByText("“Hi, this is Vera.”");
    const tr = screen.getByTestId("transcript");
    const first = tr.firstElementChild;
    cur = call({
      status: "in_progress",
      provider: "elevenlabs",
      transcript: [
        ...cur.transcript,
        { seq: 2, speaker: "contact", text: "Yes, that was me." },
      ],
    });
    await screen.findByText("“Yes, that was me.”", undefined, {
      timeout: 4000,
    });
    expect(screen.getByTestId("transcript")).toBe(tr);
    expect(tr.firstElementChild).toBe(first);
    expect(tr.children).toHaveLength(2);
  });

  it("citation chip highlights the cited transcript line", async () => {
    mockVoice(() =>
      call({
        status: "completed",
        provider: "elevenlabs",
        transcript: [
          { seq: 1, speaker: "agent", text: "Did you place the order?" },
          { seq: 2, speaker: "contact", text: "Yes, I did." },
        ],
        result: {
          result: "confirmed",
          confidence: "high",
          answers: [{ question_id: "q1", answer: "Yes", cited_lines: [2] }],
        },
      }),
    );
    renderWithProviders(<CallPanel caseId="CHG-1042" />);
    const res = await screen.findByTestId("structured-result");
    expect(within(res).getByText("high")).toBeTruthy();
    const line2 = document.getElementById("call-line-2")!;
    expect(line2.getAttribute("aria-current")).toBeNull();
    await userEvent.click(
      within(res).getByRole("button", { name: "Transcript line 2" }),
    );
    expect(line2.getAttribute("aria-current")).toBe("true");
    expect(
      document.getElementById("call-line-1")!.getAttribute("aria-current"),
    ).toBeNull();
  });

  it.each([
    ["simulated", "Simulated call"],
    ["elevenlabs", "Live voice call"],
  ] as const)("provider %s is labelled %s", async (provider, label) => {
    mockVoice(() => call({ status: "in_progress", provider }));
    renderWithProviders(<CallPanel caseId="CHG-1042" />);
    const p = await screen.findByTestId("call-provider");
    expect(p.textContent).toContain(label);
    expect(document.body.textContent).not.toMatch(/elevenlabs/i);
  });

  it("renders only the masked number, never a full phone number", async () => {
    mockVoice(
      () =>
        ({
          ...call({ status: "in_progress", masked_number: "•••• 0142" }),
          phone: FULL,
          number: FULL,
        }) as CallbackDetail,
    );
    renderWithProviders(<CallPanel caseId="CHG-1042" />);
    await screen.findByText(/•••• 0142/);
    expect(document.body.textContent).not.toContain(FULL);
    expect(document.body.textContent).not.toMatch(/\d{3}[ -]?\d{4}/);
  });

  it("masks a full number even if the server sends one as masked_number", async () => {
    mockVoice(() => call({ status: "in_progress", masked_number: FULL }));
    renderWithProviders(<CallPanel caseId="CHG-1042" />);
    await screen.findByText(/•••• 0142/);
    expect(document.body.textContent).not.toContain("555");
  });
});

describe("Voice call read model (CallbackDetail.voice)", () => {
  const voice = (o: Record<string, unknown> = {}) => ({
    provider: "simulated",
    simulated: true,
    provider_call_id: "sim-1",
    masked_number: "•••• 0142",
    purpose: "Confirm the disputed purchase",
    call_status: "in_progress",
    started_at: "2026-11-10T15:05:00Z",
    ended_at: null,
    transcript_version: 1,
    structured_answers: [],
    rejected: [],
    confidence: null,
    ...o,
  });

  it("reads provider, masked number, purpose and live status from voice", async () => {
    mockVoice(() => ({ ...call(), voice: voice() }) as CallbackDetail);
    renderWithProviders(<CallPanel caseId="CHG-1042" />);
    const p = await screen.findByTestId("call-provider");
    expect(p.textContent).toContain("Simulated call");
    expect(screen.getByText(/•••• 0142/)).toBeTruthy();
    expect(screen.getByText("Confirm the disputed purchase")).toBeTruthy();
    expect(screen.getByText("Live")).toBeTruthy();
  });

  it("cites structured_answers line_index and shows confidence as sent", async () => {
    mockVoice(
      () =>
        ({
          ...call({
            status: "confirmed",
            transcript: [
              { seq: 0, speaker: "agent", text: "Did you place the order?" },
              { seq: 1, speaker: "contact", text: "Yes." },
            ],
          }),
          voice: voice({
            provider: "elevenlabs",
            simulated: false,
            call_status: "completed",
            structured_answers: [
              { question_id: "q1", answer: "yes", line_index: 1 },
            ],
            confidence: 0.92,
          }),
        }) as CallbackDetail,
    );
    renderWithProviders(<CallPanel caseId="CHG-1042" />);
    const res = await screen.findByTestId("structured-result");
    expect(within(res).getByText("0.92")).toBeTruthy();
    await userEvent.click(
      within(res).getByRole("button", { name: "Transcript line 1" }),
    );
    expect(
      document.getElementById("call-line-1")!.getAttribute("aria-current"),
    ).toBe("true");
    expect(screen.getByTestId("call-provider").textContent).toContain(
      "Live voice call",
    );
  });
});

describe("Server-offered call controls", () => {
  it.each([
    ["end_callback", "End call", "in_progress"],
    ["escalate_callback", "Escalate", "completed"],
  ] as const)("%s posts the callback id", async (command, label, status) => {
    const calls = mockVoice(
      () => call({ status }),
      caseWith([act(command, { label })]),
    );
    renderWithProviders(<CallPanel caseId="CHG-1042" />);
    await userEvent.click(await screen.findByRole("button", { name: label }));
    await waitFor(() =>
      expect(calls.some((x) => x.method === "POST")).toBe(true),
    );
    const body = JSON.parse(calls.find((x) => x.method === "POST")!.body!);
    expect(body.payload.callback_id).toBe("CB-0001");
  });
});
