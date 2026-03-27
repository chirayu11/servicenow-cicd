#!/usr/bin/env python3
"""
poll_preview.py — poll until preview completes, then check for collisions.

When action=resume_previewed the set is already in previewed state, so this
script exits immediately on the first poll without sleeping.

Required env vars:
  SN_INSTANCE    — test instance subdomain
  SN_USER        — test admin username
  SN_PASS        — test admin password
  REMOTE_SYS_ID  — sys_id of the sys_remote_update_set record on test
                   (resolved by the workflow as: precheck.remote_sys_id || import_set.remote_sys_id)
  SET_NAME       — update set name (for error messages)
"""
import os
import sys
import time

from sn import ServiceNowClient

REMOTE_SYS_ID = os.environ['REMOTE_SYS_ID']
SET_NAME      = os.environ['SET_NAME']

TIMEOUT  = 300
INTERVAL = 10

client = ServiceNowClient.from_env()

# ---------------------------------------------------------------------------
# Poll until state = 'previewed'
# ---------------------------------------------------------------------------
print(f'Polling preview state (max {TIMEOUT}s, every {INTERVAL}s)...')
elapsed = 0

while True:
    data  = client.get_json(
        f'/api/now/table/sys_remote_update_set/{REMOTE_SYS_ID}'
        f'?sysparm_fields=sys_id,name,state'
    )
    state = data['result']['state']
    print(f'[{elapsed}s] Preview state: {state}')

    if state == 'previewed':
        print('Preview completed.')
        break
    elif state == 'error':
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
problems   = client.get_json(
    f'/api/now/table/sys_update_preview_problem'
    f'?sysparm_query=remote_update_set%3D{REMOTE_SYS_ID}%5Etype%3Dconflict'
    f'&sysparm_fields=sys_id,type,description'
    f'&sysparm_limit=50'
)
collisions = problems.get('result', [])

if collisions:
    print(
        f"::error::Preview completed but found {len(collisions)} collision(s) for '{SET_NAME}'. "
        "Resolve these manually in test before retrying."
    )
    for r in collisions:
        print(f"  COLLISION: {r.get('description', '(no description)')}")
    sys.exit(1)

print('No collisions detected. Safe to commit.')
