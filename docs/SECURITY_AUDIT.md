# TeachFlow Security Audit

**Review date:** 2026-09-08
**Original audit:** 2026-02-13, preserved in
[`archive/audits/SECURITY_AUDIT_2026-02-13.md`](../archive/audits/SECURITY_AUDIT_2026-02-13.md)
**Scope:** Current Flask application, deployment configuration, and regression
tests. This is a code review, not a penetration test or a deployment approval.

## Current summary

The original audit reported 3 Critical, 5 High, 7 Medium, and 7 Low findings.
This review confirms that the three Critical findings and most previously
identified hardening work are fixed. The remaining material risks are primarily
about operating a single-teacher, local-first application as a networked,
multi-user service.

| Severity | Open | Partially fixed | Fixed | Total original |
|---|---:|---:|---:|---:|
| Critical | 0 | 0 | 3 | 3 |
| High | 1 | 0 | 4 | 5 |
| Medium | 3 | 2 | 2 | 7 |
| Low | 3 | 0 | 4 | 7 |

**Current release risk:** local Mock demos are supported. A shared or
network-exposed deployment still requires ownership isolation, request-rate
limiting, session expiry, error handling, and input hardening before it can be
described as suitable for that use case.

## Rechecked original findings

### Critical

| ID | Original finding | Status | Current evidence |
|---|---|---|---|
| SEC-001 | No CSRF protection | **Fixed** | `src/web/app.py` initializes `CSRFProtect`; forms expose tokens. `tests/test_security.py::TestCSRFProtection` rejects an unprotected POST, and `tests/test_lesson_workflow.py::test_ten_mb_file_and_real_csrf` exercises a tokened submission. |
| SEC-002 | Login open redirect | **Fixed** | `src/web/blueprints/auth.py::_is_safe_url` rejects schemes, netlocs, and `//` paths before redirecting. `tests/test_security.py::TestOpenRedirect` covers external, protocol-relative, and safe relative targets. |
| SEC-003 | Predictable SECRET_KEY fallback | **Fixed** | `src/web/app.py::_load_or_generate_secret_key` generates `secrets.token_hex(32)` and persists it to the ignored `.env` when possible. `tests/test_security.py::TestSecretKey` asserts the former default is not used. Docker no longer embeds a default secret; `tests/test_deployment_config.py` verifies it. |

### High

| ID | Original finding | Status | Current evidence |
|---|---|---|---|
| SEC-004 | Hardcoded default credentials | **Fixed** | The unused constants were removed from `src/web/blueprints/helpers.py`. `src/web/blueprints/auth.py` sends an empty installation to `/setup`; `tests/test_security.py::TestDefaultCredentials` proves a public default login is rejected. |
| SEC-005 | API keys persisted in `config.yaml` | **Fixed** | `src/web/config_utils.py::save_api_key_to_env` writes secrets to ignored `.env`; `src/web/blueprints/settings.py` removes `api_key` before config persistence. `.gitignore` excludes `config.yaml`; `tests/test_security.py::TestApiKeyNotInConfig` covers the path. |
| SEC-006 | No multi-tenancy / IDOR protection | **Open** | `src/database.py::Class` and related resources have no owner foreign key, and queries are not scoped to `flask_session["user_id"]`. This remains a blocker for multi-user shared deployments. |
| SEC-007 | Unauthenticated generated-file serving | **Fixed** | `src/web/app.py` uses `_image_login_required` and `<filename>` routes for generated images and uploads. `tests/test_security.py::TestImageServing` verifies anonymous requests redirect to login. |
| SEC-008 | Debug startup recommended in docs | **Fixed** | Current README and installation guidance launch without `debug=True`; `rg "debug=True" README.md docs src` finds only this archived finding, not an active instruction. |

### Medium

