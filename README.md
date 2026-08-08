# WhatsApp Connect

Receives WhatsApp messages from the Meta Cloud API and holds them for a chatbot to collect.

Two endpoints:

| Method | Path        | Who calls it | Purpose |
| ------ | ----------- | ------------ | ------- |
| `GET`  | `/webhook`  | Meta         | One-time verification handshake when you save the callback URL |
| `POST` | `/webhook`  | Meta         | Delivers incoming messages |
| `GET`  | `/messages` | Your chatbot | Returns everything received since the last call, then clears it |

Replies are **not** sent by this service. Your chatbot posts them straight to
`https://graph.facebook.com/<version>/<phone-number-id>/messages`.

## Environment

Copy `.env.example` to `.env` and fill it in. Never commit `.env`.

| Variable              | Required | Purpose |
| --------------------- | -------- | ------- |
| `MYTOKEN`             | yes      | Your own verify token. Must match the **Verify token** field in the Meta dashboard. The app refuses to start without it. |
| `APP_SECRET`          | strongly recommended | Meta app secret, used to check the `X-Hub-Signature-256` header. If unset, incoming webhooks are **not** verified. |
| `TOKEN`               | for sending | Access token your chatbot uses against the Graph API. Not read by this service. |
| `PHONE_NUMBER_ID`     | for sending | Business phone number ID. Not read by this service. |
| `GRAPH_API_VERSION`   | for sending | e.g. `v25.0`. Not read by this service. |
| `LOG_LEVEL`           | no       | Defaults to `INFO`. |
| `MAX_STORED_MESSAGES` | no       | Buffer size, defaults to `500`. |
| `PORT`                | no       | Defaults to `8000`. Render sets this automatically. |

## Run locally

```bash
uv sync
uv run python main.py
```

Expose it so Meta can reach it:

```bash
ngrok http 8000
```

## Meta setup

1. **App Dashboard → WhatsApp → Configuration → Webhook**
   - Callback URL: `https://<your-host>/webhook`
   - Verify token: the value of `MYTOKEN`
2. Subscribe to the **`messages`** field on the **WhatsApp Business Account** object.
3. Subscribe your app to the WABA — this is separate from step 2 and webhooks will
   not arrive without it:

   ```
   POST https://graph.facebook.com/<version>/<WABA-ID>/subscribed_apps
   ```

   Confirm with `GET .../subscribed_apps` — your app must appear in the list.

Free-form text replies only reach a number that messaged you within the last 24
hours. Outside that window you must use an approved template.

## Deploy on Render

- **Build:** `pip install -r requirements.txt` or `uv sync`
- **Start:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Set `MYTOKEN` and `APP_SECRET` as environment variables in the Render dashboard.
- Update the Meta callback URL to your Render URL.

Two things to know about the free tier: the service spins down when idle, so the
first webhook after a quiet period can fail while it cold-starts, and every
restart clears the in-memory buffer.

## Limits

Messages are stored in process memory, so:

- a restart drops anything not yet collected;
- `GET /messages` is a destructive read — messages are returned exactly once, and
  a chatbot crash after the fetch loses them;
- only one worker process can be run. `--workers 2` gives each process its own
  separate buffer.

Use a database or queue instead if any of that matters.
