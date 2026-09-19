# Configure separately hosted Modal models

Use the API base URL and model name from each endpoint's request example. Shared and dedicated endpoints use the same client routing; confirm billing mode in Modal before estimating costs. Our stored token prices describe Shared Endpoints and do not account for dedicated GPU compute.

Put these settings in the ignored `.env.modal` file (use `.env` for local-only runs):

```dotenv
MODAL_PROXY_TOKEN=wk-YOUR-ID.ws-YOUR-SECRET
ABTRACT_BASE_URL_DEEPSEEK_V4_1_FLASH=https://YOUR-DEEPSEEK-ENDPOINT.us-west.modal.direct/v1
ABTRACT_BASE_URL_GLM_5_3_FLASH=https://YOUR-GLM-ENDPOINT.us-west.modal.direct/v1
GEMINI_API_KEY=YOUR-GEMINI-KEY
GEMINI_MODEL=gemini-3.8-flash
ABTRACT_DASHBOARD_PASSWORD=YOUR-PASSWORD
ABTRACT_JOB_SWARM_BUDGET_USD=5
```

Each `ABTRACT_BASE_URL_<ID>` overrides `MODAL_INFERENCE_BASE_URL` for that model. Include `/v1`. Model name discovery and its cache are separate for each endpoint. To override a served model name, use `ABTRACT_MODEL_DEEPSEEK_V4_1_FLASH` or `ABTRACT_MODEL_GLM_5_3_FLASH` with the name shown by the endpoint. Keep `ABTRACT_OPTIMIZER_MODEL` unset for Gemini rewrites, and omit `ABTRACT_DATA_DIR` from cloud secrets so the image uses the mounted `/data` Volume.

If Optimize reports `401 UNAUTHENTICATED` / `ACCESS_TOKEN_TYPE_UNSUPPORTED`, Google has rejected the Gemini credential. `AQ.` is a valid new Google auth-key format; it should not be replaced with an RSA key or a Modal token. Check the key and its linked service account/project in [Google AI Studio](https://ai.google.dev/gemini-api/docs/api-key). After replacing `GEMINI_API_KEY` in the private `.env.modal`, update `abtract-secrets` with `--force` and redeploy. Authentication failures are not retried automatically. A rejection from a direct request using `x-goog-api-key` also points to the key/project rather than SDK request formatting.

Check authentication, routing, and served model names without generating inference:

```bash
uv run python scripts/check_endpoints.py --env-file .env.modal
```

After filling in the Gemini key, deploy from the repository root:

```bash
uv run modal secret create abtract-secrets --from-dotenv .env.modal
uv run modal deploy deploy.py
uv run python scripts/import_demo_site.py --modal
```

Add `--force` to the secret command when replacing an existing secret, then redeploy. Open the printed dashboard URL and sign in as `abtract` with the password from `.env.modal`. The demo lives at `<site URL>/s/demo/v0/`; the product's **Try with the demo site** button fills that URL in. The default **Full audit** runs the selected grid in parallel and shows live results. Choose **Quick scan** for an optional smaller sample. Pushing to GitHub alone does not update Modal; redeploy after changing the code.

Sources: [Modal endpoint API and authentication](https://modal.com/docs/guide/endpoints), [Shared Endpoints](https://modal.com/docs/guide/shared-endpoints), [Dedicated Endpoint billing](https://modal.com/docs/guide/dedicated-endpoints).
