import os
import sys
import json
import time

def main():
    if len(sys.argv) < 2:
        print("Usage: python chat_to_job.py <prompt_with_input>")
        sys.exit(1)

    input_text = sys.argv[1]

    # In a real scenario, this script might parse the input,
    # interact with an external API, or format data before
    # passing it back to the job's next steps.

    print("--- chat_to_job.py executed ---")
    print(f"Received input length: {len(input_text)}")

    # We can output a JSON that the next step or the AutomationController could parse if needed
    result = {
        "status": "success",
        "processed_input": f"Processed: {input_text[:50]}...",
        "timestamp": time.time()
    }

    print(json.dumps(result))
    sys.exit(0)

if __name__ == "__main__":
    main()
