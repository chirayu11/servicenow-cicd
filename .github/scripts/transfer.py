#!/usr/bin/env python3
"""
transfer.py — transfer an update set from dev to test.

Builds the update set XML in ServiceNow's standard exchange format by reading
from dev's Table API, then uploads it to test via sys_update_set_upload.do.

The upload uses a form-based login session (not Basic Auth) because
sys_update_set_upload.do is a legacy Jelly processor that requires a proper
web session cookie (glide_session_store) to process the form POST.

Required env vars:
  SN_DEV_INSTANCE, SN_DEV_USER, SN_DEV_PASS
  SN_TEST_INSTANCE, SN_TEST_USER, SN_TEST_PASS
  SYS_ID    — sys_id of the local update set on dev
  SET_NAME  — update set name (for log messages)

Writes to $GITHUB_OUTPUT:
  remote_sys_id — sys_id of the created sys_remote_update_set on test
"""
import html
import io
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone

import requests

from sn import ServiceNowClient, gha_output

SYS_ID   = os.environ['SYS_ID']
SET_NAME = os.environ['SET_NAME']

SN_TEST_INSTANCE = os.environ['SN_TEST_INSTANCE']
SN_TEST_USER     = os.environ['SN_TEST_USER']
SN_TEST_PASS     = os.environ['SN_TEST_PASS']

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
    f'&sysparm_fields=sys_id,name,type,action,payload'
    f'&sysparm_orderby=sys_created_on'
    f'&sysparm_limit=10000'
).get('result', [])

print(f'Found {len(records)} change record(s) on dev.')
if len(records) == 10000:
    print('::warning::Fetched exactly 10 000 records — update set may exceed the limit.')

# ---------------------------------------------------------------------------
# 3. Build XML in ServiceNow update set exchange format
#
#   <unload unload_date="...">
#     <sys_remote_update_set action="INSERT_OR_UPDATE">
#       <sys_id>...</sys_id>       ← dev's sys_update_set.sys_id
#       <name>...</name>
#       <state>loaded</state>
#     </sys_remote_update_set>
#     <sys_update_xml action="INSERT_OR_UPDATE">
#       <sys_id>...</sys_id>       ← dev's sys_update_xml.sys_id
#       <name>...</name>
#       <payload>&lt;record_update...&gt;...&lt;/record_update&gt;</payload>
#       <remote_update_set>SYS_ID</remote_update_set>
#       ...
#     </sys_update_xml>
#     ...
#   </unload>
#
# The payload field stores the change XML as HTML-escaped text — this is
# the format sys_update_set_export_xml.do generates and that the upload
# processor expects. Using html.escape() produces the correct encoding.
# ---------------------------------------------------------------------------
def xe(s: str) -> str:
    return html.escape(str(s or ''), quote=False)

unload_date = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    f'<unload unload_date="{unload_date}">',
    '<sys_remote_update_set action="INSERT_OR_UPDATE">',
    f'<description>{xe(us.get("description", ""))}</description>',
    f'<name>{xe(us["name"])}</name>',
    '<state>loaded</state>',
    f'<sys_id>{xe(SYS_ID)}</sys_id>',
    '</sys_remote_update_set>',
]

for r in records:
    lines += [
        '<sys_update_xml action="INSERT_OR_UPDATE">',
        f'<action>{xe(r.get("action", "INSERT_OR_UPDATE"))}</action>',
        f'<name>{xe(r.get("name", ""))}</name>',
        f'<payload>{xe(r.get("payload", ""))}</payload>',
        f'<remote_update_set>{xe(SYS_ID)}</remote_update_set>',
        f'<sys_id>{xe(r.get("sys_id", ""))}</sys_id>',
        f'<type>{xe(r.get("type", ""))}</type>',
        f'<update_set>{xe(SYS_ID)}</update_set>',
        '</sys_update_xml>',
    ]

lines.append('</unload>')
xml_bytes = '\n'.join(lines).encode('utf-8')
print(f'Built {len(xml_bytes):,} bytes of XML.')

# ---------------------------------------------------------------------------
# 4. Upload XML to test via form login session
#
# A fresh session WITHOUT Basic Auth is used so that ServiceNow processes
# the /login.do form POST and sets the glide_session_store cookie.
# If we kept Basic Auth, ServiceNow might satisfy authentication via the
# header before the form processor runs, and the session cookie is never set.
# ---------------------------------------------------------------------------
test_base = f'https://{SN_TEST_INSTANCE}.service-now.com'
upload_session = requests.Session()   # no auth — credentials go in form body

# Step 4a: form login
login_resp = upload_session.post(
    test_base + '/login.do',
    data={
        'user_name': SN_TEST_USER,
        'user_password': SN_TEST_PASS,
        'sys_action': 'sysverb_login',
        'sysparm_redirect': '/nav_to.do?uri=/',
    },
    allow_redirects=True,
    timeout=60,
)
if 'login.do' in login_resp.url:
    print('::warning::Form login may have failed (still on login page after redirect).')
else:
    print(f'Form login succeeded.')

# Step 4b: extract CSRF token from the upload page
page = upload_session.get(test_base + '/sys_update_set_upload.do', timeout=60)
m = re.search(r"g_ck\s*=\s*['\"]([^'\"]+)['\"]", page.text)
sysparm_ck = m.group(1) if m else ''
if sysparm_ck:
    print(f'Extracted sysparm_ck: {sysparm_ck[:8]}…')
else:
    print('::warning::Could not extract sysparm_ck from upload page — proceeding without CSRF token.')

# Step 4c: POST the XML file
upload_resp = upload_session.post(
    test_base + '/sys_update_set_upload.do',
    data={'sysparm_ck': sysparm_ck},
    files={'attachmentFile': ('update_set.xml', io.BytesIO(xml_bytes), 'application/xml')},
    allow_redirects=True,
    timeout=120,
)
print(f'Upload HTTP status: {upload_resp.status_code}')
print(f'Upload final URL: {upload_resp.url}')
if upload_resp.url.endswith('sys_update_set_upload.do'):
    # Still on the upload form — processor did not accept the request
    print(f'Upload response (first 2000 chars): {upload_resp.text[:2000].replace(chr(10), " ")}')

# ---------------------------------------------------------------------------
# 5. Poll for the sys_remote_update_set record on test
# ---------------------------------------------------------------------------
encoded_name = urllib.parse.quote(SET_NAME)
MAX_WAIT = 30
INTERVAL = 3
elapsed = 0

while True:
    results = test.get_json(
        f'/api/now/table/sys_remote_update_set'
        f'?sysparm_query=name%3D{encoded_name}'
        f'&sysparm_fields=sys_id,name,state'
        f'&sysparm_orderbydesc=sys_created_on'
        f'&sysparm_limit=1'
    ).get('result', [])
    if results:
        break
    if elapsed >= MAX_WAIT:
        print(
            f'::error::Could not locate sys_remote_update_set for "{SET_NAME}" after {MAX_WAIT}s. '
            'The upload may have failed — check the Upload final URL and response above.'
        )
        sys.exit(1)
    print(f'Record not found yet ({elapsed}s elapsed), retrying in {INTERVAL}s...')
    time.sleep(INTERVAL)
    elapsed += INTERVAL

remote_sys_id = results[0]['sys_id']
print(f'Found remote update set on test: {remote_sys_id} (state: {results[0]["state"]})')
gha_output('remote_sys_id', remote_sys_id)
