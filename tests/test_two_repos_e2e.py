"""
End-to-End Test for Repo 1 (user-query-service) and Repo 2 (user-update-service).
Tests:
1. Repo 1 GET endpoint with 2 query parameters (userId + department).
2. Verifies that `<param1>User-Detail.json` is created with retrieved data.
3. Repo 2 POST endpoint with request body.
4. Verifies that `<param1>User-Detail.json` is updated with the request body.
5. Repo 1 & 2 path parameters.
"""

import json
import unittest
from pathlib import Path
import importlib.util

BASE_DIR = Path(__file__).resolve().parent.parent


def load_flask_app(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repo1_module = load_flask_app("repo1_app", BASE_DIR / "repo1-user-query-service" / "app.py")
repo2_module = load_flask_app("repo2_app", BASE_DIR / "repo2-user-update-service" / "app.py")


class TestTwoReposEndToEnd(unittest.TestCase):

    def setUp(self):
        self.repo1_client = repo1_module.app.test_client()
        self.repo2_client = repo2_module.app.test_client()
        self.shared_dir = BASE_DIR / "shared_data"
        self.shared_dir.mkdir(parents=True, exist_ok=True)

    def test_end_to_end_flow(self):
        # -------------------------------------------------------------
        # STEP 1: Invoke Repo 1 GET endpoint with 2 query parameters
        # -------------------------------------------------------------
        param1 = "USR101"
        param2 = "Engineering"
        res1 = self.repo1_client.get(f"/api/users?userId={param1}&department={param2}")
        self.assertEqual(res1.status_code, 200)

        json1 = res1.get_json()
        self.assertEqual(json1["data"]["userId"], "USR101")
        self.assertEqual(json1["data"]["name"], "Sarah Connor")
        self.assertEqual(json1["data"]["queriedDepartment"], "Engineering")

        expected_filename = f"{param1}User-Detail.json"
        self.assertEqual(json1["output_file"], expected_filename)

        # Verify file actually created on disk
        target_file = self.shared_dir / expected_filename
        self.assertTrue(target_file.exists(), f"File {target_file} was not created!")

        with open(target_file, "r", encoding="utf-8") as f:
            file_data = json.load(f)
        self.assertEqual(file_data["userId"], "USR101")
        self.assertEqual(file_data["role"], "Lead Architect")

        # -------------------------------------------------------------
        # STEP 2: Invoke Repo 2 POST endpoint with request body
        # -------------------------------------------------------------
        update_payload = {
            "userId": "USR101",
            "role": "Distinguished Principal Architect",
            "department": "Global Architecture",
            "salary": 185000,
            "status": "PROMOTED_EXECUTIVE",
            "promotionYear": 2026,
        }

        res2 = self.repo2_client.post(
            "/api/users/update",
            data=json.dumps(update_payload),
            content_type="application/json",
        )
        self.assertEqual(res2.status_code, 200)

        json2 = res2.get_json()
        self.assertEqual(json2["updated_data"]["role"], "Distinguished Principal Architect")
        self.assertEqual(json2["updated_data"]["salary"], 185000)

        # -------------------------------------------------------------
        # STEP 3: Verify the file has been updated with the request body
        # -------------------------------------------------------------
        with open(target_file, "r", encoding="utf-8") as f:
            updated_file_data = json.load(f)

        self.assertEqual(updated_file_data["userId"], "USR101")
        self.assertEqual(updated_file_data["name"], "Sarah Connor")  # Preserved original
        self.assertEqual(updated_file_data["role"], "Distinguished Principal Architect")  # Updated
        self.assertEqual(updated_file_data["salary"], 185000)  # Updated
        self.assertEqual(updated_file_data["promotionYear"], 2026)  # New field added
        self.assertEqual(updated_file_data["_lastUpdatedBy"], "repo2-user-update-service")

    def test_path_parameter_flow(self):
        # Test Repo 1 with path parameters
        res1 = self.repo1_client.get("/api/users/USR102/Finance")
        self.assertEqual(res1.status_code, 200)
        json1 = res1.get_json()
        self.assertEqual(json1["data"]["userId"], "USR102")

        # Test Repo 2 updating it with path parameter
        res2 = self.repo2_client.post(
            "/api/users/USR102/update",
            data=json.dumps({"salary": 135000, "status": "SENIOR"}),
            content_type="application/json",
        )
        self.assertEqual(res2.status_code, 200)

        target_file = self.shared_dir / "USR102User-Detail.json"
        with open(target_file, "r", encoding="utf-8") as f:
            updated_file_data = json.load(f)
        self.assertEqual(updated_file_data["salary"], 135000)
        self.assertEqual(updated_file_data["status"], "SENIOR")


if __name__ == "__main__":
    unittest.main()
