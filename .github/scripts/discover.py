#!/usr/bin/env python3
"""
discover.py — query both instances and compute the update set deployment list.

Queries:
  dev  — all complete local update sets (oldest first, preserves dependency order)
  test — all committed remote update sets
  test — all partial-state remote update sets (loaded/previewed)

Fails (exit 1) if test is ahead of dev — i.e., test has committed sets that
have no corresponding complete set in dev.

Writes to $GITHUB_STEP_SUMMARY and $GITHUB_OUTPUT:
  sets_json   — JSON array; each element: name, sys_id, created, description,
                test_state, test_sys_id
  set_count   — integer count

Required env vars:
  SN_DEV_INSTANCE   SN_DEV_USER   SN_DEV_PASS
  SN_TEST_INSTANCE  SN_TEST_USER  SN_TEST_PASS
"""
import json
import sys

from sn import ServiceNowClient, gha_output_multiline, gha_output, gha_summary

dev  = ServiceNowClient.from_env('SN_DEV')
test = ServiceNowClient.from_env('SN_TEST')

# ---------------------------------------------------------------------------
# Query 1: dev — all complete local update sets, oldest first.
# Oldest-first ordering preserves the natural dependency chain
# (e.g. a table-creation set deploys before a field-addition set).
# ---------------------------------------------------------------------------
dev_sets = dev.get_json(
    '/api/now/table/sys_update_set'
    '?sysparm_query=state%3Dcomplete'
    '&sysparm_orderby=sys_created_on'
    '&sysparm_fields=sys_id,name,description,state,sys_created_on'
    '&sysparm_limit=500'
).get('result', [])
print(f'Found {len(dev_sets)} complete update set(s) on dev')

# ---------------------------------------------------------------------------
# Query 2: test — all already-committed remote update sets.
# ---------------------------------------------------------------------------
test_committed_list = test.get_json(
    '/api/now/table/sys_remote_update_set'
    '?sysparm_query=state%3Dcommitted'
    '&sysparm_fields=name,state'
    '&sysparm_limit=500'
).get('result', [])
print(f'Found {len(test_committed_list)} already-committed update set(s) on test')

# ---------------------------------------------------------------------------
# Query 3: test — partial-state sets (loaded/previewed).
# These are included in the deploy list; the per-set precheck in Job 3
# will resume them from the appropriate step automatically.
# ---------------------------------------------------------------------------
test_partial_list = test.get_json(
    '/api/now/table/sys_remote_update_set'
    '?sysparm_query=stateIN%28loaded%2Cpreviewed%29'
    '&sysparm_fields=sys_id,name,state'
    '&sysparm_limit=50'
).get('result', [])
if test_partial_list:
    print(
        f'::notice::Found {len(test_partial_list)} update set(s) on test in partial state '
        '(loaded/previewed). The deploy job will resume these automatically.'
    )
    for r in test_partial_list:
        print(f"  - '{r['name']}' (state: {r['state']})")

# Build lookup structures
dev_complete_names   = {s['name'].strip().lower() for s in dev_sets}
test_committed_names = {r['name'].strip().lower() for r in test_committed_list}
test_partial = {                                    # name_lower -> {state, sys_id}
    r['name'].strip().lower(): {'state': r['state'], 'sys_id': r['sys_id']}
    for r in test_partial_list
}

# ---------------------------------------------------------------------------
# Safety check: fail hard if test is ahead of dev.
# ---------------------------------------------------------------------------
extra_on_test = sorted(
    r['name'].strip()
    for r in test_committed_list
    if r['name'].strip().lower() not in dev_complete_names
)

if extra_on_test:
    lines = [
        '## Discover Results\n',
        '> [!CAUTION]',
        '> **test is ahead of dev.**',
        '> The following update sets are committed on test but have no corresponding'
        ' complete set in dev.',
        '> Please remove them from test manually (**System Update Sets → Retrieved Update Sets**)'
        ' to bring the environments back in sync, then re-run this workflow.\n',
    ]
    for name in extra_on_test:
        lines.append(f'> - `{name}`')
    gha_summary('\n'.join(lines) + '\n')

    names_str = ', '.join(f"'{n}'" for n in extra_on_test)
    print(
        f'::error::test is ahead of dev. {len(extra_on_test)} set(s) on test have no match '
        f'in dev: {names_str}. Remove them from test manually and re-run.'
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Compute the deploy list.
# ---------------------------------------------------------------------------
to_deploy = []
skipped_committed = []

for s in dev_sets:
    name = s['name'].strip()
    name_lower = name.lower()
    if name_lower in test_committed_names:
        skipped_committed.append(name)
    else:
        partial_info = test_partial.get(name_lower)
        to_deploy.append({
            'name': name,
            'sys_id': s['sys_id'],
            'created': s.get('sys_created_on', '')[:10],
            'description': (s.get('description') or '').strip(),
            'test_state': partial_info['state'] if partial_info else None,
            'test_sys_id': partial_info['sys_id'] if partial_info else None,
        })

# ---------------------------------------------------------------------------
# Write Step Summary
# ---------------------------------------------------------------------------
lines = ['## Discover Results\n']

if to_deploy:
    lines.append(f'**{len(to_deploy)} update set(s) ready to promote dev → test:**\n')
    lines.append('| # | Update Set | Created | Test State | Description |')
    lines.append('|---|---|---|---|---|')
    for i, s in enumerate(to_deploy, 1):
        desc = s['description']
        if len(desc) > 60:
            desc = desc[:60] + '…'
        state_badge = f'`{s["test_state"]}`' if s['test_state'] else '—'
        lines.append(
            f"| {i} | `{s['name']}` | {s['created']} | {state_badge} | {desc or '—'} |"
        )
else:
    lines.append('**Nothing to deploy — test is already up to date.**\n')

if skipped_committed:
    lines.append('\n<details>')
    lines.append('<summary>Already committed on test (skipped)</summary>\n')
    for name in skipped_committed:
        lines.append(f'- `{name}`')
    lines.append('\n</details>')

gha_summary('\n'.join(lines) + '\n')

# ---------------------------------------------------------------------------
# Write job outputs
# ---------------------------------------------------------------------------
gha_output_multiline('sets_json', json.dumps(to_deploy))
gha_output('set_count', str(len(to_deploy)))
print(f'Sets to deploy: {len(to_deploy)}')
