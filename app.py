import json
import os
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response

load_dotenv()

app = FastAPI()

TOKEN = os.getenv("TOKEN")
MYTOKEN = os.getenv("MYTOKEN")

@app.get("/")
def home():
    return Response(content="hello this is webhook setup", status_code=200)

@app.get("/webhook")
def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
):
    mode = hub_mode
    challenge = hub_challenge
    verify_token = hub_verify_token

    if mode and verify_token:
        if mode == "subscribe" and verify_token == MYTOKEN:
            return Response(content=challenge or "", status_code=200)
        raise HTTPException(status_code=403)

    raise HTTPException(status_code=400, detail="Missing verification parameters")

@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        body_param = await request.json()
    except json.JSONDecodeError:
        body_param = {}

    print(json.dumps(body_param, indent=2))

    if not body_param.get("object"):
        raise HTTPException(status_code=404)

    print("inside body param")

    try:
        value = body_param["entry"][0]["changes"][0]["value"]
        message = value["messages"][0]
        phone_number_id = value["metadata"]["phone_number_id"]
        sender = message["from"]
        message_body = message["text"]["body"]
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=404)

    print(f"phone number {phone_number_id}")
    print(f"from {sender}")
    print(f"body param {message_body}")
    graph_url = f"https://graph.facebook.com/v13.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "text": {
            "body": f"Hi.. I'm Prasath, your message is {message_body}",
        },
    }
    headers = {"Content-Type": "application/json"}
    params = {"access_token": TOKEN}
    response = requests.post(
        graph_url,
        params=params,
        json=payload,
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    return Response(status_code=200)

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "5000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
