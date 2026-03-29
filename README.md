# ServiceNow CI/CD Pipeline

Automated promotion of completed Update Sets from **dev** to **test** via GitHub Actions.

---

## How It Works

```
  DEVELOPER                GITHUB ACTIONS                 SERVICENOW
  ─────────                ──────────────                 ──────────

  1. Make changes
     in dev
     (complete the
     update set)
          │
          ▼
  2. Click "Run
     workflow" in
     GitHub Actions  ──►  JOB 1: Discover
                           Query dev for all
                           complete update sets
                               │
                           Query test for all
                           committed sets
                               │
                           Fail if test is ahead
                           Compute delta
                           Write review table  ────────────────►
                               │                               │
                          ─────▼────────                       │
                         | Review table |   ◄──────────────────┘
                         |  in Actions  |
                         └──────┬───────┘
  3. Review list                │
     Approve or Deny  ◄─────────┘
          │
       Approve
          │
          └──────────►  JOB 3: Deploy (per set, in order)
                           │
                           ├─ Precheck state on test  ─────────────────►
                           │   (skip/resume if already imported)
                           │
                           ├─ Transfer (CI/CD retrieve API)
                           │   test pulls directly from dev  ──────────►
                           │   using pre-configured Update Source
                           │
                           ├─ Trigger Preview on test  ────────────────►
                           │   (collision detection)
                           │
                           ├─ Poll until complete  ─────────────────────
                           │   Check for conflicts
                           │
                           └─ Commit on test  ──────────────────────────►
                                                 Changes live on test  ──►

                        JOB 4: Summary
                           Write deployment report
```

---

## Quickstart

### What you need before the first run

1. Two active ServiceNow instances (PDIs hibernate — just log in to wake them)
2. Admin credentials for both
3. At least one Update Set in **Complete** state in dev
4. A GitHub repository with Actions enabled
5. A **Remote Update Source** record configured on test (see Step 1 below)
6. 7 GitHub secrets configured (see Step 2 below)
7. A GitHub Environment named `deploy-test` with at least one required reviewer

### Step 1 — Create a Remote Update Source on test

The transfer step works by telling the **test** instance to pull the update set directly from dev. This requires a one-time connection record on test.

1. Log in to the **test** instance
2. In the browser address bar go to: `https://<test>.service-now.com/sys_update_set_source_list.do`
3. Click **New**
4. Fill in:
   - **Name**: anything (e.g. `Dev Instance`)
   - **URL**: `https://<dev-subdomain>.service-now.com`
   - **Username** / **Password**: dev admin credentials
5. Save the record
6. Copy the **sys_id** from the URL (the 32-character hex value after `sys_id=`)

You will use this sys_id as the `SN_DEV_UPDATE_SOURCE_ID` secret in Step 2.

### Step 2 — Configure secrets

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret Name                | Example value                      | Description                                                      |
| -------------------------- | ---------------------------------- | ---------------------------------------------------------------- |
| `SN_DEV_INSTANCE`          | `dev12345`                         | Dev subdomain only — no `https://` or `.service-now.com`         |
| `SN_DEV_USERNAME`          | `admin`                            | Admin username for dev                                           |
| `SN_DEV_PASSWORD`          | `MyP@ss!`                          | Admin password for dev                                           |
| `SN_TEST_INSTANCE`         | `dev67890`                         | Test subdomain only                                              |
| `SN_TEST_USERNAME`         | `admin`                            | Admin username for test                                          |
| `SN_TEST_PASSWORD`         | `MyP@ss!`                          | Admin password for test                                          |
| `SN_DEV_UPDATE_SOURCE_ID`  | `abc123...` (32-char hex)          | sys_id of the Update Source record you created on test in Step 1 |

### Step 3 — Create the `deploy-test` GitHub Environment

1. Go to **Settings → Environments → New environment**
2. Name it exactly: `deploy-test`
3. Under **Protection rules**, click **Required reviewers**
4. Add yourself (and/or your team)
5. Save

This is what pauses the workflow for human approval between discovery and deployment.

### Step 4 — Create a demo change in dev

