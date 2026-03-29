#!/usr/bin/env python3
"""
commit.py — commit the previewed update set on test via the CI/CD API.

Required env vars:
  SN_INSTANCE    — test instance subdomain
  SN_USER        — test admin username
  SN_PASS        — test admin password
  REMOTE_SYS_ID  — sys_id of the sys_remote_update_set record on test
  SET_NAME       — update set name (for log messages)
"""
import os
import sys
import time

from sn import ServiceNowClient, gha_summary

REMOTE_SYS_ID = os.environ['REMOTE_SYS_ID']
SET_NAME      = os.environ['SET_NAME']

TIMEOUT  = 300
INTERVAL = 10

client = ServiceNowClient.from_env()

# ---------------------------------------------------------------------------
# Trigger commit via the CI/CD Update Set API
# ---------------------------------------------------------------------------
print(f"Triggering commit for '{SET_NAME}' ({REMOTE_SYS_ID})...")
result = client.post_json(f'/api/sn_cicd/update_set/commit/{REMOTE_SYS_ID}', {})

try:
    progress_id  = result['result']['links']['progress']['id']
    progress_url = result['result']['links']['progress']['url']
except (KeyError, TypeError):
    print(f'::error::Unexpected commit response: {result}')
    sys.exit(1)

print(f'Commit triggered. Progress: {progress_url}')

# ---------------------------------------------------------------------------
# Poll progress until committed
# Status: 0=Pending, 1=Running, 2=Successful, 3=Failed, 4=Cancelled
# ---------------------------------------------------------------------------
elapsed = 0

while True:
    prog   = client.get_json(f'/api/sn_cicd/progress/{progress_id}').get('result', {})
    status = int(prog.get('status', 0))
    pct    = prog.get('percent_complete', 0)
    label  = prog.get('status_label', '')
    print(f'[{elapsed}s] {pct}% — {label}')

    if status == 2:
        print(f"::notice::Successfully committed '{SET_NAME}' to test.")
        gha_summary(
            f'### Committed: `{SET_NAME}`\n'
            f'- Remote sys_id on test: `{REMOTE_SYS_ID}`\n'
        )
        sys.exit(0)
    if status >= 3:
        detail = prog.get('status_detail') or prog.get('error') or prog.get('status_message', '')
        print(f"::error::Commit failed ({label}): {detail}")
        sys.exit(1)

    if elapsed >= TIMEOUT:
        print(f"::error::Commit timed out after {TIMEOUT}s.")
        sys.exit(1)

    time.sleep(INTERVAL)
    elapsed += INTERVAL
