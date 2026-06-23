import asyncio
import os
from main import get_blueprint
from dotenv import load_dotenv

# Load env variables for Gemini API key
load_dotenv()

async def test_blueprint():
    # Verify GEMINI_API_KEY
    if not os.getenv("GEMINI_API_KEY"):
        print("WARNING: GEMINI_API_KEY environment variable is not set. The Gemini calls will fail.")

    print("=== TEST 1: Valid GitHub Username (octocat) ===")
    try:
        result = await get_blueprint("octocat")
        print("SUCCESS! Output JSON:")
        import json
        print(json.dumps(result, indent=2))
        
        # Verify schema
        if isinstance(result, list):
            print(f"\nVerification: Received list of {len(result)} items.")
            if len(result) > 0:
                first = result[0]
                required_keys = {"startup_name", "match_percentage", "matching_skills", "missing_skills", "proof_repos", "diagnostic_log"}
                keys = set(first.keys())
                if required_keys.issubset(keys):
                    print("Verification: All required schema keys (including proof_repos) are present!")
                else:
                    print(f"Verification FAILED: Missing keys. Found {keys}")
        else:
            print("Verification FAILED: Result is not a JSON list!")
            
    except Exception as e:
        print("ERROR: Test 1 failed with exception:")
        import traceback
        traceback.print_exc()

    print("\n=== TEST 2: Invalid GitHub Username ===")
    try:
        result = await get_blueprint("invalid_username_12345_xyz_abc_test")
        print("Response:")
        import json
        print(json.dumps(result, indent=2))
        if isinstance(result, dict) and "error" in result:
            print("SUCCESSFUL ERROR HANDLING: Clean JSON error dict returned!")
        else:
            print("FAILED: Result is not an error dictionary.")
    except Exception as e:
        print("FAILED: Test 2 raised an unexpected exception:")
        print(e)

if __name__ == "__main__":
    asyncio.run(test_blueprint())
