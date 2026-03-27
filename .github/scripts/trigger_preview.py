#!/usr/bin/env python3
"""
trigger_preview.py — start the collision-detection preview on the test instance.

Preview runs asynchronously. This script only triggers it; poll_preview.py
polls until it completes.

Required env vars:
  SN_INSTANCE    — test instance subdomain
  SN_USER        — test admin username
  SN_PASS        — test admin password
  REMOTE_SYS_ID  — sys_id of the sys_remote_update_set record on test
                   (resolved by the workflow as: precheck.remote_sys_id || import_set.remote_sys_id)
"""
import os
import urllib.error

from sn import ServiceNowClient

REMOTE_SYS_ID = os.environ['REMOTE_SYS_ID']

client = ServiceNowClient.from_env()

# The preview processor is a legacy .do endpoint — the same one the
# ServiceNow UI calls when you click the "Preview" button.
try:
    client.post(f'/sys_remote_update_set_preview.do?sysparm_sys_id={REMOTE_SYS_ID}')
except urllib.error.HTTPError as e:
    # Non-fatal: the preview may still have started. poll_preview.py will
    # detect if it did not by watching the state field.
    print(
        f'::warning::Preview trigger returned HTTP {e.code}. '
        'The poll step will confirm whether preview started.'
    )

print(f'Preview triggered for {REMOTE_SYS_ID}')
