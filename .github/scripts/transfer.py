#!/usr/bin/env python3
"""
transfer.py — trigger retrieval of an update set from dev to test.

Calls the ServiceNow CI/CD Update Set Retrieve API on the test instance.
Test pulls the update set directly from dev using credentials stored in
a pre-configured Remote Update Source (sys_update_set_source) record.

One-time setup required:
  On test: System Update Sets → Update Sources → New
    - Fill in dev instance URL and credentials
    - Note the record's sys_id
    - Add as GitHub secret SN_DEV_UPDATE_SOURCE_ID

Required env vars:
  SN_TEST_INSTANCE, SN_TEST_USER, SN_TEST_PASS
  SN_DEV_UPDATE_SOURCE_ID  — sys_id of sys_update_set_source record on test
  SYS_ID    — sys_id of the local update set on dev
  SET_NAME  — update set name (for log messages and result lookup)

Writes to $GITHUB_OUTPUT:
  remote_sys_id — sys_id of the created sys_remote_update_set on test
"""
import os
import sys
import time
import urllib.parse

from sn import ServiceNowClient, gha_output

SYS_ID           = os.environ['SYS_ID']
SET_NAME         = os.environ['SET_NAME']
UPDATE_SOURCE_ID = os.environ['SN_DEV_UPDATE_SOURCE_ID']

test = ServiceNowClient.from_env('SN_TEST')

# ---------------------------------------------------------------------------
# 1. Trigger retrieval via the CI/CD Update Set API
# ---------------------------------------------------------------------------
print(f"Triggering retrieval of '{SET_NAME}' (sys_id: {SYS_ID})...")
result = test.post_json(
    f'/api/sn_cicd/update_set/retrieve'
    f'?update_set_id={SYS_ID}'
    f'&update_source_id={UPDATE_SOURCE_ID}',
    {},
)

try:
    progress_id  = result['result']['links']['progress']['id']
    progress_url = result['result']['links']['progress']['url']
except (KeyError, TypeError):
    print(f'::error::Unexpected retrieve response: {result}')
    sys.exit(1)

print(f'Retrieve triggered. Progress: {progress_url}')

# ---------------------------------------------------------------------------
# 2. Poll progress until complete
# Status: 0=Pending, 1=Running, 2=Successful, 3=Failed, 4=Cancelled
# ---------------------------------------------------------------------------
MAX_WAIT = 300
INTERVAL = 10
elapsed  = 0

while True:
    prog   = test.get_json(f'/api/sn_cicd/progress/{progress_id}').get('result', {})
    status = int(prog.get('status', 0))
    pct    = prog.get('percent_complete', 0)
    label  = prog.get('status_label', '')
    print(f'  {pct}% — {label}')

    if status == 2:
        print('Retrieval completed successfully.')
        break
    if status >= 3:
        detail = prog.get('status_detail') or prog.get('error') or prog.get('status_message', '')
        print(f'::error::Retrieval failed ({label}): {detail}')
        sys.exit(1)

    if elapsed >= MAX_WAIT:
        print(f'::error::Retrieval timed out after {MAX_WAIT}s.')
        sys.exit(1)

    time.sleep(INTERVAL)
    elapsed += INTERVAL

# ---------------------------------------------------------------------------
# 3. Locate the created sys_remote_update_set record on test
# ---------------------------------------------------------------------------
encoded_name = urllib.parse.quote(SET_NAME)
results = test.get_json(
    f'/api/now/table/sys_remote_update_set'
    f'?sysparm_query=name%3D{encoded_name}'
    f'&sysparm_fields=sys_id,name,state'
    f'&sysparm_orderbydesc=sys_created_on'
    f'&sysparm_limit=1'
).get('result', [])

if not results:
    print(f'::error::sys_remote_update_set not found for "{SET_NAME}" after retrieval.')
    sys.exit(1)

remote_sys_id = results[0]['sys_id']
print(f'Remote update set on test: {remote_sys_id} (state: {results[0]["state"]})')
gha_output('remote_sys_id', remote_sys_id)
