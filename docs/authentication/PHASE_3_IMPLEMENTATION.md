# FALCON Phase 3 Authentication Implementation

Phase 3 status: complete.

## 1. Purpose

Phase 3 establishes the authentication and account-security boundary used by
all later FALCON financial modules.

The implementation provides:

- email and password registration;
- email-verification challenges;
- secure login;
- short-lived bearer access tokens;
- protected refresh-session cookies;
- refresh-token rotation;
- refresh-token replay detection;
- session-family revocation;
- logout;
- password recovery;
- current-user authentication;
- unified public authentication failures;
- PostgreSQL-backed security lifecycle tests.

## 2. Public API

The authentication API is available below `/api/v1/auth`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/register` | Create an email/password account |
| POST | `/login` | Authenticate and create a refresh session |
| POST | `/refresh` | Rotate the refresh token and issue access |
| POST | `/logout` | Revoke the current refresh session |
| POST | `/email-verification/request` | Request a verification message |
| POST | `/email-verification/confirm` | Consume a verification token |
| POST | `/password-reset/request` | Request a password-reset message |
| POST | `/password-reset/confirm` | Replace the password and revoke sessions |
| GET | `/me` | Return the authenticated account identity |

## 3. Credential model

### Passwords

Passwords are hashed using Argon2id through the configured password service.

Raw passwords are never stored. Password hashes are stored only in
`user_credentials`.

The configured password length boundary is enforced before hashing.

### Access tokens

Access tokens are signed JWT bearer credentials.

They contain typed identifiers for:

- the user;
- the refresh session;
- the token;
- issuance;
- activation;
- expiry.

The implementation validates the signature, issuer, audience, type, required
claims, timestamps and UUID identifiers.

An access token is accepted only when its PostgreSQL user and refresh session
remain active.

### Refresh tokens

Refresh tokens are high-entropy opaque values.

Only SHA-256 digests are stored. The raw token is returned only through an
HTTP-only refresh cookie.

Each successful refresh:

1. locks the current token and session;
2. consumes the current token;
3. creates a replacement token;
4. issues a new access token;
5. returns the replacement refresh cookie.

Reuse of a consumed refresh token revokes the affected session family.

### Authentication challenges

Email verification and password recovery use expiring, single-use opaque
challenges.

Only token digests are stored. A challenge can be consumed or invalidated,
but not both.

Creating a replacement challenge invalidates the previous active challenge
for the same user and purpose.

## 4. Delivery protection

Authentication delivery messages are persisted in the durable delivery
outbox.

Email addresses and raw verification or reset tokens are encrypted using the
configured Fernet delivery key before persistence.

The current phase provides encrypted outbox creation and validation. An
external email provider and background delivery worker are not implemented
in Phase 3.

## 5. Browser security

The refresh credential uses a cookie with:

- `HttpOnly`;
- `SameSite=Lax`;
- the narrow `/api/v1/auth` path;
- a bounded lifetime;
- `Secure` outside development.

Refresh, logout and password-reset confirmation reject explicitly untrusted
browser origins.

Credentialed CORS is limited to the configured exact trusted origins.

Raw refresh tokens are not accepted in JSON request bodies.

## 6. Enumeration resistance

Password-reset requests and eligible verification-message requests return
generic accepted responses.

The public response does not reveal whether an email address exists.

Invalid login states share the `invalid_credentials` failure.

Invalid bearer states share the `invalid_access_token` failure.

Invalid refresh states share the `invalid_refresh_session` failure.

Invalid reset challenges share the `invalid_password_reset_token` failure.

## 7. Session revocation

Refresh sessions are revoked when:

- the user logs out;
- refresh-token replay is detected;
- the password is reset.

An otherwise unexpired access token is rejected after its persisted refresh
session has been revoked.

## 8. Required configuration

The following environment variables control authentication:

- `FALCON_AUTH_SIGNING_SECRET`;
- `FALCON_AUTH_ACCESS_TOKEN_ALGORITHM`;
- `FALCON_AUTH_ACCESS_TOKEN_ISSUER`;
- `FALCON_AUTH_ACCESS_TOKEN_AUDIENCE`;
- `FALCON_AUTH_ACCESS_TOKEN_LIFETIME_MINUTES`;
- `FALCON_AUTH_REFRESH_TOKEN_LIFETIME_DAYS`;
- `FALCON_AUTH_EMAIL_VERIFICATION_LIFETIME_MINUTES`;
- `FALCON_AUTH_PASSWORD_RESET_LIFETIME_MINUTES`;
- `FALCON_AUTH_OPAQUE_TOKEN_BYTES`;
- `FALCON_AUTH_DELIVERY_ENCRYPTION_KEY`;
- `FALCON_AUTH_DELIVERY_ENCRYPTION_KEY_ID`;
- `FALCON_AUTH_PASSWORD_MIN_LENGTH`;
- `FALCON_AUTH_PASSWORD_MAX_LENGTH`.

Production must use independently generated signing and delivery keys.

Secrets must remain outside Git.

## 9. Persistence

Authentication uses these PostgreSQL structures:

- `users`;
- `user_credentials`;
- `refresh_sessions`;
- `refresh_tokens`;
- `authentication_challenges`;
- `authentication_delivery_outbox`.

The schema includes indexes for active user sessions, session families,
expiry cleanup, active challenges, pending delivery work and active refresh
tokens.

Partitioning is not used because current authentication-table volume does
not justify its operational cost. Indexed lookups match the current access
patterns.

## 10. Validation

The backend test suite validates:

- cryptographic primitives;
- configuration safety;
- persistence constraints;
- registration and verification;
- login and initial session issuance;
- refresh rotation and replay revocation;
- logout;
- password recovery;
- current-principal resolution;
- API and OpenAPI contracts;
- CORS and trusted-origin behavior;
- real PostgreSQL lifecycle behavior.

GitHub Actions runs the complete unit suite and all PostgreSQL integration
tests for backend changes.

## 11. Deferred controls

The following controls are deliberately not implemented in Phase 3:

- distributed rate limiting and abuse throttling;
- external email provider integration;
- background delivery workers;
- OAuth;
- MFA;
- role-based authorization;
- security-event analytics and alerting.

Distributed rate limiting requires shared infrastructure such as Redis.
Adding a process-local limiter would provide inconsistent protection across
multiple API instances and is therefore intentionally avoided.

These deferred controls must be reviewed before public production launch.

## 12. Completion boundary

Phase 3 is complete when this document and the consolidated security
contracts are merged into `develop`.

Later phases may depend on:

- a verified current principal;
- UUID user and session identifiers;
- transactional database sessions;
- uniform authentication errors;
- revocable refresh sessions;
- non-sensitive `/auth/me` identity data.

Later financial modules must never accept a user identifier supplied by the
client when the authenticated principal already provides that identity.
