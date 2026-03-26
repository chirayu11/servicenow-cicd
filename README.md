# ServiceNow CI/CD Pipeline

Automated promotion of completed Update Sets from **PDI1 (dev)** to **PDI2 (test)** via GitHub Actions.

---

## How It Works

```
  DEVELOPER                GITHUB ACTIONS                 SERVICENOW
  ─────────                ──────────────                 ──────────

  1. Make changes
     in PDI1
     (complete the
     update set)
          │
          ▼
  2. Click "Run
     workflow" in
     GitHub Actions  ──►  JOB 1: Discover
                           Query PDI1 for all
                           complete update sets
                               │
                           Query PDI2 for all
                           committed sets
                               │
                           Compute delta
                           Write review table  ──────────────────────►
                               │                               │
                          ─────▼─────                         │
                         | Review table |   ◄─────────────────┘
                         |  in Actions  |
                         └──────┬───────┘
  3. Review list                │
     Approve or Deny  ◄─────────┘
          │
       Approve
          │
          └──────────►  JOB 3: Deploy (per set, in order)
                           │
                           ├─ Export XML from PDI1  ──────────────────►
                           │                         ◄── XML file ─────┘
                           │
                           ├─ Import XML to PDI2  ─────────────────────►
                           │
                           ├─ Trigger Preview on PDI2  ────────────────►
                           │   (collision detection)
                           │
                           ├─ Poll until complete  ─────────────────────
                           │   Check for conflicts
                           │
                           └─ Commit on PDI2  ──────────────────────────►
                                                 Changes live on PDI2  ──►

                        JOB 4: Summary
                           Write deployment report
```

---

## Quickstart

### What you need before the first run

1. Two active ServiceNow PDI instances (PDIs hibernate — just log in to wake them)
2. Admin credentials for both
3. At least one Update Set in **Complete** state on PDI1
4. A GitHub repository with Actions enabled
5. 6 GitHub secrets configured (see table below)
6. A GitHub Environment named `deploy-test` with at least one required reviewer

### Step 1 — Configure secrets

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | Example value | Description |
|---|---|---|
| `SN_PDI1_INSTANCE` | `dev12345` | PDI1 subdomain only — no `https://` or `.service-now.com` |
| `SN_PDI1_USERNAME` | `admin` | Admin username for PDI1 |
| `SN_PDI1_PASSWORD` | `MyP@ss!` | Admin password for PDI1 |
| `SN_PDI2_INSTANCE` | `dev67890` | PDI2 subdomain only |
| `SN_PDI2_USERNAME` | `admin` | Admin username for PDI2 |
| `SN_PDI2_PASSWORD` | `MyP@ss!` | Admin password for PDI2 |

### Step 2 — Create the `deploy-test` GitHub Environment

1. Go to **Settings → Environments → New environment**
2. Name it exactly: `deploy-test`
3. Under **Protection rules**, click **Required reviewers**
4. Add yourself (and/or your team)
5. Save

This is what pauses the workflow for human approval between discovery and deployment.

### Step 3 — Create a demo change in PDI1

