# Recordings

Model turns replayed by `RecordedModelClient` (REPLAY mode).

Path: `evals/recordings/{specialist}/{prompt_version}/{case_id}.json`; the n-th model call of one
step (tool rounds, then validation retries) is `{case_id}.{n}.json`. A turn with `tool_calls`
asks the gateway to run real `read_field` reads; the final turn holds the JSON output.

## Provenance: authored reference outputs (not captured from a model)

The investigation recordings (`charge_investigator`, `related_transaction_investigator`,
`receipt_document_reviewer`, prompt `v1`, case `CHG-1042`) were **written by hand** as faithful
reference outputs for what the v1 prompts ask, because the build workspace cannot reach the model
provider. Each file says so: `"provenance": "authored-reference"` and
`"model_id": "authored-reference"`, and the runs API shows that model id on every replayed step.
They are pending capture from a real model.

To capture real recordings on a machine that can reach the provider:

```bash
python -m vera_api.investigation dump-requests --case-id CHG-1042   # writes evals/requests/...
python -m vera_api.model_client probe                               # pins VERA_MODEL_ID
python -m vera_api.model_client record --specialist charge_investigator --prompt-version v1 \
  --case-id CHG-1042 --request evals/requests/charge_investigator/v1/CHG-1042.json
```

`record` captures one model turn; a step that calls tools needs one recording per turn (`--n 1`,
...) with the tool results appended to the request messages. Review, then commit. Changing a
prompt bumps `prompt_version` and needs re-recording.
