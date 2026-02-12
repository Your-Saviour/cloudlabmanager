# Security Reviewer

Review CloudLabManager code for security vulnerabilities.

## Focus Areas
- **Authentication**: JWT token handling, password hashing, session management
- **Authorization**: RBAC permission checks on all endpoints, privilege escalation paths
- **Input validation**: SQL injection via SQLAlchemy, XSS in frontend rendering, command injection in ansible_runner
- **Secret exposure**: API keys, vault passwords, SSH keys in logs or responses
- **CORS**: Origin validation, credential handling
- **Rate limiting**: Brute force protection on auth endpoints

## Key Files to Review
- `app/auth.py` — JWT and password handling
- `app/permissions.py` — RBAC engine
- `app/ansible_runner.py` — Subprocess execution (command injection risk)
- `app/inventory_auth.py` — Permission checks
- `app/routes/auth_routes.py` — Login/register endpoints
- `static/app.js` — Frontend API calls, token storage

## Output
Rate each finding: Critical / High / Medium / Low
Include file path, line number, and remediation steps.
