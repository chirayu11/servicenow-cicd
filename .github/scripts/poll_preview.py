#!/usr/bin/env python3
"""
poll_preview.py — trigger preview and poll until complete, then check for collisions.

Triggers the collision-detection preview on the test instance (if not already
in previewed state), then polls until the state reaches 'previewed'. On
completion, checks sys_update_preview_problem for conflicts.

If the set is already in 'previewed' state the trigger is skipped and the
poll exits immediately on the first check.

Required env vars:
  SN_INSTANCE    — test instance subdomain
  SN_USER        — test admin username
  SN_PASS        — test admin password
  REMOTE_SYS_ID  — sys_id of the sys_remote_update_set record on test
  SET_NAME       — update set name (for error messages)
"""
import os
import sys
import time

import requests

from sn import ServiceNowClient

REMOTE_SYS_ID = os.environ['REMOTE_SYS_ID']
SET_NAME      = os.environ['SET_NAME']

TIMEOUT  = 300
INTERVAL = 10

client = ServiceNowClient.from_env()

# ---------------------------------------------------------------------------
# Trigger preview if not already in previewed state
# ---------------------------------------------------------------------------
state = client.get_json(
    f'/api/now/table/sys_remote_update_set/{REMOTE_SYS_ID}'
    f'?sysparm_fields=state'
)['result']['state']

if state == 'previewed':
    print('Set is already in previewed state — skipping trigger.')
else:
    try:
        client.post(f'/sys_remote_update_set_preview.do?sysparm_sys_id={REMOTE_SYS_ID}')
    except requests.exceptions.HTTPError as e:
        print(
            f'::warning::Preview trigger returned HTTP {e.response.status_code}. '
            'The poll below will confirm whether preview started.'
        )
    print(f'Preview triggered for {REMOTE_SYS_ID}')

# ---------------------------------------------------------------------------
# Poll until state = 'previewed'
# ---------------------------------------------------------------------------
print(f'Polling preview state (max {TIMEOUT}s, every {INTERVAL}s)...')
elapsed = 0

while True:
    state = client.get_json(
        f'/api/now/table/sys_remote_update_set/{REMOTE_SYS_ID}'
        f'?sysparm_fields=state'
    )['result']['state']
    print(f'[{elapsed}s] Preview state: {state}')

    if state == 'previewed':
        print('Preview completed.')
        break
    if state == 'error':
        print(
            f"::error::Preview ended in error state for '{SET_NAME}'. "
            f"Open test → Retrieved Update Sets → '{SET_NAME}' to investigate."
        )
        sys.exit(1)

    if elapsed >= TIMEOUT:
        print(f'::error::Preview timed out after {TIMEOUT}s. Last state: {state}')
        sys.exit(1)

    time.sleep(INTERVAL)
    elapsed += INTERVAL

# ---------------------------------------------------------------------------
# Check for collision-type preview problems
# ---------------------------------------------------------------------------
collisions = client.get_json(
    f'/api/now/table/sys_update_preview_problem'
    f'?sysparm_query=remote_update_set%3D{REMOTE_SYS_ID}%5Etype%3Dconflict'
    f'&sysparm_fields=sys_id,type,description'
    f'&sysparm_limit=50'
).get('result', [])

if collisions:
    print(
        f"::error::Preview completed but found {len(collisions)} collision(s) for '{SET_NAME}'. "
        "Resolve these manually in test before retrying."
    )
    for r in collisions:
        print(f"  COLLISION: {r.get('description', '(no description)')}")
    sys.exit(1)

print('No collisions detected. Safe to commit.')
