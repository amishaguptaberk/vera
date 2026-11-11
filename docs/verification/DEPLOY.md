# Deploy packaging

| | |
|---|---|
| Status | Merged, **not verified** |
| Commit | `ticket/DEPLOY` `eb2f8e5`, merged to main |
| Verifier | None. Not independently reviewed; no image was built or run (the build workspace has no Docker daemon). |

## What was checked

- `docker compose -f infra/docker-compose.yml config` parses.
- `bash -n infra/docker/entrypoint.sh` passes.
- `uv sync --frozen --no-dev` into a clean environment succeeds and `vera_api.app`, `vera_api.worker`, `vera_domain` import.

## Not checked

- `docker build` of either image, container start, healthchecks, the web image's `npm ci` / `npm run build`.
- Any deployment to a host. No host has been chosen.

## Notes

- The web app's API origin is fixed at build time (`VERA_API_ORIGIN` build argument).
- The deployment must run with `VERA_ENV=synthetic`: there is no login outside it.