See [Demo Change](#demo-change-for-pdi1) below for a ready-to-go example.

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

### Step 6 — Verify on PDI2

After the workflow completes:
1. Log in to PDI2
2. Go to **System Update Sets → Retrieved Update Sets**
3. Your update sets should show state **Committed**
4. Navigate to the record you changed to confirm it exists on PDI2

---

## Workflow Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `deployment_label` | No | `Promote dev to test` | Human-readable description of this release — appears in the run title and summary report |
| `dry_run` | No | `false` | Runs only the Discover job — shows what would be deployed without touching either instance. Use for first-time connectivity testing. |

No manual update set names required. The workflow automatically discovers all completed update sets in PDI1 that have not yet been committed to PDI2.

---

## Discovery Logic

The **Discover** job computes the deployment list as follows:

```
  PDI1 complete update sets
            minus
  PDI2 committed remote update sets
            =
  Sets to deploy (ordered oldest-first)
```

**What "oldest-first" means:** Sets are deployed in the order they were created in PDI1. This preserves the natural dependency chain — a set that creates a table is deployed before a set that adds fields to that table.

**What happens to incomplete sets:**
Sets in PDI1 that are not in `complete` state are excluded from discovery. They will appear automatically in the next workflow run once the developer marks them complete.

**What happens if PDI2 has partial state sets:**
If a previous deployment partially completed (a set was imported/previewed but not committed), the workflow warns you and does not attempt to redeploy those sets automatically. Resolve them manually in PDI2 first.

---

## Demo Change for PDI1

**Create a Custom Application Menu Item** — the most visual, zero-scripting demo change:

**Step 1 — Create an Update Set**
1. Log in to PDI1
2. Navigate to **System Update Sets → Local Update Sets**
3. Click **New**
4. Name it `Demo Navigation Item`
5. Set state to `In Progress`
6. Click **Save**
7. Click **Set Current** at the top of the record (makes this the active update set)

**Step 2 — Make a change**
1. Navigate to **System UI → Application Menus**
2. Click **New**
3. Set **Title** to `Demo App` (or any name you want to see in the navigator)
4. Click **Save**

**Step 3 — Complete the Update Set**
1. Navigate back to **System Update Sets → Local Update Sets**
2. Open `Demo Navigation Item`
3. Change **State** to `Complete`
4. Click **Save**

**Step 4 — Deploy**
1. Run the GitHub Actions workflow
2. Discovery will find `Demo Navigation Item`
3. Review and approve
4. After the run: log into PDI2 and look for `Demo App` in the left navigator

The result is binary and immediately obvious — either `Demo App` is in the PDI2 navigator or it isn't. No scripting, no technical knowledge required to verify.

---

## API Reference

The workflow uses these ServiceNow endpoints:

| Step | Method | Endpoint | Purpose |
|---|---|---|---|
| Discover PDI1 | GET | `/api/now/table/sys_update_set?sysparm_query=state=complete&sysparm_orderby=sys_created_on` | All complete update sets, oldest first |
| Discover PDI2 | GET | `/api/now/table/sys_remote_update_set?sysparm_query=state=committed` | Already-committed sets |
| Check partials | GET | `/api/now/table/sys_remote_update_set?sysparm_query=stateINloaded,previewed` | Partial/stuck sets |
| Export | GET | `/sys_update_set_export_xml.do?sysparm_sys_id=<id>` | Download update set as XML |
| Import | POST | `/sys_update_set_upload.do` | Upload XML to PDI2 |
| Find remote record | GET | `/api/now/table/sys_remote_update_set?sysparm_query=name=<name>` | Locate imported record |
| Trigger preview | GET | `/sys_remote_update_set_preview.do?sysparm_sys_id=<id>` | Start collision detection |
| Poll preview | GET | `/api/now/table/sys_remote_update_set/<id>` | Check preview progress |
| Check collisions | GET | `/api/now/table/sys_update_preview_problem?sysparm_query=type=conflict` | Find conflicts |
| Commit | POST | `/sys_remote_update_set_commit.do?sysparm_sys_id=<id>` | Apply changes to PDI2 |

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
    against PDI2 running in SauceLabs. Verify the deployed
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
    record in PDI2 capturing the deployment details.
    Close the record with pass/fail status after all sets commit.
    Full audit trail lives in ServiceNow alongside the changes.
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Discover returns 0 sets | No complete update sets in PDI1, or all are already committed on PDI2 | Check PDI1 → Local Update Sets; confirm at least one shows state `complete` |
| `curl: (6) Could not resolve host` | Wrong instance name secret | Verify `SN_PDI1_INSTANCE` / `SN_PDI2_INSTANCE` — should be just the subdomain, e.g. `dev12345` |
| Export step: "Response is not valid XML" | PDI is hibernating or credentials are wrong | Log in to PDI1 in a browser to wake it; re-verify `SN_PDI1_USERNAME` / `SN_PDI1_PASSWORD` |
| Import step: "Could not locate remote update set record" | Upload succeeded but name lookup failed | Manually check PDI2 → Retrieved Update Sets; the name must match exactly |
| Preview times out | Large update set or slow PDI | Increase `TIMEOUT` in the poll step (default: 300s) |
| Preview finds collisions | A conflicting customization already exists on PDI2 | Open PDI2 → Retrieved Update Sets → your set → Preview Problems; resolve manually |
| Commit state is not `committed` | Preview had warnings that weren't caught, or the commit processor is slow | Wait 30 seconds and re-check PDI2 manually; for large sets, increase the `sleep 5` before the state check |
| Approval gate: "No reviewers" error | `deploy-test` environment has no required reviewers configured | Go to Settings → Environments → deploy-test → add required reviewers |
| HTTP 401 on any step | Wrong credentials or session expired | PDIs hibernate after inactivity — log in via browser to reactivate; re-verify secrets |
