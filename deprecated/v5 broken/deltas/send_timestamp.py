import time
import urllib.request
import urllib.error
import json
from datetime import datetime, timezone, timedelta

# Target API endpoint
API_URL = "http://localhost:8000/api/deltas/update"

# The header requires an X-Token if authentication is enabled on the server.
# Set your token here if needed, or leave blank if Auth is turned off.
TOKEN = ""

HEADERS = {"Content-Type": "application/json"}
if TOKEN:
    HEADERS["X-Token"] = TOKEN

print("Starting timestamp delta stream...")
print(f"Targeting: {API_URL}")

try:
    # Get the current time in Central Time (UTC-6 or UTC-5 depending on DST, this is a simplified UTC-6 for demonstration)
    # Using a fixed offset for Central Standard Time (-6 hours)
    offset = timedelta(hours=-6)
    central_tz = timezone(offset, name='CST')
    now = datetime.now(central_tz)
    formatted_time = now.strftime("%Y-%m-%d %I:%M:%S %p %Z")

    payload = {
        "name": "System Time (CT)",
        "value": formatted_time
    }

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(API_URL, data=data, headers=HEADERS, method='POST')

    try:
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                print(f"[{formatted_time}] Successfully sent timestamp.")
            else:
                print(f"[{formatted_time}] Failed to send. Server responded with: {response.status}")
    except urllib.error.URLError as e:
        print(f"Connection error: {e}")

except Exception as e:
    print(f"Error: {e}")
