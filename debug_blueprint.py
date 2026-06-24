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
        if isinstance(result, dict) and "blueprint" in result and "viral_assets" in result:
            blueprint = result["blueprint"]
            viral_assets = result["viral_assets"]
            print(f"\nVerification: Received dict. Blueprint contains {len(blueprint)} items.")
            print(f"Viral Assets profile_markdown len: {len(viral_assets.get('profile_markdown', ''))}")
            print(f"Viral Assets headline_bio: {viral_assets.get('headline_bio')}")
            
            if len(blueprint) > 0:
                first = blueprint[0]
                required_keys = {"startup_name", "match_percentage", "matching_skills", "missing_skills", "infrastructure_depth", "diagnostic_log", "audited_file", "code_review_log", "interview_question", "recommended_refactor"}
                keys = set(first.keys())
                if required_keys.issubset(keys):
                    print("Verification: All required schema keys (including code audit and refactor keys) are present!")
                else:
                    print(f"Verification FAILED: Missing keys. Found {keys}")
        else:
            print("Verification FAILED: Result is not a JSON dict with 'blueprint' and 'viral_assets' keys!")
            
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
