import os
import re
import json
import asyncio
import logging
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.responses import Response
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import VoiceResponse, Gather
from openai import AsyncOpenAI, RateLimitError, APITimeoutError, APIStatusError
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db, SessionLocal
from models import TriageRecord

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────

OPENAI_API_KEY      = os.environ["OPENAI_API_KEY"]
TWILIO_ACCOUNT_SID  = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN   = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_PHONE_NUMBER = os.environ["TWILIO_PHONE_NUMBER"]
SERVER_URL          = os.environ["SERVER_URL"]

# ─── Clients ─────────────────────────────────────────────────────────────────

# Hard timeouts so we NEVER let Twilio's ~15s HTTP limit expire.
# read=8s leaves ~7s buffer before Twilio cuts the call.
openai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    http_client=httpx.AsyncClient(
        timeout=httpx.Timeout(connect=3.0, read=8.0, write=3.0, pool=3.0)
    ),
    max_retries=0,   # No silent retries on a live voice call — fail fast
)

twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

app = FastAPI(title="Alert+ Voice Intake")

# ─── In-memory stores ─────────────────────────────────────────────────────────

call_sessions: dict[str, list[dict]] = {}

# Pending AI responses: call_sid → ai_text
# Used when we need to hold the caller while OpenAI responds slowly.
pending_responses: dict[str, asyncio.Future] = {}

# ─── Prompts ─────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are Priya, a health intake assistant for Alert+, a rural health program in India.
You speak both Hindi and English. The initial greeting and name request have already been delivered:
"Hello, I am Priya from Alert+. नमस्ते, मैं Alert+ से प्रिया बोल रही हूँ। Can I get your name? / क्या मैं आपका नाम जान सकती हूँ?"
Then detect the patient's preferred language and continue in that language.

Your job is to gently collect the following information in order:
1. Patient's full name (नाम)
2. District they are calling from (जिला)
3. Primary symptom (मुख्य लक्षण)
4. Duration in days (कितने दिनों से)
5. Severity on a scale of 1–10 (1 = mild, 10 = very severe)
6. Associated symptoms (साथ के लक्षण)
7. Any medication taken (कोई दवाई ली है?)

Rules:
- Speak slowly and clearly. Use simple everyday words, avoid medical jargon.
- Ask one question at a time. Be warm and reassuring.
- Do NOT follow a rigid script — respond naturally to what the patient says.
- Do NOT diagnose. You are only collecting information for the ASHA worker.
- If the patient seems distressed, acknowledge their discomfort before continuing.
- If the patient says something completely unrelated to health, gently redirect:
  "I'm here to help with health concerns. Could you tell me what you're feeling? / मैं स्वास्थ्य समस्याओं में मदद के लिए यहाँ हूँ।"

CRITICAL SAFETY RULES (override everything else):
- If the patient mentions chest pain, difficulty breathing, unconsciousness, severe injury,
  accident, heavy bleeding, or suicidal thoughts — IMMEDIATELY say:
  "Please call 112 right now for emergency help. / कृपया अभी 112 पर कॉल करें।"
  Then say a warm goodbye and do NOT continue intake questions.

After collecting all 9 pieces of information, say EXACTLY this and nothing else after:
"Thank you. I have noted your symptoms. An ASHA worker will contact you soon. /
धन्यवाद। आपके लक्षण नोट हो गए हैं। एक आशा कार्यकर्ता जल्द आपसे संपर्क करेंगी।"
Then on a new line output ONLY this JSON (no extra text, no markdown):
{"patient_name": "...", "district": "...", "primary_symptom": "...", "duration_days": 0, "severity": 0, "associated_symptoms": [], "medication_taken": null, "language": "hindi|english|mixed"}
"""

EXTRACTION_PROMPT = """
Extract structured data from the following patient call transcript.
Return ONLY a valid JSON object with no preamble or markdown.

