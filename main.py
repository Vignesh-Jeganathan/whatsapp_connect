import hashlib
import hmac
import json
import logging
import os
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("whatsapp")

VERIFY_TOKEN = os.getenv("MYTOKEN")
APP_SECRET = os.getenv("APP_SECRET")
MAX_STORED_MESSAGES = int(os.getenv("MAX_STORED_MESSAGES", "500"))

if not VERIFY_TOKEN:
    raise RuntimeError("MYTOKEN is not set - the webhook cannot be verified safely")

if not APP_SECRET:
    logger.warning("APP_SECRET is not set - incoming webhooks will NOT be signature checked")

class MessageBuffer:
    def __init__(self, maxlen: int) -> None:
        self._items: deque[dict] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def extend(self, items: list[dict]) -> None:
        with self._lock:
            self._items.extend(items)

    def drain(self) -> list[dict]:
        with self._lock:
            items = list(self._items)
            self._items.clear()
            return items

class SeenMessageIds:
    def __init__(self, maxlen: int = 1000) -> None:
        self._ids: dict[str, None] = {}
        self._maxlen = maxlen
        self._lock = threading.Lock()

    def is_duplicate(self, message_id: str) -> bool:
        with self._lock:
            if message_id in self._ids:
                return True
            self._ids[message_id] = None
            overflow = len(self._ids) - self._maxlen
            for old in list(self._ids)[:overflow] if overflow > 0 else []:
                del self._ids[old]
            return False

buffer = MessageBuffer(MAX_STORED_MESSAGES)
seen = SeenMessageIds()

app = FastAPI(title="WhatsApp Connect", description="Receives WhatsApp messages from Meta.")

def to_iso(raw_timestamp: Any) -> str:
    try:
        return datetime.fromtimestamp(int(raw_timestamp), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return datetime.now(timezone.utc).isoformat()


def parse_message(message: dict) -> dict | None:
    message_id = message.get("id")
    sender = message.get("from")

    if not message_id or not sender:
        logger.warning("skipping message with no id or sender")
        return None

    if message.get("type") != "text":
        logger.info("ignoring %s message %s", message.get("type"), message_id)
        return None

    text = (message.get("text") or {}).get("body")
    if not text:
        logger.info("ignoring text message %s with an empty body", message_id)
        return None

    return {
        "id": message_id,
        "from": sender,
        "text": text,
        "timestamp": to_iso(message.get("timestamp")),
    }


def extract_messages(payload: dict) -> list[dict]:
    parsed: list[dict] = []

    for entry in payload.get("entry") or []:
        for change in (entry or {}).get("changes") or []:
            value = (change or {}).get("value") or {}
            for message in value.get("messages") or []:
                try:
                    result = parse_message(message or {})
                except Exception:
                    logger.exception("could not parse a message; skipping it")
                    continue
                if result:
                    parsed.append(result)

    return parsed


def valid_signature(body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    try:
        expected = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, header.removeprefix("sha256="))
    except Exception:
        logger.exception("signature verification failed unexpectedly")
        return False

@app.get("/webhook", response_class=PlainTextResponse)
def verify(
    mode: str | None = Query(None, alias="hub.mode"),
    challenge: str | None = Query(None, alias="hub.challenge"),
    token: str | None = Query(None, alias="hub.verify_token"),
):
    if mode == "subscribe" and token and hmac.compare_digest(token, VERIFY_TOKEN):
        logger.info("webhook verified")
        return PlainTextResponse(challenge or "")
    logger.warning("webhook verification rejected (mode=%s)", mode)
    raise HTTPException(status_code=403, detail="Verification failed")

@app.post("/webhook")
async def receive(request: Request, x_hub_signature_256: str | None = Header(None)):
    raw = await request.body()
    if APP_SECRET and not valid_signature(raw, x_hub_signature_256):
        logger.warning("rejected webhook with an invalid signature")
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("webhook body was not valid JSON")
        return {"received": []}
    if not isinstance(payload, dict):
        logger.warning("webhook body was not a JSON object")
        return {"received": []}
    messages = extract_messages(payload)
    fresh = [m for m in messages if not seen.is_duplicate(m["id"])]
    for message in fresh:
        logger.info("from %s: %s", message["from"], message["text"])
    if fresh:
        buffer.extend(fresh)
    skipped = len(messages) - len(fresh)
    if skipped:
        logger.info("ignored %d duplicate message(s)", skipped)
    return {"received": fresh}


@app.get("/messages")
def messages():
    items = buffer.drain()
    return {"count": len(items), "messages": items}

@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    if request.method == "POST" and request.url.path == "/webhook":
        return JSONResponse(status_code=200, content={"received": []})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
