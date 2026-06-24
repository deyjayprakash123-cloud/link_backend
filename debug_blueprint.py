import asyncio
import os
from main import get_blueprint
from dotenv import load_dotenv

# Load env variables for Gemini API key
load_dotenv()

async def test_blueprint():
    # Verify GEMINI_API_KEY
    if not os.getenv("GEMINI_API_KEY"):
        print("WARNING: GEMINI_API_KEY environment variable is not set. Gemini calls will fall back to heuristics.")

    print("=== TEST 1: Valid GitHub Username (octocat) ===")
    try:
        result = await get_blueprint("octocat")
        print("SUCCESS! Output JSON:")
        import json
        print(json.dumps(result, indent=2))

        # Verify schema
        if isinstance(result, dict) and "blueprint" in result:
            blueprint = result["blueprint"]
            print(f"\nVerification: Received dict. Blueprint contains {len(blueprint)} items.")

            if len(blueprint) > 0:
                first = blueprint[0]
                required_keys = {"startup_name", "startup_description", "live_issues", "action_plan"}
                keys = set(first.keys())
                if required_keys.issubset(keys):
                    print("Verification: All required OSS Backdoor schema keys are present!")
                    # Validate live_issues structure
                    issues = first.get("live_issues", [])
                    print(f"  live_issues count: {len(issues)}")
                    if issues:
                        issue_keys = set(issues[0].keys())
                        expected_issue_keys = {"title", "url", "repo_name"}
                        if expected_issue_keys.issubset(issue_keys):
                            print(f"  First issue title: {issues[0].get('title')}")
                            print(f"  First issue repo:  {issues[0].get('repo_name')}")
                            print("  live_issues structure is VALID.")
                        else:
                            print(f"  WARNING: live_issues[0] missing keys. Found: {issue_keys}")
                    else:
                        print("  live_issues is empty (fallback link will show).")
                    print(f"  action_plan: {first.get('action_plan')}")
                else:
                    print(f"Verification FAILED: Missing keys. Found {keys}")
        else:
            print("Verification FAILED: Result is not a JSON dict with 'blueprint' key!")

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
