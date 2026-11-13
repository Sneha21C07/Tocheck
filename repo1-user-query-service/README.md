# Repo 1: User Query Service (`repo1-user-query-service`)

Microservice that exposes a GET endpoint accepting 2 query or path parameters.
It retrieves user records from its dummy dataset and automatically persists the record into `<param1>User-Detail.json`.

---

## Endpoints

### 1. GET with 2 Query Parameters
- **URL**: `/api/users`
- **Method**: `GET`
- **Query Parameters**:
  - `userId` (1st parameter - used as prefix for file creation)
  - `department` (2nd parameter)
- **Example**:
  ```bash
  curl "http://localhost:5001/api/users?userId=USR101&department=Engineering"
  ```

### 2. GET with 2 Path Parameters
- **URL**: `/api/users/<user_id>/<department>`
- **Method**: `GET`
- **Example**:
  ```bash
  curl "http://localhost:5001/api/users/USR101/Engineering"
  ```

---

## File Creation Behavior
Once data is retrieved, it generates a JSON file formatted as:
```text
<param1>User-Detail.json
```
For example, querying `USR101` generates:
- `USR101User-Detail.json` in both the local directory and the shared data folder (`../shared_data/USR101User-Detail.json`).

---

## Running the Service
```bash
python app.py
```
Default port: `5001`
