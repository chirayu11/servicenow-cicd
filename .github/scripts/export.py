#!/usr/bin/env python3
"""
export.py — export an update set as XML from the dev instance.

Reconstructs the standard ServiceNow unload XML format by querying the
sys_update_xml table via the REST API. This avoids the legacy
/sys_update_set_export_xml.do processor, which requires a browser-level
web session and does not work with Basic Auth in headless/CI environments.

Required env vars:
  SN_INSTANCE   — dev instance subdomain
  SN_USER       — dev admin username
  SN_PASS       — dev admin password
  SYS_ID        — sys_id of the local update set on dev
  SET_NAME      — update set name (for log messages)

Writes to $GITHUB_OUTPUT:
  export_file   — absolute path to the generated XML file
"""
import html
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from sn import ServiceNowClient, gha_output

SYS_ID   = os.environ['SYS_ID']
SET_NAME = os.environ['SET_NAME']

EXPORT_FILE = f'/tmp/update_set_{SYS_ID}.xml'

print(f"Exporting: '{SET_NAME}' (sys_id: {SYS_ID})")

client = ServiceNowClient.from_env()

# ---------------------------------------------------------------------------
# 1. Fetch the update set record
# ---------------------------------------------------------------------------
us = client.get_json(
    f'/api/now/table/sys_update_set/{SYS_ID}'
    f'?sysparm_fields=sys_id,name,description,state'
).get('result', {})

if not us:
    print(f'::error::Update set {SYS_ID} not found on dev.')
    sys.exit(1)

state = us.get('state', '')
if state != 'complete':
    print(
        f"::warning::Update set state is '{state}', expected 'complete'. "
        'Proceeding anyway.'
    )
else:
    print(f'Update set state: {state}')

# ---------------------------------------------------------------------------
# 2. Fetch all change records
# ---------------------------------------------------------------------------
print('Fetching change records from dev...')
records = client.get_json(
    f'/api/now/table/sys_update_xml'
    f'?sysparm_query=update_set={SYS_ID}'
    f'&sysparm_fields=payload'
    f'&sysparm_orderby=sys_created_on'
    f'&sysparm_limit=10000'
).get('result', [])

print(f'Found {len(records)} change record(s).')

if len(records) == 10000:
    print('::warning::Fetched exactly 10 000 records — update set may be larger than the limit.')

# ---------------------------------------------------------------------------
# 3. Build the XML in ServiceNow standard unload format
#
# Format:
#   <?xml version="1.0" encoding="UTF-8"?>
#   <unload unload_date="...">
#     <sys_update_set action="INSERT_OR_UPDATE">  <!-- update set metadata -->
#       <name>...</name>
#       ...
#     </sys_update_set>
#     <some_table action="INSERT_OR_UPDATE">      <!-- sys_update_xml.payload -->
#       ...
#     </some_table>
#     ...
#   </unload>
#
# Each sys_update_xml.payload is a complete XML element (the serialised form
# of the changed record). It is returned by the API as a raw string and can
# be embedded directly.
# ---------------------------------------------------------------------------
def xe(s: str) -> str:
    """XML-escape a string value for use as element text content."""
    return html.escape(str(s or ''), quote=False)

# Each payload is stored as a standalone XML document, so it starts with its
# own <?xml ...?> declaration. Strip that before embedding inside <unload>.
_XML_DECL = re.compile(r'^\s*<\?xml[^?]*\?>\s*', re.IGNORECASE)

unload_date = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    f'<unload unload_date="{unload_date}">',
    # Every element in a ServiceNow unload file is wrapped in <record_update
    # table="...">. The import processor uses the table attribute to decide
    # what record type to create — without this wrapper it silently ignores
    # the element and never creates the sys_remote_update_set record.
    '<record_update sys_domain="global" table="sys_update_set">',
    '<sys_update_set action="INSERT_OR_UPDATE">',
    f'<description>{xe(us.get("description", ""))}</description>',
    f'<name>{xe(us.get("name", SET_NAME))}</name>',
    f'<state>{xe(state)}</state>',
    f'<sys_id>{xe(us.get("sys_id", SYS_ID))}</sys_id>',
    '</sys_update_set>',
    '</record_update>',
]

for r in records:
    payload = _XML_DECL.sub('', r.get('payload', '')).strip()
    if payload:
        lines.append(payload)

lines.append('</unload>')

content = '\n'.join(lines).encode('utf-8')

with open(EXPORT_FILE, 'wb') as f:
    f.write(content)

# ---------------------------------------------------------------------------
# 4. Validate the constructed XML
# ---------------------------------------------------------------------------
try:
    ET.parse(EXPORT_FILE)
except ET.ParseError as e:
    print(f'::error::Constructed export XML is not valid: {e}')
    print(f'First 500 bytes: {content[:500]}')
    sys.exit(1)

print(f'Exported {len(content):,} bytes of XML to {EXPORT_FILE}')
print(f'First 800 bytes of generated XML:\n{content[:800].decode("utf-8", errors="replace")}')
gha_output('export_file', EXPORT_FILE)
