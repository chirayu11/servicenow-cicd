# CLAUDE.md — ServiceNow CI/CD Pipeline

## What this project does

Automates promotion of completed ServiceNow Update Sets from a **dev** PDI to a **test** PDI via GitHub Actions. The pipeline:

1. **Discovers** all complete update sets in dev not yet committed on test
2. **Pauses for human approval** via a GitHub Environment gate
3. **Deploys each set** sequentially: transfer → preview → commit
4. **Writes a summary** report to GitHub Step Summary

---

## Repository structure

```
.github/
  workflows/
    servicenow-deploy.yml   # Main workflow — 4 jobs: discover, await-approval, deploy, summary
  scripts/
    sn.py                   # Shared HTTP client (ServiceNowClient) + GHA output helpers
    discover.py             # Job 1: query dev+test, compute delta, write review table
    precheck.py             # Step 0 of deploy: query test live for per-set current state
    transfer.py             # Step 1: CI/CD retrieve API — test pulls update set from dev
    trigger_preview.py      # Step 2: trigger collision-detection preview on test
    poll_preview.py         # Step 3: poll until preview completes, fail on collisions
    commit.py               # Step 4: commit via CI/CD API, poll until committed
```

---

## ServiceNow concepts

- **Local Update Set** (`sys_update_set`) — tracks changes made on dev. States: `in progress` → `complete`
- **Remote Update Set** (`sys_remote_update_set`) — record created on test when a set is retrieved. States: `loaded` → `previewed` → `committed`
- **Preview** — collision detection. Checks whether the set's changes conflict with what's already on test. Must succeed before commit.
- **Commit** — applies the changes to test. Irreversible per-run.
- **Remote Update Source** (`sys_update_set_source`) — a connection record on test that holds dev instance URL + credentials. The CI/CD retrieve API uses this to pull sets from dev.

---

## ServiceNow API endpoints in use

All authenticated with HTTP Basic Auth. The Table API (`/api/now/table/*`) and CI/CD API (`/api/sn_cicd/*`) both work. Legacy `.do` processor endpoints (Jelly) work for GET/trigger but **not** for POST commits (CSRF enforcement).

| Step | Method | Endpoint |
|---|---|---|
| Query dev complete sets | GET | `/api/now/table/sys_update_set?sysparm_query=state=complete` |
| Query test committed sets | GET | `/api/now/table/sys_remote_update_set?sysparm_query=state=committed` |
| Query test partial sets | GET | `/api/now/table/sys_remote_update_set?sysparm_query=stateIN(loaded,previewed)` |
| Precheck per set | GET | `/api/now/table/sys_remote_update_set?sysparm_query=name=<name>` |
| Transfer (retrieve) | POST | `/api/sn_cicd/update_set/retrieve?update_set_id=<id>&update_source_id=<id>` |
| Poll progress | GET | `/api/sn_cicd/progress/<progress_id>` |
| Trigger preview | POST | `/sys_remote_update_set_preview.do?sysparm_sys_id=<id>` (legacy .do, works with Basic Auth) |
| Poll preview state | GET | `/api/now/table/sys_remote_update_set/<id>?sysparm_fields=state` |
| Check collisions | GET | `/api/now/table/sys_update_preview_problem?sysparm_query=remote_update_set=<id>^type=conflict` |
| Commit | POST | `/api/sn_cicd/update_set/commit/<remote_sys_id>` |

Progress poll status codes: `0=Pending, 1=Running, 2=Successful, 3=Failed, 4=Cancelled`

---

## One-time setup required before first run

### 1. Remote Update Source on test instance

On the **test** ServiceNow instance:
1. Navigate to **System Update Sets → Update Sources → New** (or `sys_update_set_source.list` in browser URL)
2. Fill in:
   - **Name**: anything (e.g. `Dev Instance`)
   - **URL**: `https://<dev-subdomain>.service-now.com`
   - **Username** / **Password**: dev admin credentials
3. Save and copy the record's **sys_id** from the URL

