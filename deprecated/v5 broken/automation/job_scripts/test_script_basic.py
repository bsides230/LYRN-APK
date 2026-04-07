import sys
import time
import json
import argparse

def main():
    parser = argparse.ArgumentParser(description="Basic Test Script")
    parser.add_argument("instructions", nargs="?", help="Job instructions passed as argument")
    args = parser.parse_args()

    # Log start
    print(json.dumps({"status": "starting", "script": "test_script_basic.py", "timestamp": time.time()}))

    # Simulate work
    time.sleep(2)

    # Process input (just echo it back in the result)
    result = {
        "status": "success",
        "message": "Basic test script completed successfully.",
        "received_instructions": args.instructions,
        "timestamp": time.time()
    }

    # Print JSON result to stdout
    print(json.dumps(result))

    # Exit with 0 (Success)
    sys.exit(0)

if __name__ == "__main__":
    main()