| ID | Original finding | Status | Current evidence |
|---|---|---|---|
| SEC-009 | No rate limiting | **Partially fixed** | `src/agents.py` applies the configured cost/call limit through `src/cost_tracking.py::check_rate_limit` before non-Mock generation. It does not rate-limit login, all API routes, or request volume, so a network deployment still needs a request limiter. |
| SEC-010 | Missing session-cookie flags | **Fixed** | `src/web/app.py` sets `SESSION_COOKIE_HTTPONLY=True` and `SESSION_COOKIE_SAMESITE="Lax"`, with `Secure` enabled when `FLASK_HTTPS` is set. `tests/test_security.py::TestSessionCookieFlags` covers the first two flags. |
| SEC-011 | No session regeneration after login | **Fixed** | `src/web/blueprints/auth.py` calls `flask_session.clear()` before writing authenticated session values. `tests/test_security.py::TestSessionSecurity::test_session_cleared_on_login` covers it. |
| SEC-012 | Password change leaves session active | **Fixed** | `src/web/blueprints/auth.py::settings_password` clears the session and redirects to login after a successful change. `tests/test_security.py::TestSessionSecurity::test_session_cleared_on_password_change` covers it. |
| SEC-013 | Unpinned dependencies | **Fixed** | `requirements.txt` pins the declared runtime packages. `tests/test_csv_sanitization.py` includes dependency-pinning checks. |
| SEC-014 | CSV formula injection | **Fixed** | Exporters call `src/export_utils.py::sanitize_csv_cell`; `tests/test_csv_sanitization.py` covers dangerous prefixes across CSV export types. |
| SEC-015 | Unbounded, exposed audit log | **Partially fixed** | `/api/audit-log` and its clear route require login in `src/web/blueprints/settings.py`. `src/llm_provider.py` still stores an unbounded in-memory list and prompt/response previews, so retention limits and redaction remain necessary. |

### Low

| ID | Original finding | Status | Current evidence |
|---|---|---|---|
| SEC-016 | Weak password policy | **Fixed** | Setup and password change reject passwords shorter than eight characters in `src/web/blueprints/auth.py`; `tests/test_security.py::TestPasswordPolicy` covers setup. |
| SEC-017 | Logout via GET | **Fixed** | `/logout` accepts POST only in `src/web/blueprints/auth.py`; `tests/test_security.py::TestLogoutMethod` expects GET to return 405. |
| SEC-018 | No session timeout | **Open** | `src/web/app.py` does not configure `PERMANENT_SESSION_LIFETIME` or set sessions permanent. |
| SEC-019 | No 404/500 error handlers | **Open** | `src/web/app.py` has a targeted 413 handler only; no application 404/500 handlers were found. |
| SEC-020 | Provider errors may expose internals | **Open** | `src/web/blueprints/settings.py::test_provider` returns `str(e)` for unexpected exceptions. It should log server-side detail and return a generic message. |
| SEC-021 | LIKE wildcard behavior | **Open** | Search routes such as `src/web/blueprints/content.py` interpolate `%` and `_` into `ilike` patterns. SQL parameterization prevents SQL injection, but escaping is still needed for predictable search behavior. |
| SEC-022 | Prompt injection through lesson content | **Open** | Lesson content is still passed into generation context without a dedicated untrusted-content boundary. Teacher review mitigates output risk but does not harden the prompt path. |

## Evidence run for this review

- `python -m pytest tests/test_security.py tests/test_ui_polish.py tests/test_deployment_config.py -q` — 35 passed.
- `python -m pytest tests/test_csv_sanitization.py -q` — verifies CSV mitigation and dependency pinning.
- `docker compose config -q` with a supplied throwaway `SECRET_KEY` — validates the Compose interpolation.
- Targeted source searches for default credentials, `debug=True`, error handlers,
  rate limiting, ownership fields, and wildcard search patterns.

## Next actions before a shared deployment

1. Add ownership columns and enforce them on every resource query and mutation.
2. Apply request-rate limits, especially to login and generation endpoints.
3. Bound and redact the API audit log.
4. Configure a session lifetime and custom 404/500 handlers.
5. Sanitize unexpected provider errors, escape LIKE wildcards, and add explicit
   prompt-content delimiters.
