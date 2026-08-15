# ADR 0003: Authentication and Account-Security Contract

- Status: Accepted
- Date: 2026-08-15
- Decision owners: FALCON development team
- Related issue: #32
- Supersedes: None
- Superseded by: None

## Context

FALCON stores private financial records and produces advice that can affect a
person's financial decisions. Authentication therefore protects substantially
more sensitive data than an ordinary profile application.

Phase 2 established the `users` table as the ownership root for all private
domain data. It intentionally did not add passwords, sessions, verification
tokens, or password-reset tokens. Phase 3 must introduce those capabilities
without mixing short-lived authentication state into the financial domain
model.

The first release requires email and password authentication, forgot-password,
and email verification. Google authentication remains optional and must not
delay the secure core flow.

This record fixes the trust boundaries, persistent state, token lifecycle, API
surface, public failure semantics, and security invariants before
implementation begins.

## Decision drivers

The contract prioritizes:

- protection of private financial information
- complete account and session revocation
- resistance to credential stuffing and user enumeration
- bounded damage if the database is disclosed
- short-lived bearer credentials
- safe browser behaviour
- deterministic, testable API semantics
- compatibility with the existing asynchronous FastAPI and PostgreSQL stack
- maintainable implementation for a four-person team
- incremental delivery without premature OAuth complexity

## Decision

### 1. Authentication boundary

Authentication is a dedicated backend capability inside the existing layered
modular monolith.

The capability owns:

- password credentials
- login verification
- email-verification challenges
- password-reset challenges
- refresh sessions
- access-token creation and validation
- current-user resolution
- authentication audit events

The existing `users` row remains the domain ownership root. Authentication
records reference `users.id`; financial records never reference credentials
or sessions.

Routes perform transport validation only. Services own authentication policy
and transaction boundaries. Repositories own persistence queries.
Cryptographic operations are isolated behind explicit interfaces so algorithms
can be upgraded without changing route contracts.

### 2. Email identity

Email addresses are normalized before lookup or storage by trimming surrounding
ASCII whitespace and applying Unicode-aware lowercase normalization.

The database remains authoritative for uniqueness. Registration must handle a
unique-constraint race and return the same public conflict response as a
pre-existing address.

The MVP supports exactly one email identity per user. Changing the primary
email is deferred until a separate re-verification contract is approved.

Email values are personally identifiable information. They may appear in
authorized account responses but must not appear in access logs, exception
messages, metric labels, or token claims.

### 3. Password storage and policy

Plaintext passwords are accepted only over TLS outside local development and
exist only for the duration of the request.

Passwords are hashed with Argon2id using the maintained Python password-hashing
library selected during implementation. The stored encoded hash includes its
algorithm and work parameters. Parameters are configuration owned by the
backend and must have production-safe minimums.

A successful login transparently rehashes a password when stored parameters are
obsolete.

The initial password policy is:

- 12 to 128 Unicode characters
- no composition rules requiring arbitrary mixtures of character classes
- no trimming or silent modification
- rejection of known-compromised passwords when a local or privacy-preserving
  check is introduced

The API accepts the password once. Confirmation fields are a client concern.
Passwords, hashes, and strength-check details are never logged or returned.

### 4. Account states

The existing `UserStatus` values remain `active` and `disabled`.

A disabled user cannot register a replacement account with the same email,
login, refresh a session, verify an email, reset a password, or access a
protected financial route. Disabling a user revokes every active refresh
session.

Email verification is an independent timestamp, not a user status enum value.

An active but unverified user may:

- log in
- log out
- inspect the minimal current-user identity response
- request a new verification message
- submit a verification challenge

All other private application capabilities require an active, verified user.

### 5. Browser token model

FALCON uses two credentials:

1. a short-lived signed JWT access token; and
2. a long-lived opaque refresh token bound to a server-side session.

The access token is returned in the response body and held in browser memory.
It is sent as `Authorization: Bearer <token>`. It must not be stored in local
storage or session storage by the official frontend.

The refresh token is a cryptographically random value with at least 256 bits of
entropy. It is set only as a cookie with:

- `HttpOnly`
- `Secure` outside local development
- `SameSite=Lax`
- a narrow authentication path
- a bounded `Max-Age`

The raw refresh token is never persisted. PostgreSQL stores a deterministic
cryptographic hash suitable for exact lookup. Database disclosure must not
yield a usable refresh credential.

Credentialed CORS is enabled only for exact configured frontend origins.
Cookie-mutating requests additionally validate the `Origin` header when it is
present. Wildcard origins remain forbidden.

### 6. Access-token contract

The initial access-token lifetime is 15 minutes.

Each access token contains only:

- issuer
- audience
- subject equal to the user UUID
- session identifier
- token identifier
- issued-at time
- not-before time
- expiry time
- explicit access-token type

It contains no email address, display name, roles, financial data, or secrets.

