-- Dev-only cleanup for local data corrupted by the old disconnect behavior.
-- Run manually against a local database; do not wire this into production migrations.
UPDATE instagram_accounts
SET ig_username = regexp_replace(ig_username, '(_disconnected)+$', '')
WHERE ig_username LIKE '%_disconnected%';
