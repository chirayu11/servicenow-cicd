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
# ---------------------------------------------------------------------------
test.poll_progress(progress_id, timeout=300, operation='Retrieval')
print('Retrieval completed successfully.')

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