The API verifies the signature, fixed algorithm, issuer, audience, token type,
required claims, and timestamps. Algorithm selection is never accepted from
untrusted token input.

Access tokens are stateless during their short lifetime. Logout immediately
prevents refresh but does not maintain a per-request access-token denylist.
High-risk operations may require a valid server-side session in a later,
explicit contract.

Signing secrets are loaded through typed secret configuration, never committed,
never exposed through settings representations, and must be independently
rotatable. Production rejects placeholder or insufficient secrets at startup.

### 7. Refresh-session lifecycle

The initial refresh-session lifetime is seven days.

A successful login creates one session containing at least:

- session UUID and user UUID
- current refresh-token hash
- creation, last-used, and expiry timestamps
- revocation timestamp and reason when revoked
- token-family identifier or equivalent rotation state
- bounded device metadata only if it is demonstrated to be useful and safe

Every successful refresh rotates the opaque token in the same database
transaction. The previous hash becomes unusable.

Presentation of an already-rotated refresh token is treated as possible token
reuse and revokes the entire token family. Concurrent refresh attempts produce
at most one success.

Logout revokes the presented session and clears the refresh cookie. A
logout-all operation is deferred, but the persistence design must permit all
sessions for a user to be revoked.

Password reset and user disablement revoke all refresh sessions for that user.
Expired and revoked sessions are never accepted and may be removed by a
separate retention job.

### 8. Email verification

Registration creates an unverified active user and requests a verification
challenge in the same application operation. Message delivery occurs through
an adapter and must not keep a database transaction open during network I/O.

A verification token:

- has at least 256 bits of cryptographic entropy
- is delivered only to the account email address
- is stored only as a hash
- expires after a configured bounded interval
- is single-use
- is invalidated when a newer verification challenge is issued
- cannot be accepted for a disabled user

Successful verification records `email_verified_at` and consumes the
challenge atomically. Replaying the same challenge fails safely.

Verification resend always returns the same public accepted response,
regardless of whether the email exists, is already verified, or belongs to a
disabled user. Internal behaviour may differ without revealing it to the
caller.

Tokens are transported in request bodies rather than URL query strings where
the official frontend can do so, reducing leakage through history, referrers,
and access logs.

### 9. Forgot-password and reset-password

The forgot-password endpoint always returns the same accepted response for
well-formed email input. Response content and normal response timing must not
confirm whether an account exists.

A reset token follows the same entropy, hashed-storage, expiry, single-use, and
no-logging rules as a verification token. Issuing a new reset challenge
invalidates older unused challenges for that user.

A successful reset:

- validates the challenge and new password
- replaces the password hash
- consumes the challenge atomically
- revokes every refresh session belonging to the user
- does not automatically log the user in

Resetting a disabled account is forbidden internally while retaining
enumeration-safe request behaviour.

### 10. API surface

The Phase 3 API is versioned under `/api/v1/auth`.

| Method | Path | Success | Purpose |
| --- | --- | --- | --- |
| `POST` | `/register` | `201` | Create an email/password account |
| `POST` | `/login` | `200` | Authenticate and create a refresh session |
| `POST` | `/refresh` | `200` | Rotate the refresh token and issue access |
| `POST` | `/logout` | `204` | Revoke the current refresh session |
| `GET` | `/me` | `200` | Return the minimal authenticated identity |
| `POST` | `/email-verification/request` | `202` | Request a verification message |
| `POST` | `/email-verification/confirm` | `204` | Consume a verification challenge |
| `POST` | `/password-reset/request` | `202` | Request a password-reset message |
| `POST` | `/password-reset/confirm` | `204` | Consume a reset challenge and set password |

Login returns an access token and its expiry metadata while setting the refresh
cookie. Refresh does the same and rotates the cookie. Refresh credentials are
never returned in JSON.

Registration returns only the minimal new-user identity and verification state.
It does not automatically create a refresh session.

### 11. Public failure semantics

All failures use the existing unified API error envelope and request ID.

Stable authentication error codes include:

- `email_already_registered` for registration conflict
- `invalid_credentials` for every login credential mismatch
- `authentication_required` for a missing access credential
- `invalid_access_token` for malformed, invalid, or expired access tokens
- `invalid_refresh_session` for refresh failures
- `email_verification_required` for verified-only capability access
- `invalid_verification_token` for invalid, expired, or consumed challenges
- `invalid_password_reset_token` for invalid, expired, or consumed challenges
- `user_disabled` only after valid authentication has identified the account
- `rate_limit_exceeded` for enforced request limits

Login never reveals whether the email, password, account state, or verification
state caused `invalid_credentials`.

Verification-request and password-reset-request endpoints use a generic
accepted message and do not expose account existence through status codes.

### 12. Rate limiting and abuse controls

Rate-limit policy is enforced at a replaceable boundary and keyed using a
privacy-conscious combination of route, network source, and normalized account
identifier hash where appropriate.

At minimum, limits apply to:

