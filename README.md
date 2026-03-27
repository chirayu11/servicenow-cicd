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
                           ├─ Export XML from dev  ────────────────────►
                           │                         ◄── XML file ──────┘
                           │
                           ├─ Import XML to test  ──────────────────────►
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
5. 6 GitHub secrets configured (see table below)
6. A GitHub Environment named `deploy-test` with at least one required reviewer

### Step 1 — Configure secrets

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret Name        | Example value | Description                                              |
| ------------------ | ------------- | -------------------------------------------------------- |
| `SN_DEV_INSTANCE`  | `dev12345`    | Dev subdomain only — no `https://` or `.service-now.com` |
| `SN_DEV_USERNAME`  | `admin`       | Admin username for dev                                   |
| `SN_DEV_PASSWORD`  | `MyP@ss!`     | Admin password for dev                                   |
| `SN_TEST_INSTANCE` | `dev67890`    | Test subdomain only                                      |
| `SN_TEST_USERNAME` | `admin`       | Admin username for test                                  |
| `SN_TEST_PASSWORD` | `MyP@ss!`     | Admin password for test                                  |

### Step 2 — Create the `deploy-test` GitHub Environment

1. Go to **Settings → Environments → New environment**
2. Name it exactly: `deploy-test`
3. Under **Protection rules**, click **Required reviewers**
4. Add yourself (and/or your team)
5. Save

This is what pauses the workflow for human approval between discovery and deployment.

### Step 3 — Create a demo change in dev

