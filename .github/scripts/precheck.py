#!/usr/bin/env python3
"""
precheck.py — query test for the current state of a named update set.

Called at the start of each deploy matrix job. Queries the test instance live
rather than trusting the discover-time snapshot, because the approval gate can
take minutes or hours during which someone may manually deploy a set.

Required env vars:
  SN_INSTANCE   — test instance subdomain
  SN_USER       — test admin username
  SN_PASS       — test admin password
  SET_NAME      — exact update set name (as it appears in dev)

Writes to $GITHUB_OUTPUT:
  action         — deploy | resume_loaded | resume_previewed | skip
  remote_sys_id  — sys_id on test (empty string when action=deploy)
"""
import os
import sys
import urllib.parse

from sn import ServiceNowClient, gha_output

SET_NAME = os.environ['SET_NAME']

client = ServiceNowClient.from_env()

encoded_name = urllib.parse.quote(SET_NAME)
data = client.get_json(
    f'/api/now/table/sys_remote_update_set'
    f'?sysparm_query=name%3D{encoded_name}'
    f'&sysparm_fields=sys_id,name,state'
    f'&sysparm_orderby=sys_created_on'
    f'&sysparm_limit=10'
)
results = data.get('result', [])

action = 'deploy'
remote_sys_id = ''

if not results:
    print(f"Set '{SET_NAME}' not found on test. Proceeding with full deployment.")
else:
    # Use the most recently created record (last in oldest-first order)
    latest = results[-1]
    state  = latest['state']
    sys_id = latest['sys_id']

    if state == 'committed':
        action = 'skip'
        remote_sys_id = sys_id
        print(f"::notice::Set '{SET_NAME}' is already committed on test. Skipping.")
    elif state == 'previewed':
        action = 'resume_previewed'
        remote_sys_id = sys_id
        print(
            f"::notice::Set '{SET_NAME}' is previewed on test "
            f"(sys_id: {sys_id}). Resuming from commit step."
        )
    elif state == 'loaded':
        action = 'resume_loaded'
        remote_sys_id = sys_id
        print(
            f"::notice::Set '{SET_NAME}' is loaded on test "
            f"(sys_id: {sys_id}). Resuming from preview step."
        )
    else:
        print(
            f"::warning::Set '{SET_NAME}' exists on test in unexpected state '{state}'. "
            f"Falling back to full deployment."
        )

gha_output('action', action)
gha_output('remote_sys_id', remote_sys_id)