- registration
- login
- refresh
- verification resend
- forgot-password
- reset confirmation

Limits are configurable, bounded, and tested. Raw email addresses and tokens
must not become rate-limit keys visible in logs or metrics.

Repeated failed authentication attempts generate safe audit events. The first
release does not implement permanent account lockout because it enables denial
of service against known addresses. Progressive delay or temporary controls may
be introduced behind the same boundary.

### 13. Logging, auditing, and observability

The existing body-free structured request logger remains authoritative.

The following values must never be logged:

- passwords or password hashes
- access, refresh, verification, or reset tokens
- cookies or authorization headers
- request or response bodies
- raw email addresses in authentication audit events

Security audit events contain bounded identifiers and outcomes, such as user
UUID when known, session UUID when safe, event type, request ID, and timestamp.
They contain no secrets and no raw credential material.

Metrics use low-cardinality outcome labels and never use user, session, email,
IP address, or token values as labels.

### 14. Transaction and delivery rules

User, credential, challenge, and session mutations follow ADR 0002 transaction
boundaries and database integrity rules.

Challenge creation and the corresponding durable message-delivery request are
made consistent through an outbox-style boundary or an equivalently testable
design. External email delivery never occurs while holding a database
transaction open.

Cryptographic token generation occurs before persistence. Only its hash crosses
the repository boundary.

Time is supplied through an injectable UTC clock for deterministic expiry and
rotation tests.

### 15. Authorization dependency layers

Phase 3 provides separate dependencies for:

- optional authentication
- active authenticated user
- active and email-verified authenticated user

A UUID from a token is an identifier, not proof of ownership. Later financial
routes must filter or constrain every private query by the authenticated
`user_id`, consistent with ADR 0002.

Authentication failures return `401` with an appropriate bearer challenge.
A valid but insufficient account state returns `403`.

### 16. Testing requirements

Each implementation checkpoint includes unit tests and, where persistence is
involved, real PostgreSQL integration tests.

The completed Phase 3 suite must cover at least:

- password hash and verification behaviour
- rehash-on-login
- normalized email uniqueness and concurrent registration
- successful and failed login without enumeration
- JWT claim and validation failures
- refresh rotation, replay detection, expiry, and concurrent use
- logout and session revocation
- disabled and unverified account behaviour
- verification issue, replacement, expiry, single use, and replay
- reset issue, replacement, expiry, single use, and session revocation
- generic request responses for unknown accounts
- cookie flags, trusted-origin handling, and CORS configuration
- secret redaction and log-safety assertions
- migration upgrade and downgrade

The backend's existing 90% statement and branch coverage gate remains in force.
Coverage does not replace security-case assertions.

## Alternatives considered

### Stateful opaque access tokens

Rejected for the initial release because every ordinary authenticated request
would require a session lookup. Short-lived signed access tokens plus
server-side refresh sessions provide bounded revocation delay with simpler
request handling.

### Refresh JWTs

Rejected because opaque refresh tokens are easier to revoke, rotate, hash at
rest, and detect for reuse without treating long-lived bearer data as
self-contained authority.

### Refresh tokens in browser storage

Rejected because script-readable long-lived credentials substantially increase
the impact of cross-site scripting.

### Password composition rules

Rejected because arbitrary uppercase, number, and symbol rules harm usability
without reliably producing stronger passwords. Length, modern hashing,
rate-limiting, and compromised-password screening provide clearer value.

### Permanent lockout after failed login

Rejected because an attacker could lock a known user's financial account.
Configurable throttling and security auditing are used instead.

### Google OAuth in the core checkpoint path

Deferred until email/password authentication reaches its complete security and
test contract. OAuth may later create or link an authentication identity, but
it must not bypass verified ownership, session, audit, or account-state rules.

## Consequences

### Positive

- Financial ownership remains separated from credential state.
- Database disclosure does not directly expose plaintext refresh or challenge
  tokens.
- Access credentials are short-lived and contain minimal personal data.
- Password reset and disablement have deterministic session-revocation effects.
- Browser handling avoids long-lived tokens in script-readable storage.
- Route contracts are stable enough for frontend and backend work to proceed
  independently.
- Google OAuth can be added later without weakening the core session model.

### Negative

- Refresh rotation and replay detection add persistence and concurrency
  complexity.
- Cookie-based refresh requires exact CORS and origin configuration.
- Stateless access tokens remain usable until their short expiry after logout.
- Reliable challenge delivery requires an outbox or equivalent durable boundary.
- Strong security-case testing adds work beyond simple happy-path endpoints.

## Deferred decisions

The following are explicitly outside the Phase 3 core:

- Google OAuth and account linking
- multi-factor authentication
- passkeys
- primary-email change
- logout-all and user-facing session management endpoints
- breach-password provider selection
- signing-key publication or asymmetric key rotation
- privileged administrator roles
- risk-based authentication
- high-risk-operation step-up authentication

Each deferred capability requires its own threat analysis before implementation.