JSON schema:
{
  "patient_name": string or null,
  "district": string or null,
  "primary_symptom": string,
  "duration_days": integer or null,
  "severity": integer (1-10) or null,
  "associated_symptoms": list of strings,
  "medication_taken": string or null,
  "urgency_level": "low" | "moderate" | "high",
  "language": "hindi" | "english" | "mixed"
}

Urgency rules:
- high: severity >= 8, or symptoms like chest pain, difficulty breathing, unconsciousness
- moderate: severity 5-7, or fever > 3 days, vomiting, diarrhoea
- low: severity <= 4, mild/short symptoms

Transcript:
"""

HOLD_MESSAGES = [
    "एक क्षण रुकिए… / Just a moment…",
    "हाँ, मैं नोट कर रही हूँ… / Yes, I'm noting that…",
    "समझ गई, एक सेकंड… / Understood, one second…",
]
_hold_idx = 0

def next_hold_message() -> str:
    global _hold_idx
    msg = HOLD_MESSAGES[_hold_idx % len(HOLD_MESSAGES)]
    _hold_idx += 1
    return msg


# ─── OpenAI helper ────────────────────────────────────────────────────────────

async def ask_openai(messages: list[dict], call_sid: str) -> str:
    """
    Call OpenAI with a hard timeout.
    Falls back to gpt-4o-mini if gpt-4o is rate-limited.
    Raises on all other errors so the caller can handle gracefully.
    """
    for model in ("gpt-4o", "gpt-4o-mini"):
        try:
            resp = await openai_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
            )
            if model != "gpt-4o":
                logger.warning(f"[{call_sid}] Used fallback model: {model}")
            return resp.choices[0].message.content.strip()

        except RateLimitError:
            if model == "gpt-4o":
                logger.warning(f"[{call_sid}] gpt-4o rate-limited, trying gpt-4o-mini")
                continue          # try mini
            raise                 # mini also rate-limited — give up

        except APITimeoutError:
            logger.error(f"[{call_sid}] OpenAI timeout on {model}")
            raise

        except APIStatusError as e:
            logger.error(f"[{call_sid}] OpenAI API error on {model}: {e.status_code} {e.message}")
            raise

    raise RuntimeError("All models exhausted")


# ─── TwiML helpers ────────────────────────────────────────────────────────────

def twiml_say_and_gather(text: str, action_url: str) -> str:
    """Speak text then listen for next input."""
    r = VoiceResponse()
    r.say(text, voice="Polly.Aditi", language="hi-IN")
    g = Gather(
        input="speech",
        action=action_url,
        method="POST",
        language="hi-IN",
        speech_timeout="auto",
        timeout=10,
    )
    r.append(g)
    # If silence after gather, re-prompt once
    r.redirect(action_url, method="POST")
    return str(r)


def twiml_error_hangup() -> str:
    r = VoiceResponse()
    r.say(
        "क्षमा करें, एक तकनीकी समस्या हुई। कृपया वापस कॉल करें। / "
        "I'm sorry, there was a technical issue. Please call back.",
        voice="Polly.Aditi",
        language="hi-IN",
    )
    r.hangup()
    return str(r)


# ─── Incoming call ────────────────────────────────────────────────────────────

@app.post("/incoming-call")
async def incoming_call(request: Request):
    form     = await request.form()
    call_sid = form.get("CallSid", "unknown")
    caller   = form.get("From", "unknown")
    logger.info(f"Incoming call: {call_sid} from {caller}")

    initial_greeting = (
        "Hello, I am Priya from Alert+. "
        "नमस्ते, मैं Alert+ से प्रिया बोल रही हूँ। "
        "Can I get your name and district? / आपका नाम और जिला क्या है?"
    )

    call_sessions[call_sid] = [
        {"role": "system",    "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": initial_greeting},
    ]

    xml = twiml_say_and_gather(initial_greeting, f"{SERVER_URL}/conversation")
    return Response(content=xml, media_type="application/xml")


# ─── Conversation turn ────────────────────────────────────────────────────────

@app.post("/conversation")
async def conversation(request: Request):
    form       = await request.form()
    call_sid   = form.get("CallSid", "unknown")
    user_input = form.get("SpeechResult", "").strip()
    caller     = form.get("From", "unknown")

    logger.info(f"[{call_sid}] User: {user_input}")

    conv_url = f"{SERVER_URL}/conversation"

    # ── No speech detected ────────────────────────────────────────────────────
    if not user_input:
        r = VoiceResponse()
        r.say(
            "क्या आप दोबारा बोल सकते हैं? / Could you please repeat that?",
            voice="Polly.Aditi",
            language="hi-IN",
        )
        g = Gather(input="speech", action=conv_url, method="POST",
                   language="hi-IN", speech_timeout="auto", timeout=10)
        r.append(g)
        return Response(content=str(r), media_type="application/xml")

    # ── Recover lost session (e.g. server restart mid-call) ──────────────────
    if call_sid not in call_sessions:
        logger.warning(f"[{call_sid}] Session not found — reinitialising")
        call_sessions[call_sid] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # ── Check if there's already a pending response for this call ─────────────
    # This handles the case where Twilio re-POSTs after our hold redirect.
    if call_sid in pending_responses:
        fut = pending_responses[call_sid]
        if fut.done():
            del pending_responses[call_sid]
            try:
                ai_text = fut.result()
                return _build_ai_response(call_sid, caller, ai_text, conv_url)
            except Exception:
                del call_sessions[call_sid]
                return Response(content=twiml_error_hangup(), media_type="application/xml")
        else:
            # Still waiting — play hold and redirect back
            r = VoiceResponse()
            r.say(next_hold_message(), voice="Polly.Aditi", language="hi-IN")
            r.redirect(f"{SERVER_URL}/hold?call_sid={call_sid}", method="POST")
            return Response(content=str(r), media_type="application/xml")

    # ── Normal path: append user input and call OpenAI ───────────────────────
    call_sessions[call_sid].append({"role": "user", "content": user_input})

    try:
        ai_text = await asyncio.wait_for(
            ask_openai(call_sessions[call_sid], call_sid),
            timeout=8.0,  # Hard wall — Twilio needs a response in <15s
        )
    except asyncio.TimeoutError:
        # OpenAI too slow: store a future, send hold TwiML, pick up on /hold
        logger.warning(f"[{call_sid}] OpenAI slow — sending hold TwiML")
        loop = asyncio.get_event_loop()
        fut  = loop.create_future()
        pending_responses[call_sid] = fut

        async def _bg_call():
            try:
                result = await ask_openai(call_sessions[call_sid], call_sid)
                if not fut.done():
                    fut.set_result(result)
            except Exception as e:
                if not fut.done():
                    fut.set_exception(e)

        asyncio.create_task(_bg_call())

        r = VoiceResponse()
        r.say(next_hold_message(), voice="Polly.Aditi", language="hi-IN")
        r.redirect(f"{SERVER_URL}/hold?call_sid={call_sid}", method="POST")
        return Response(content=str(r), media_type="application/xml")

    except Exception as e:
        logger.error(f"[{call_sid}] OpenAI error: {e}")
        call_sessions.pop(call_sid, None)
        return Response(content=twiml_error_hangup(), media_type="application/xml")

    return _build_ai_response(call_sid, caller, ai_text, conv_url)


# ─── Hold polling endpoint ────────────────────────────────────────────────────

@app.post("/hold")
async def hold(request: Request):
    """
    Twilio redirects here while we're waiting for a slow OpenAI response.
    We poll the future and either return the real response or hold again.
    """
    form     = await request.form()
    call_sid = form.get("call_sid") or request.query_params.get("call_sid", "")
    conv_url = f"{SERVER_URL}/conversation"

    fut = pending_responses.get(call_sid)
    if fut is None:
        # Session gone — just re-enter conversation normally
        return Response(
            content=twiml_say_and_gather(
                "क्षमा करें, कृपया दोबारा बोलें। / Sorry, please speak again.",
                conv_url,
            ),
            media_type="application/xml",
        )

    if fut.done():
        del pending_responses[call_sid]
        try:
            ai_text = fut.result()
            return _build_ai_response(call_sid, "unknown", ai_text, conv_url)
        except Exception:
            call_sessions.pop(call_sid, None)
            return Response(content=twiml_error_hangup(), media_type="application/xml")

    # Still waiting — hold again (Twilio will re-POST here after the say)
    r = VoiceResponse()
    r.say(next_hold_message(), voice="Polly.Aditi", language="hi-IN")
    r.redirect(f"{SERVER_URL}/hold?call_sid={call_sid}", method="POST")
    return Response(content=str(r), media_type="application/xml")


# ─── Shared response builder ──────────────────────────────────────────────────

def _build_ai_response(call_sid: str, caller: str, ai_text: str, conv_url: str) -> Response:
    """
    Given a final AI reply, build the correct TwiML:
    - If intake is complete (JSON present) → speak closing, hangup, save in bg
    - Otherwise → speak reply, gather next input
    """
    call_sessions[call_sid].append({"role": "assistant", "content": ai_text})
    logger.info(f"[{call_sid}] AI: {ai_text}")

    if '"primary_symptom"' in ai_text:
        spoken_part = ai_text.split("{")[0].strip()
        r = VoiceResponse()
        if spoken_part:
            r.say(spoken_part, voice="Polly.Aditi", language="hi-IN")
        r.hangup()
        asyncio.create_task(handle_call_complete(call_sid, caller, ai_text))
        return Response(content=str(r), media_type="application/xml")

    return Response(
        content=twiml_say_and_gather(ai_text, conv_url),
        media_type="application/xml",
    )


def log_full_transcript(call_sid: str, caller_phone: str, transcript: str):
    if transcript.strip():
        logger.info(
            "[%s] FULL TRANSCRIPT for %s\n%s\n[%s] END FULL TRANSCRIPT",
            call_sid,
            caller_phone or "unknown",
            transcript,
            call_sid,
        )
    else:
        logger.info("[%s] FULL TRANSCRIPT for %s is empty", call_sid, caller_phone or "unknown")


# ─── Call-complete handler (background task) ──────────────────────────────────

async def handle_call_complete(call_sid: str, caller_phone: str, ai_text: str):
    messages = call_sessions.pop(call_sid, [])
    pending_responses.pop(call_sid, None)

    transcript = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in messages
        if m.get("role") != "system"
    )
    log_full_transcript(call_sid, caller_phone, transcript)

    symptom_data = None
    try:
        json_match = re.search(r'\{.*\}', ai_text, re.DOTALL)
        if json_match:
            symptom_data = json.loads(json_match.group())
            symptom_data["patient_phone"] = caller_phone
    except Exception as e:
        logger.warning(f"[{call_sid}] Inline JSON parse failed: {e} — falling back to extraction")

    if not symptom_data:
        symptom_data = await extract_symptoms(transcript, caller_phone)

    if not symptom_data:
        logger.error(f"[{call_sid}] Could not extract symptom data")
        return

    async with SessionLocal() as db:
        await save_triage_record(db, caller_phone, call_sid, symptom_data, transcript)


# ─── Call-completed webhook (Twilio status callback) ─────────────────────────

@app.post("/call-completed")
async def call_completed(request: Request):
    form         = await request.form()
    call_sid     = form.get("CallSid", "")
    caller_phone = form.get("From", "")
    call_status  = form.get("CallStatus", "")
    logger.info(f"Call completed: {call_sid} | status: {call_status} | from: {caller_phone}")

    pending_responses.pop(call_sid, None)

    if call_sid in call_sessions:
        messages = call_sessions.pop(call_sid, [])
        transcript = "\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in messages
            if m.get("role") != "system"
        )
        log_full_transcript(call_sid, caller_phone, transcript)
        if transcript.strip():
            symptom_data = await extract_symptoms(transcript, caller_phone)
            if symptom_data:
                async with SessionLocal() as db:
                    await save_triage_record(db, caller_phone, call_sid, symptom_data, transcript)

    return Response(status_code=200)


# ─── Symptom extraction ───────────────────────────────────────────────────────

async def extract_symptoms(transcript: str, phone: str) -> Optional[dict]:
    try:
        resp = await openai_client.chat.completions.create(
            model="gpt-4o-mini",          # Cheap + fast for extraction
            messages=[
                {
                    "role": "system",
                    "content": "You extract medical and patient data from transcripts. Return only valid JSON.",
                },
                {"role": "user", "content": EXTRACTION_PROMPT + transcript},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        data["patient_phone"] = phone
        logger.info(f"Extracted data for {phone}: {data}")
        return data
    except Exception as e:
        logger.error(f"Extraction error: {e}")
        return None


# ─── DB save ─────────────────────────────────────────────────────────────────

async def save_triage_record(db, phone, call_sid, data, transcript):
    try:
        record = TriageRecord(
            caller_phone=phone,
            call_sid=call_sid,
            source="voice_ai",
            transcript=transcript,
            patient_name=data.get("patient_name"),
            district=data.get("district"),
            symptoms={
                "primary_symptom":     data.get("primary_symptom"),
                "associated_symptoms": data.get("associated_symptoms", []),
                "medication_taken":    data.get("medication_taken"),
            },
            severity=str(data.get("severity")),
            brief=data.get("primary_symptom"),
            # user_id intentionally omitted — no users table exists yet
        )
        db.add(record)
        await db.commit()
        logger.info(f"Saved record | call: {call_sid} | name: {data.get('patient_name')}")
    except Exception as e:
        logger.error(f"DB save error for {call_sid}: {e}")
        await db.rollback()
# ─── ASHA SMS ─────────────────────────────────────────────────────────────────

async def send_asha_sms(asha_worker, patient_phone: str, data: dict):
    name     = data.get("patient_name") or "Unknown"
    district = data.get("district") or "Unknown"
    symptom  = data.get("primary_symptom", "unknown")
    days     = data.get("duration_days", "?")
    severity = data.get("severity", "?")
    urgency  = data.get("urgency_level", "unknown").upper()
    meds     = data.get("medication_taken") or "None"
    assoc    = ", ".join(data.get("associated_symptoms", [])) or "None"

    body = (
        f"[Alert+] New report\n"
        f"Patient: {name} | District: {district}\n"
        f"Phone: {patient_phone}\n"
        f"Symptom: {symptom} for {days} day(s), severity {severity}/10\n"
        f"Also: {assoc}\n"
        f"Meds taken: {meds}\n"
        f"Urgency: {urgency}\n"
        f"Please follow up."
    )
    try:
        msg = twilio_client.messages.create(
            body=body,
            from_=TWILIO_PHONE_NUMBER,
            to=asha_worker.phone_number,
        )
        logger.info(f"SMS sent to ASHA {asha_worker.phone_number}: {msg.sid}")
    except Exception as e:
        logger.error(f"SMS error: {e}")


# ─── Debug endpoint ───────────────────────────────────────────────────────────

@app.get("/debug/records")
async def debug_records():
    async with SessionLocal() as db:
        result = await db.execute(
            select(TriageRecord).order_by(TriageRecord.created_at.desc()).limit(20)
        )
        records = result.scalars().all()
        return [
            {
                "id":           r.id,
                "user_id":      r.user_id,
                "patient_name": r.patient_name,
                "district":     r.district,
                "phone":        r.caller_phone,
                "symptoms":     r.symptoms,
                "severity":     r.severity,
                "created_at":   str(r.created_at),
                "asha_worker_id": r.asha_worker_id,
                "longitude":    r.longitude,
                "latitude":     r.latitude,
            }
            for r in records
        ]


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "alert-plus-voice-intake"}


# ─── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        log_level="info",
    )
