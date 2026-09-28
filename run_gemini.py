import os
import sys

# Set environment variables for Gemini
os.environ["LLM_PROVIDER"] = "gemini"
os.environ["LLM_API_KEY"] = os.environ.get("LLM_API_KEY", "")

# We must adjust sys.argv for make_submission.py
sys.argv = ["make_submission.py", "--output", "submission.jsonl"]

# Import and run make_submission
sys.path.insert(0, os.path.abspath("tools"))
import make_submission

if __name__ == "__main__":
    make_submission.main()
