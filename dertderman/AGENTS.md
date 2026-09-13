# DertDerman Codex Guidance

## Project

DertDerman is a Django-based complaint platform.

Django root:
dertderman/

Main apps:

- accounts
- companies
- complaints
- notifications
- payments
- adminx
- core

Custom admin:

- /yonetim/
- Do not introduce or depend on /django-admin/ for product workflows.

## Roles

User roles:

- USER
- COMPANY
- ADMIN

Company membership roles:

- OWNER
- MANAGER
- SUPPORT

Never trust role checks performed only in templates.
Authorization must also be enforced in views/services/selectors.

## Security priorities

For security-sensitive changes always consider:

- IDOR
- direct POST bypass
- form field manipulation
- cross-company access
- privilege escalation
- CSRF
- session security
- race conditions
- stale database objects
- duplicate requests
- notification privacy leaks
- business-logic bypass
- rate-limit bypass
- transaction safety

Prefer fail-closed behavior.

Do not use UI hiding as the only security control.

When modifying protected data, re-check authorization at the backend/service layer.

For concurrent state-changing operations, consider:

- transaction.atomic
- select_for_update
- idempotency

Never add secrets, API keys, passwords or production credentials to source control.

## Company lifecycle

A company application may be:

- PENDING
- APPROVED
- REJECTED

Only an active, non-archived, APPROVED company with an active valid membership may access the company workspace.

Rejected companies may use the dedicated reapplication flow.

Reapplication:

- must verify the existing account
- must reuse the existing User/Company/Membership records
- returns Company to PENDING
- does not grant panel access before admin approval

Do not create duplicate companies/users to implement reapplication.

## Company profile security

For APPROVED companies, identity-sensitive fields are protected from normal company-panel edits.

Protected fields:

- name
- logo
- selected_avatar
- category
- email

Editable operational fields:

- description
- website
- phone

Protected-field restrictions must be enforced in backend code, not only templates/forms.

Admin /yonetim/ may retain controlled ability to correct protected company identity data.

## Plans

Company plans:

STANDARD:

- company account/profile
- complaint viewing
- basic company functionality
- no new public company responses
- no new internal notes

DertDerman Pro:

- public company responses
- internal company notes
- Pro badge/features

Public verified status is independent from Pro status.

Do not infer Pro access from the UI.
Use the existing entitlement helpers/service logic.

If Pro expires:

- historical public responses remain
- historical internal notes remain
- new responses are blocked
- new internal notes are blocked

Do not delete historical content because a subscription expires.

## Complaint lifecycle

Company visibility:

PENDING:

- company must not see it

REJECTED:

- company must not see it

PUBLISHED:

- company may see it
- active Pro company may create response/internal note

RESOLVED:

- company may see history
- read-only
- no new company response/internal note

REMOVED:

- company may see history when policy allows
- read-only
- no new company response/internal note

WITHDRAWN:

- read-only
- no new company response/internal note

Lifecycle rules must be enforced in the service/backend layer.

Do not allow state transitions that contradict the complaint lifecycle.

## Notifications

Do not notify companies about complaints they are not allowed to see.

PENDING or REJECTED complaint data must not leak through:

- notifications
- notification counters
- notification links
- dashboard metrics
- API/view responses

Notification links must not lead to inaccessible or unauthorized records.

Avoid duplicate notification/email creation for repeated identical events.

## Email

Email provider:

- Resend

Never hardcode Resend credentials.

Transactional email operations should preserve:

- delivery logging
- idempotency
- webhook verification
- retry safety

Do not weaken existing webhook verification or delivery reconciliation.

## Payments

Payment implementation is security-critical.

When payment functionality is modified, explicitly check:

- webhook authenticity
- idempotency
- duplicate payment callbacks
- double subscription activation
- fake success redirects
- client-controlled prices
- client-controlled plan names
- race conditions
- cancellation
- expiry
- refund behavior
- failed renewals

Never grant Pro because the browser claims payment succeeded.

Subscription entitlement must be based on trusted server/provider state.

Do not store raw card data.

## Development vs production

Do not break local development merely to satisfy production security checks.

Production hardening should be environment-driven.

Production must eventually use:

- secret environment-based SECRET_KEY
- DEBUG=False
- production ALLOWED_HOSTS
- HTTPS
- secure session cookies
- secure CSRF cookies
- production database
- shared rate-limit/cache backend such as Redis

Do not hardcode production-only values into development settings.

## Change policy

Before editing:

1. inspect the existing implementation
2. inspect relevant tests
3. understand existing business rules

During editing:

- make the smallest safe change
- avoid unrelated refactors
- preserve unrelated local changes
- do not revert user work

Tests must not be changed merely to make new code pass.
Only update a test when the product rule intentionally changed.

## Verification

After relevant Django changes, normally run:

python manage.py check

Run focused tests for the changed area.

Then run:
python manage.py makemigrations --check

If a model change requires a migration:

- create it
- explain why it is required

Do not claim success unless command output confirms it.

Avoid running the entire test suite for every small change unless the change has broad impact.

## Final report

At completion report only:

1. changed files
2. security/business rule implemented
3. migration status
4. tests run and results
5. remaining risks

Keep the report concise.
