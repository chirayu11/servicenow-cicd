#!/usr/bin/env python3
"""
export.py — export an update set as XML from the dev instance.

Required env vars:
  SN_INSTANCE   — dev instance subdomain
  SN_USER       — dev admin username
  SN_PASS       — dev admin password
  SYS_ID        — sys_id of the local update set on dev
  SET_NAME      — update set name (for log messages)

Writes to $GITHUB_OUTPUT:
  export_file   — absolute path to the downloaded XML file
"""
import os
import sys
import xml.etree.ElementTree as ET

from sn import ServiceNowClient, gha_output

SYS_ID   = os.environ['SYS_ID']
SET_NAME = os.environ['SET_NAME']

EXPORT_FILE = f'/tmp/update_set_{SYS_ID}.xml'

print(f"Exporting: '{SET_NAME}' (sys_id: {SYS_ID})")

client = ServiceNowClient.from_env()

# Verify the update set exists and is complete.
# This Table API call also primes the requests.Session cookie so the
# subsequent legacy .do export endpoint receives a valid server-side session
# (the .do processor requires session-based auth; Basic Auth alone is not enough).
us = client.get_json(
    f'/api/now/table/sys_update_set/{SYS_ID}'
    f'?sysparm_fields=sys_id,name,state'
).get('result', {})

if not us:
    print(f'::error::Update set {SYS_ID} not found on dev.')
    sys.exit(1)
if us.get('state') != 'complete':
    print(
        f"::warning::Update set state is '{us.get('state')}', expected 'complete'. "
        'Proceeding anyway.'
    )

content = client.get_raw(
    f'/sys_update_set_export_xml.do?sysparm_sys_id={SYS_ID}'
)

with open(EXPORT_FILE, 'wb') as f:
    f.write(content)

# Guard against HTML error pages served with HTTP 200.
# ServiceNow returns these when the session is invalid or the instance is hibernating.
try:
    ET.parse(EXPORT_FILE)
except ET.ParseError as e:
    print(f'::error::Response is not valid XML: {e}')
    print('First 300 bytes:', content[:300])
    print('Log in to dev in a browser to wake the instance, then retry.')
    sys.exit(1)

print(f'Exported {len(content):,} bytes of XML to {EXPORT_FILE}')
gha_output('export_file', EXPORT_FILE)