See [Demo Change](#demo-change) below for a ready-to-go example.

### Step 4 — Run the workflow

1. Click the **Actions** tab in your repository
2. Click **ServiceNow — Promote Dev to Test** in the left sidebar
3. Click **Run workflow** (top right)
4. Optionally add a deployment label (e.g., `Sprint 12 release`)
5. Click the green **Run workflow** button

### Step 5 — Review and approve

1. Watch **Job 1: Discover** complete
2. Click the job to see the **Step Summary** — it lists everything that will be deployed
3. When prompted for approval on **Job 2**, review the list and click **Approve**

### Step 6 — Verify on test

After the workflow completes:
1. Log in to test
2. Go to **System Update Sets → Retrieved Update Sets**
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
If test has committed sets that have no corresponding complete set in dev, the environments are out of sync. The discover job fails with a descriptive error listing the extra sets. Remove them from test manually (**System Update Sets → Retrieved Update Sets**) and re-run the workflow.

---

## Demo Change

**Create a Custom Application Menu Item** — the most visual, zero-scripting demo change:

**Step 1 — Create an Update Set**
1. Log in to dev
2. Navigate to **System Update Sets → Local Update Sets**
3. Click **New**
4. Name it `Demo Navigation Item`
5. Set state to `In Progress`
6. Click **Save**
7. Click **Set Current** at the top of the record (makes this the active update set)

**Step 2 — Make a change**
1. Navigate to **System Definition → Application Menus**
2. Click **New**
3. Set **Title** to `Demo App` (or any name you want to see in the navigator)
4. Click **Submit**

**Step 3 — Complete the Update Set**
1. Navigate back to **System Update Sets → Local Update Sets**
2. Open `Demo Navigation Item`
3. Change **State** to `Complete`
4. Click **Update**

**Step 4 — Deploy**
1. Run the GitHub Actions workflow
2. Discovery will find `Demo Navigation Item`
3. Review and approve
4. After the run: log into test and look for `Demo App` in the left navigator

The result is binary and immediately obvious — either `Demo App` is in the test navigator or it isn't. No scripting, no technical knowledge required to verify.

---

## API Reference

The workflow uses these ServiceNow endpoints:

| Step                    | Method | Endpoint                                                                                    | Purpose                                       |
| ----------------------- | ------ | ------------------------------------------------------------------------------------------- | --------------------------------------------- |
| Discover dev            | GET    | `/api/now/table/sys_update_set?sysparm_query=state=complete&sysparm_orderby=sys_created_on` | All complete update sets in dev, oldest first |
| Discover test committed | GET    | `/api/now/table/sys_remote_update_set?sysparm_query=state=committed`                        | Already-committed sets on test                |
| Check partials          | GET    | `/api/now/table/sys_remote_update_set?sysparm_query=stateINloaded,previewed`                | Partial-state sets on test                    |
| Precheck                | GET    | `/api/now/table/sys_remote_update_set?sysparm_query=name=<name>`                            | Current state of a specific set on test       |
| Export                  | GET    | `/sys_update_set_export_xml.do?sysparm_sys_id=<id>`                                         | Download update set as XML from dev           |
| Import                  | POST   | `/sys_update_set_upload.do`                                                                 | Upload XML to test                            |
| Find remote record      | GET    | `/api/now/table/sys_remote_update_set?sysparm_query=name=<name>`                            | Locate imported record on test                |
| Trigger preview         | GET    | `/sys_remote_update_set_preview.do?sysparm_sys_id=<id>`                                     | Start collision detection on test             |
| Poll preview            | GET    | `/api/now/table/sys_remote_update_set/<id>`                                                 | Check preview progress on test                |
| Check collisions        | GET    | `/api/now/table/sys_update_preview_problem?sysparm_query=type=conflict`                     | Find conflicts                                |
| Commit                  | POST   | `/sys_remote_update_set_commit.do?sysparm_sys_id=<id>`                                      | Apply changes to test                         |

The export, import, preview, and commit endpoints (`*.do`) are legacy processor URLs — the same paths the ServiceNow UI uses internally. They work with HTTP Basic Auth.

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

| Symptom                                                  | Likely Cause                                                                      | Fix                                                                                                                              |
| -------------------------------------------------------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Discover fails: "test is ahead of dev"                   | Test has committed sets with no match in dev's complete list                      | Remove the listed sets from test manually: **System Update Sets → Retrieved Update Sets** → open each set → delete. Then re-run. |
| Discover returns 0 sets                                  | No complete update sets in dev, or all are already committed on test              | Check dev → Local Update Sets; confirm at least one shows state `complete`                                                       |
| `curl: (6) Could not resolve host`                       | Wrong instance name secret                                                        | Verify `SN_DEV_INSTANCE` / `SN_TEST_INSTANCE` — should be just the subdomain, e.g. `dev12345`                                    |
| Export step: "Response is not valid XML"                 | Instance is hibernating or credentials are wrong                                  | Log in to dev in a browser to wake it; re-verify `SN_DEV_USERNAME` / `SN_DEV_PASSWORD`                                           |
| Import step: "Could not locate remote update set record" | Upload succeeded but name lookup failed                                           | Manually check test → Retrieved Update Sets; the name must match exactly                                                         |
| Preview times out                                        | Large update set or slow instance                                                 | Increase `TIMEOUT` in `poll_preview.py` (default: 300s)                                                                          |
| Preview finds collisions                                 | A conflicting customisation already exists on test                                | Open test → Retrieved Update Sets → your set → Preview Problems; resolve manually                                                |
| Commit times out or state is not `committed`             | Large update set with long async processing                                       | Increase `TIMEOUT` in `commit.py` (default: 300s); check test → Retrieved Update Sets manually                                   |
| Approval gate: "No reviewers" error                      | `deploy-test` environment has no required reviewers configured                    | Go to Settings → Environments → deploy-test → add required reviewers                                                             |
| HTTP 401 on any step                                     | Wrong credentials or session expired                                              | Instances hibernate after inactivity — log in via browser to reactivate; re-verify secrets                                       |
| Precheck shows `resume_loaded` or `resume_previewed`     | A previous pipeline run partially completed, or someone manually imported the set | Normal — the pipeline resumes from the right step automatically. No action needed.                                               |
