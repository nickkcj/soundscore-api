# Community safety: release and operation

Prepared on 2026-10-03. Nothing in this document is evidence of deployment.

## Implementation

- `n4o5p6q7r8s9` adds reports, bilateral blocks and versioned terms acceptance.
- Native app requires authenticated terms acceptance before entering protected screens, including social OAuth accounts and existing users.
- API protects review/comment/group/message publication with the same terms version.
- Blocking removes follows, hides reviews/comments/messages for the authenticated viewer, prevents direct messaging/sharing/following and private group invites, invalidates feed caches, and restricts Supabase realtime visibility.
- Reports validate content existence and access; private messages require conversation participation and private groups require membership. Duplicate reports are idempotent; submission is limited to 30 stored reports per UTC day.
- Only active superusers can list or resolve reports. Removal deletes the original content; suspension disables the author's account. Each resolution records actor, time and reason. Snapshots retain evidence when content is deleted; reporter identity is not exposed to the reported user.

## Required deployment sequence

1. Publish the web terms gate and public `/terms` and `/delete-account` pages together with the API rollout. Existing web/mobile clients that have not accepted terms will otherwise receive 403 when publishing. Keep this compatibility requirement visible; do not deploy only the API gates.
2. Confirm the intended account for the moderator role; the production read-only audit found **zero active superusers** among 18 accounts.
3. Run `alembic upgrade head` with production credentials before the Lambda update. The existing deploy workflow needs this migration step (added in this change).
4. Deploy the backend via the existing AWS pipeline. Verify health, new OpenAPI routes, report permissions and terms with a disposable test account.
5. Install native build 1.0.4 through Play internal testing and test OAuth, push, content, moderation and account deletion on the Play-signed artifact. A local debug install is not this release check.
6. Update Play declarations and store listing only after verifying their factual answers and public URLs. Promote to production only after QA and production eligibility pass.

## Moderator operation

Use an authenticated superuser's normal bearer token. Do not put it in source files or command history.

- `GET /api/v1/moderation/reports?status=pending&limit=50` returns the oldest pending reports.
- `POST /api/v1/moderation/reports/{id}/resolve` accepts `{ "action": "dismiss" | "remove" | "suspend", "note": "reason for the decision" }`.
- Review the queue daily; prioritize threats, privacy exposure and child safety. Do not download or redistribute suspected illegal imagery. Removal/suspension must follow an actual review.
- Appeals and child-safety contact use the existing `contact@soundscore.com.br`. Confirm that this mailbox is operational and monitored before declaring the process in Play Console.
- Child safety reports confirmed as CSAM must follow applicable reporting obligations. This is an operational responsibility; API endpoints alone do not perform authority reporting.

## Verification

- Backend: 69 pytest checks passed (60 existing + 9 safety checks).
- Disposable PostgreSQL on local port 55439: actual migration upgrade/downgrade/upgrade passed; API smoke covered terms, duplicate reports, moderator permissions, bilateral messaging blocks, feed visibility, content removal and account deletion.
- Run the smoke only with `DATABASE_URL=postgresql+asyncpg://postgres:local-qa-only@127.0.0.1:55439/soundscore_qa JWT_SECRET_KEY=local-qa-only PYTHONPATH=. .venv/bin/python scripts/verify-community-safety.py`. It refuses another database URL and truncates only this disposable QA database.
