# Recordings

Model turns recorded from LIVE runs, replayed by `RecordedModelClient`.

Path: `evals/recordings/{specialist}/{prompt_version}/{case_id}.json`; the n-th model call of one
step (validation retries) is `{case_id}.{n}.json`. Produce with
`python -m vera_api.model_client record ...` (needs `NVIDIA_API_KEY`), review, commit. Changing a
prompt bumps `prompt_version` and needs re-recording. No product recordings yet.
