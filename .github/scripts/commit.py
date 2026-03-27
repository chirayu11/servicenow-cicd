#!/usr/bin/env python3
"""
commit.py — commit the previewed update set on test, then poll until done.

Replaces the original sleep 5 + single-check pattern with a polling loop
identical to poll_preview.py, so large update sets don't fail due to timing.

Required env vars:
  SN_INSTANCE    — test instance subdomain
  SN_USER        — test admin username
  SN_PASS        — test admin password
  REMOTE_SYS_ID  — sys_id of the sys_remote_update_set record on test
                   (resolved by the workflow as: precheck.remote_sys_id || import_set.remote_sys_id)
  SET_NAME       — update set name (for log messages and step summary)
"""
import os
import sys
import time

import requests

from sn import ServiceNowClient, gha_summary

REMOTE_SYS_ID = os.environ['REMOTE_SYS_ID']
SET_NAME      = os.environ['SET_NAME']

TIMEOUT  = 300
INTERVAL = 10

client = ServiceNowClient.from_env()

# ---------------------------------------------------------------------------
# Trigger the commit
# The commit processor is a legacy .do endpoint — the same one the
# ServiceNow UI calls when you click the "Commit" button.
# ---------------------------------------------------------------------------
try:
    client.post(
        f'/sys_remote_update_set_commit.do?sysparm_sys_id={REMOTE_SYS_ID}&sysparm_ck='
    )
except requests.exceptions.HTTPError as e:
    print(
        f'::warning::Commit trigger returned HTTP {e.response.status_code}. '
        'Polling to check whether the commit proceeded...'
    )

print(f"Commit triggered for '{SET_NAME}' ({REMOTE_SYS_ID}). Polling for completion...")

# ---------------------------------------------------------------------------
# Poll until state = 'committed'
# Commit is asynchronous on large update sets — the .do endpoint returns
# before the background processor finishes writing all changes.
# ---------------------------------------------------------------------------
elapsed = 0

while True:
    data  = client.get_json(
        f'/api/now/table/sys_remote_update_set/{REMOTE_SYS_ID}'
        f'?sysparm_fields=state,name'
    )
    state = data['result']['state']
    print(f'[{elapsed}s] Commit state: {state}')

    if state == 'committed':
        print(f"::notice::Successfully committed '{SET_NAME}' to test.")
        gha_summary(
            f'### Committed: `{SET_NAME}`\n'
            f'- Remote sys_id on test: `{REMOTE_SYS_ID}`\n'
        )
        sys.exit(0)
    elif state == 'error':
        print(
            f"::error::Commit ended in error state for '{SET_NAME}'. "
            "Check test → Retrieved Update Sets for details."
        )
        sys.exit(1)

    if elapsed >= TIMEOUT:
        print(
            f"::error::Commit timed out after {TIMEOUT}s. Last state: '{state}'. "
            "Check test → Retrieved Update Sets manually."
        )
        sys.exit(1)

    time.sleep(INTERVAL)
    elapsed += INTERVAL
