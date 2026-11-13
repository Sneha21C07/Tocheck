"""
Secure helper script to push repo1-user-query-service to Sneha21C07/Tocheck.
Masks credentials and ensures safe authentication.
"""

import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

pat = os.getenv("GITHUB_PAT")
if not pat:
    print("Error: GITHUB_PAT not found in .env")
    exit(1)

repo_dir = BASE_DIR / "repo1-user-query-service"
remote_target = f"https://x-access-token:{pat}@github.com/Sneha21C07/Tocheck.git"

print(f"Pushing {repo_dir.name} to https://github.com/Sneha21C07/Tocheck ...")

# Run git push with masked credentials
proc = subprocess.run(
    ["git", "push", remote_target, "main", "--force"],
    cwd=str(repo_dir),
    capture_output=True,
    text=True,
)

clean_stdout = proc.stdout.replace(pat, "***")
clean_stderr = proc.stderr.replace(pat, "***")

print(f"Git exit code: {proc.returncode}")
if clean_stdout.strip():
    print("Output:", clean_stdout.strip())
if clean_stderr.strip():
    print("Diagnostics:", clean_stderr.strip())

if proc.returncode == 0:
    print("\nSUCCESS: repo1-user-query-service successfully pushed to Sneha21C07/Tocheck!")
else:
    print("\nFAILED: Could not push to remote repository.")