### 2. GitHub Secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `SN_DEV_INSTANCE` | dev subdomain only (e.g. `dev12345`) |
| `SN_DEV_USERNAME` | dev admin username |
| `SN_DEV_PASSWORD` | dev admin password |
| `SN_TEST_INSTANCE` | test subdomain only |
| `SN_TEST_USERNAME` | test admin username |
| `SN_TEST_PASSWORD` | test admin password |
| `SN_DEV_UPDATE_SOURCE_ID` | sys_id of the Update Source record you created on test |

### 3. GitHub Environment

Go to **Settings → Environments → New environment**:
- Name: `deploy-test`
- Add at least one required reviewer
- (Optional) set a timeout

---

## Approaches that were tried and failed — do not revisit

### Export XML via `sys_update_set_export_xml.do`
Returns HTML (the login page or instance hibernation page), not XML. Requires a full browser session with cookies, not just Basic Auth.

### Construct XML from Table API + upload via `sys_update_set_upload.do`
Two problems:
1. The XML format required is the **exchange format** (`<sys_remote_update_set>` wrapper), not the internal unload format (`<record_update table="sys_update_set">`). Getting this exactly right is fragile.
2. Even with the correct format, `sys_update_set_upload.do` returns HTTP 200 but re-renders the upload form — the POST silently does nothing without a CSRF token from a real browser session.

### Direct REST API write to `sys_update_xml`
Blocked by ServiceNow ACL — returns 403 "ACL Exception Insert Failed". The change records table is protected from external writes.

### Commit via `sys_remote_update_set_commit.do`
The legacy `.do` commit processor requires `sysparm_ck=<csrf_token>`. With an empty or absent CSRF token, the POST returns HTTP 200 but does nothing — the update set stays in `previewed` state indefinitely. The CI/CD API (`/api/sn_cicd/update_set/commit/<id>`) is the correct solution.

---

## Precheck resume logic

At the start of each deploy job, `precheck.py` queries test live and outputs an `action`:

| Test state | Action | What happens next |
|---|---|---|
| Not found | `deploy` | Full transfer → preview → commit |
| `loaded` | `resume_loaded` | Skip transfer, run preview + commit |
| `previewed` | `resume_previewed` | Skip transfer + preview trigger, run poll + commit |
| `committed` | `skip` | Log notice, skip all steps |

This handles sets manually deployed between discovery and the approval gate, and recovery from partial pipeline failures.

---

## ServiceNow UI — Next Experience (Polaris / Zurich)

The user is on the **Zurich release** with the **Next Experience UI** — there is **no left sidebar**.

Navigation tips:
- **"All" menu** (top-left) → search bar for app modules by name. Does **not** support `tablename.list` syntax.
- **Direct URL** in browser address bar: `https://<instance>.service-now.com/<table>_list.do` — always works.
- **Global search bar** (top centre) — searches records, not module names.
- To navigate to any table directly: use the URL pattern above.

Key navigation URLs for this project:
```
/sys_update_set_list.do               — Local Update Sets (dev)
/sys_remote_update_set_list.do        — Retrieved Update Sets (test)
/sys_update_set_source_list.do        — Update Sources (test)
/sys_announcement_list.do             — System Announcements
/sys_app_module_list.do               — Application Modules
```

**Service Portal Announcements** (`sp_announcement`) are different from **System Announcements** (`sys_announcement`). System Announcements show a banner across the top of every page in the main UI.

---

## Demo change — System Announcement

The most visually obvious demo: a coloured banner appears at the top of every page on test after deployment. No navigation needed to verify.

**In dev:**
1. Go to `https://<dev>.service-now.com/sys_announcement_list.do`
2. Click New
3. Set **Text**, **Style** (info/warning/success), **Active** = checked
4. Save
5. Open your update set → right-click the form header → **Add to Update Set** (or use the hamburger menu)
6. Mark the update set Complete

**After deploy to test:** the banner appears immediately on all pages.

---

## Python dependencies

Scripts use `requests` (imported in `sn.py`). GitHub Actions runner has Python 3 available; `requests` must be installed. Currently handled implicitly — if it fails, add a `pip install requests` step before the Python scripts run.

---

## PDI hibernation

Personal Developer Instances (PDIs) hibernate after inactivity. If any API call returns HTML instead of JSON, or HTTP 200 with a login page body, the instance is asleep. Fix: log in via browser on that instance to wake it, then re-run the workflow.
