from twilio.rest import Client
import os
from dotenv import load_dotenv

load_dotenv()

client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

call = client.calls.create(
    to="+918530636952",        # your Indian mobile number
    from_=os.getenv("TWILIO_PHONE_NUMBER", "+19789177727"),
    url="https://alert-plus-calling-production.up.railway.app/incoming-call"
)

print(f"Call SID: {call.sid}")
