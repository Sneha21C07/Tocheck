"""
Repo 1: User Query Service
Microservice with GET endpoint accepting 2 query/path parameters,
retrieves dummy data, and writes the retrieved record into `<param1>User-Detail.json`.
"""

import os
import json
from pathlib import Path
from flask import Flask, request, jsonify

app = Flask(__name__)

# Shared storage path accessible across both repos
SHARED_STORAGE_DIR = Path(os.getenv("SHARED_STORAGE_DIR", str(Path(__file__).resolve().parent.parent / "shared_data")))
SHARED_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# In-memory dummy dataset
DUMMY_USERS = {
    "USR101": {
        "userId": "USR101",
        "name": "Sarah Connor",
        "email": "sarah.connor@cyberdyne.io",
        "department": "Engineering",
        "role": "Lead Architect",
        "region": "US-East",
        "status": "ACTIVE",
        "salary": 145000,
        "skills": ["Java", "Microservices", "Spring Boot", "Python"],
    },
    "USR102": {
        "userId": "USR102",
        "name": "John Doe",
        "email": "john.doe@enterprise.org",
        "department": "Finance",
        "role": "Financial Analyst",
        "region": "EU-West",
        "status": "ACTIVE",
        "salary": 115000,
        "skills": ["Excel", "Financial Modeling", "SQL"],
    },
    "USR103": {
        "userId": "USR103",
        "name": "Alex Mercer",
        "email": "alex.mercer@biotech.com",
        "department": "DevOps",
        "role": "Site Reliability Engineer",
        "region": "AP-South",
        "status": "ACTIVE",
        "salary": 130000,
        "skills": ["Kubernetes", "Terraform", "CI/CD", "Docker"],
    },
}


def save_user_detail_file(param1: str, data: dict) -> Path:
    """
    Saves retrieved user data into `<param1>User-Detail.json` and `<param1>-User-Detail.json`
    in both local repo directory and shared storage directory.
    """
    clean_p1 = "".join(c for c in param1 if c.isalnum() or c in ("-", "_"))
    filename = f"{clean_p1}User-Detail.json"

    # Save to shared storage directory
    shared_file_path = SHARED_STORAGE_DIR / filename
    with open(shared_file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # Also save to local repo directory
    local_file_path = Path(__file__).resolve().parent / filename
    with open(local_file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return shared_file_path


@app.route("/api/users", methods=["GET"])
def get_user_by_query():
    """
    GET API accepting 2 query parameters:
    - param1: userId (or id)
    - param2: department (or dept / region)
    Example: /api/users?userId=USR101&department=Engineering
    """
    user_id = request.args.get("userId") or request.args.get("id") or request.args.get("param1")
    department = request.args.get("department") or request.args.get("dept") or request.args.get("param2")

    if not user_id or not department:
        return (
            jsonify({
                "error": "Missing required query parameters",
                "required": ["userId (param1)", "department (param2)"],
                "example": "/api/users?userId=USR101&department=Engineering",
            }),
            400,
        )

    user = DUMMY_USERS.get(user_id)
    if not user:
        # Create dynamic dummy user if ID not in predefined dictionary
        user = {
            "userId": user_id,
            "name": f"User {user_id}",
            "email": f"{user_id.lower()}@domain.com",
            "department": department,
            "role": "Specialist",
            "status": "ACTIVE",
        }
    else:
        # Clone user and attach/verify queried department
        user = dict(user)
        user["queriedDepartment"] = department

    # Store retrieved data into `<1st query param>User-Detail.json`
    saved_path = save_user_detail_file(user_id, user)

    return jsonify({
        "message": "User detail retrieved and saved successfully",
        "output_file": saved_path.name,
        "saved_path": str(saved_path),
        "data": user,
    }), 200


@app.route("/api/users/<user_id>/<department>", methods=["GET"])
def get_user_by_path(user_id: str, department: str):
    """
    GET API accepting 2 path parameters:
    - user_id (param1)
    - department (param2)
    Example: /api/users/USR101/Engineering
    """
    user = DUMMY_USERS.get(user_id)
    if not user:
        user = {
            "userId": user_id,
            "name": f"User {user_id}",
            "email": f"{user_id.lower()}@domain.com",
            "department": department,
            "role": "Specialist",
            "status": "ACTIVE",
        }
    else:
        user = dict(user)
        user["queriedDepartment"] = department

    saved_path = save_user_detail_file(user_id, user)

    return jsonify({
        "message": "User detail retrieved and saved successfully via path parameters",
        "output_file": saved_path.name,
        "saved_path": str(saved_path),
        "data": user,
    }), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    print(f"Starting Repo 1 (User Query Service) on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
