#!/usr/bin/env python3
"""
import_set.py — upload XML to test and locate the resulting remote update set record.

Required env vars:
  SN_INSTANCE   — test instance subdomain
  SN_USER       — test admin username
  SN_PASS       — test admin password
  EXPORT_FILE   — absolute path to the exported XML file
  SET_NAME      — update set name (used to locate the record after upload)

Writes to $GITHUB_OUTPUT:
  remote_sys_id  — sys_id of the newly-created sys_remote_update_set record on test
"""
import os
import sys
import time
import urllib.parse

from sn import ServiceNowClient, gha_output

EXPORT_FILE = os.environ['EXPORT_FILE']
SET_NAME    = os.environ['SET_NAME']

client = ServiceNowClient.from_env()

# Upload the XML file via multipart form POST.
# The upload endpoint is a legacy processor that accepts the same form the
# ServiceNow UI submits when you manually import an update set.
status = client.upload_xml('/sys_update_set_upload.do', EXPORT_FILE)
print(f'Import HTTP status: {status}')

# Allow the server-side processor time to write the sys_remote_update_set record.
# The upload endpoint returns before the background script finishes.
time.sleep(3)

# Locate the newly-created remote update set record by name + state=loaded.
# Descending order ensures the most recently created record comes first,
# which matters if the set was previously imported and left in loaded state.
encoded_name = urllib.parse.quote(SET_NAME)
results = client.get_json(
    f'/api/now/table/sys_remote_update_set'
    f'?sysparm_query=name%3D{encoded_name}%5EstateLOADloaded'
    f'&sysparm_fields=sys_id,name,state'
    f'&sysparm_orderbydesc=sys_created_on'
    f'&sysparm_limit=1'
).get('result', [])

if not results:
    print(
        f"::error::Could not locate the imported sys_remote_update_set record for '{SET_NAME}' on test. "
        "This may mean the upload failed silently or the name does not match exactly."
    )
    sys.exit(1)

remote_sys_id = results[0]['sys_id']
print(f'Found remote update set on test: {remote_sys_id}')
gha_output('remote_sys_id', remote_sys_id)
