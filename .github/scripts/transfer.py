#!/usr/bin/env python3
"""
transfer.py — transfer an update set from dev to test via REST API.

Reads sys_update_xml change records from dev and creates the corresponding
sys_remote_update_set and sys_update_xml records on test directly via the
Table API. No XML file is generated; no legacy .do endpoint is used.

Required env vars:
  SN_DEV_INSTANCE, SN_DEV_USER, SN_DEV_PASS
  SN_TEST_INSTANCE, SN_TEST_USER, SN_TEST_PASS
  SYS_ID    — sys_id of the local update set on dev
  SET_NAME  — update set name (for log messages)

Writes to $GITHUB_OUTPUT:
  remote_sys_id — sys_id of the created sys_remote_update_set on test
"""
import os
import sys

from sn import ServiceNowClient, gha_output

SYS_ID   = os.environ['SYS_ID']
SET_NAME = os.environ['SET_NAME']

dev  = ServiceNowClient.from_env('SN_DEV')
test = ServiceNowClient.from_env('SN_TEST')

# ---------------------------------------------------------------------------
# 1. Fetch update set metadata from dev
# ---------------------------------------------------------------------------
us = dev.get_json(
    f'/api/now/table/sys_update_set/{SYS_ID}'
    f'?sysparm_fields=sys_id,name,description,state'
).get('result', {})

if not us:
    print(f'::error::Update set {SYS_ID} not found on dev.')
    sys.exit(1)

state = us.get('state', '')
if state != 'complete':
    print(f"::warning::Update set state is '{state}', expected 'complete'. Proceeding anyway.")
else:
    print(f"Update set '{us['name']}' state: {state}")

# ---------------------------------------------------------------------------
# 2. Fetch all change records from dev
# ---------------------------------------------------------------------------
print('Fetching change records from dev...')
records = dev.get_json(
    f'/api/now/table/sys_update_xml'
    f'?sysparm_query=update_set={SYS_ID}'
    f'&sysparm_fields=name,type,action,payload'
    f'&sysparm_orderby=sys_created_on'
    f'&sysparm_limit=10000'
).get('result', [])

print(f'Found {len(records)} change record(s) on dev.')
if len(records) == 10000:
    print('::warning::Fetched exactly 10 000 records — update set may exceed the limit.')

# ---------------------------------------------------------------------------
# 3. Create sys_remote_update_set on test
# ---------------------------------------------------------------------------
result = test.post_json('/api/now/table/sys_remote_update_set', {
    'name': us['name'],
    'description': us.get('description', ''),
    'state': 'loaded',
    'origin_sys_id': SYS_ID,
})
remote_sys_id = result['result']['sys_id']
print(f'Created sys_remote_update_set on test: {remote_sys_id}')

# ---------------------------------------------------------------------------
# 4. Create sys_update_xml records on test linked to the remote update set
# ---------------------------------------------------------------------------
for i, r in enumerate(records, 1):
    test.post_json('/api/now/table/sys_update_xml', {
        'name': r.get('name', ''),
        'type': r.get('type', ''),
        'action': r.get('action', 'INSERT_OR_UPDATE'),
        'payload': r.get('payload', ''),
        'remote_update_set': remote_sys_id,
    })
    if i % 50 == 0:
        print(f'  ...{i}/{len(records)} records transferred.')

print(f'Transferred {len(records)} change record(s) to test.')
gha_output('remote_sys_id', remote_sys_id)