See [Demo Change](#demo-change) below for a ready-to-go example.

### Step 5 — Run the workflow

1. Click the **Actions** tab in your repository
2. Click **ServiceNow — Promote Dev to Test** in the left sidebar
3. Click **Run workflow** (top right)
4. Optionally add a deployment label (e.g., `Sprint 12 release`)
5. Click the green **Run workflow** button

### Step 6 — Review and approve

1. Watch **Job 1: Discover** complete
2. Click the job to see the **Step Summary** — it lists everything that will be deployed
3. When prompted for approval on **Job 2**, review the list and click **Approve**

### Step 7 — Verify on test

After the workflow completes:
1. Log in to test
2. Go to `https://<test>.service-now.com/sys_remote_update_set_list.do`
3. Your update sets should show state **Committed**
4. Navigate to the record you changed to confirm it exists on test

---

## Workflow Inputs

| Input              | Required | Default               | Description                                                                                                                          |
| ------------------ | -------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `deployment_label` | No       | `Promote dev to test` | Human-readable description of this release — appears in the run title and summary report                                             |
| `dry_run`          | No       | `false`               | Runs only the Discover job — shows what would be deployed without touching either instance. Use for first-time connectivity testing. |

No manual update set names required. The workflow automatically discovers all completed update sets in dev that have not yet been committed to test.

---

## Discovery Logic

The **Discover** job computes the deployment list as follows:

```
  dev complete update sets
            minus
  test committed remote update sets
            =
  Sets to deploy (ordered oldest-first)
```

**What "oldest-first" means:** Sets are deployed in the order they were created in dev. This preserves the natural dependency chain — a set that creates a table is deployed before a set that adds fields to that table.

**What happens to incomplete sets:**
Sets in dev that are not in `complete` state are excluded from discovery. They will appear automatically in the next workflow run once the developer marks them complete.

**What happens if test has partial state sets (loaded/previewed):**
These sets are included in the deploy list. The per-set precheck in the deploy job detects their current state and automatically resumes from the right step — no manual intervention needed.

**What happens if test is ahead of dev:**
If test has committed sets that have no corresponding complete set in dev, the environments are out of sync. The discover job fails with a descriptive error listing the extra sets. Remove them from test manually (`sys_remote_update_set_list.do`) and re-run the workflow.

---

## Demo Change

**Create a System Announcement** — a coloured banner that appears across the top of every page on test. Binary and immediately obvious — no navigation or specialist knowledge required to verify.

**Step 1 — Create an Update Set**
1. Log in to dev
2. Go to `https://<dev>.service-now.com/sys_update_set_list.do`
3. Click **New**
4. Name it anything (e.g. `Demo Announcement`)
5. Set state to `In Progress` and click **Save**
6. Click **Set Current** at the top of the record

**Step 2 — Create the announcement**
1. Go to `https://<dev>.service-now.com/sys_announcement_list.do`
2. Click **New**
3. Fill in:
   - **Text**: anything (e.g. `Deployed via GitHub Actions CI/CD`)
   - **Style**: `Success` (green), `Info` (blue), or `Warning` (yellow)
   - **Active**: checked
4. Save
5. Open the record, open the form context menu (hamburger icon top-left of the form), click **Add to Update Set**

**Step 3 — Complete the Update Set**
1. Go back to `sys_update_set_list.do`
2. Open your update set, change **State** to `Complete`, click **Update**

**Step 4 — Deploy**
1. Run the GitHub Actions workflow
2. Discovery will find the update set
3. Review and approve
4. After the run: log into test — the banner appears immediately at the top of every page

---

## API Reference

The workflow uses these ServiceNow endpoints, all authenticated with HTTP Basic Auth:

| Step                  | Method | Endpoint                                                                                        | Purpose                                           |
| --------------------- | ------ | ----------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| Discover dev          | GET    | `/api/now/table/sys_update_set?sysparm_query=state=complete&sysparm_orderby=sys_created_on`     | All complete update sets in dev, oldest first     |
| Discover test         | GET    | `/api/now/table/sys_remote_update_set?sysparm_query=state=committed`                            | Already-committed sets on test                    |
| Check partials        | GET    | `/api/now/table/sys_remote_update_set?sysparm_query=stateIN(loaded,previewed)`                  | Partial-state sets on test                        |
| Precheck              | GET    | `/api/now/table/sys_remote_update_set?sysparm_query=name=<name>`                                | Current state of a specific set on test           |
| Transfer              | POST   | `/api/sn_cicd/update_set/retrieve?update_set_id=<id>&update_source_id=<id>`                     | Tell test to pull the update set from dev         |
| Poll progress         | GET    | `/api/sn_cicd/progress/<progress_id>`                                                           | Poll async transfer or commit (status 2=success)  |
| Trigger preview       | POST   | `/sys_remote_update_set_preview.do?sysparm_sys_id=<id>`                                         | Start collision detection on test                 |
| Poll preview state    | GET    | `/api/now/table/sys_remote_update_set/<id>?sysparm_fields=state`                                | Check preview progress                            |
| Check collisions      | GET    | `/api/now/table/sys_update_preview_problem?sysparm_query=remote_update_set=<id>^type=conflict`  | Find conflicts after preview                      |
| Commit                | POST   | `/api/sn_cicd/update_set/commit/<remote_sys_id>`                                                | Apply the update set to test                      |

---

## Vision Roadmap

```
  Phase 1 — Current (PoC)
  ─────────────────────────────────────────────────────────────────
  Auto-discover completed update sets (dev → test)
  Mid-workflow human review table
  Human approval gate via GitHub Environments
  Sequential deployment with collision detection
  Idempotent per-set precheck (resume from any partial state)


  Phase 2 — Quality Gates
  ─────────────────────────────────────────────────────────────────
  Bravium Code Linting
    Run Bravium ServiceNow Code Review against the exported XML
    before deployment begins. Block on critical findings.
    Add as a 'lint' job between Discover and Await Approval.


  Phase 3 — Post-Deploy Verification
  ─────────────────────────────────────────────────────────────────
  Playwright Tests in SauceLabs
    After all sets are committed, trigger a Playwright test suite
    against test running in SauceLabs. Verify the deployed
    features work end-to-end in a real browser environment.
    Add as a 'verify' job after Deploy.


  Phase 4 — Traceability
  ─────────────────────────────────────────────────────────────────
  Changelog + GitHub Releases
    Auto-generate CHANGELOG entries for each deployment.
    Create a tagged GitHub Release with the update set names,
    deployment label, approver, and timestamp.

  ServiceNow Change Request Record
    Before the first set deploys, create a sys_change_request
    record in test capturing the deployment details.
    Close the record with pass/fail status after all sets commit.
    Full audit trail lives in ServiceNow alongside the changes.
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| Discover fails: "test is ahead of dev" | Test has committed sets with no match in dev's complete list | Remove the listed sets from test manually: go to `sys_remote_update_set_list.do` on test, open each set → delete. Then re-run. |
| Discover returns 0 sets | No complete update sets in dev, or all are already committed on test | Check dev → `sys_update_set_list.do`; confirm at least one shows state `complete` |
| `Could not resolve host` on any step | Wrong instance name in a secret | Verify `SN_DEV_INSTANCE` / `SN_TEST_INSTANCE` — should be just the subdomain, e.g. `dev12345` (no `https://`) |
| Transfer fails: "Unexpected retrieve response" | `SN_DEV_UPDATE_SOURCE_ID` is wrong or the Update Source record was deleted | Verify the sys_id on test: `sys_update_set_source_list.do` — re-copy and update the secret |
| Transfer fails: HTTP 401 | Wrong credentials, or the Update Source record has stale dev credentials | Check `SN_TEST_USERNAME` / `SN_TEST_PASSWORD`; also update the credentials in the Update Source record on test |
| Transfer times out after 300s | Large update set, or dev instance is hibernating | Log in to dev in a browser to wake it; increase `MAX_WAIT` in `transfer.py` if needed |
| Preview times out | Large update set or slow instance | Increase `TIMEOUT` in `poll_preview.py` (default: 300s) |
| Preview finds collisions | A conflicting customisation already exists on test | Go to test → `sys_remote_update_set_list.do` → open your set → Preview Problems; resolve manually |
| Commit times out | Large update set | Increase `TIMEOUT` in `commit.py` (default: 60s) |
| HTTP 401 on any step | Instance is hibernating | Log in via browser to reactivate the instance; re-run the workflow |
| Precheck shows `resume_loaded` or `resume_previewed` | A previous pipeline run partially completed, or someone manually imported the set | Normal — the pipeline resumes from the right step automatically. No action needed. |
| Approval gate: "No reviewers" error | `deploy-test` environment has no required reviewers configured | Go to Settings → Environments → deploy-test → add required reviewers |
