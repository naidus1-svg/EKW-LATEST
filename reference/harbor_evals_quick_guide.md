# Harbor evals: quick operator guide

Use this guide for an approved external task batch on beta.

Before starting, ask the run owner for:

- the batch prefix;
- exact model names and reasoning efforts;
- `k` (trials per task per model);
- the current beta app URL;
- confirmation that the enqueue cron is suspended; and
- confirmation that the correct provider keys are deployed.

Do not repair verifier code, change keys, delete pending markers, purge queues,
or kill pods. Ask an engineer when a check fails.

## 1. Expected task format

Every task needs a unique prefixed ID:

```text
Received ID: task_279
Batch prefix: k1-0720
Harbor ID:    k1-0720-task_279
```

Expected local layout:

```text
<ready-batch>/
  <harbor-task-id>/
    v1/
      harbor_task/
        instruction.md
        task.toml
        environment/
          Dockerfile
          data/
        tests/
          test.sh
          ...complete approved verifier files...
```

Sanitization checklist:

- `instruction.md` explicitly says to save final files in
  `/workspace/output/`.
- `task.toml`, Dockerfile, and verifier use the same output location.
- For the approved external format, `task.toml` includes
  `artifacts = ["/workspace/output"]`.
- `storage_mb` is no higher than `10240`.
- `environment/data/` contains real input files, not only links.
- `tests/` contains the complete verifier supplied with the task.
- The verifier writes `verifier/reward.json`.
- Remove `solution/`, `outputs/`, reference answers, `.DS_Store`,
  `node_modules`, and temporary files.
- Text files are UTF-8 and contain no NUL bytes.
- Do not create `.harbor_package_ready` until after upload.

If the task does not match this format, stop and ask an engineer.

## 2. Upload the batch

Sign in and set the local ready-batch folder:

```powershell
gcloud auth login
gcloud config set project turing-delivery-apac-dev

$ReadyBatch = "D:\Turing\GDPVal\MY_BATCH\_harbor_ready"
$TaskIds = @(
  Get-ChildItem $ReadyBatch -Directory |
    ForEach-Object Name
)

"Tasks found: $($TaskIds.Count)"
```

Confirm the count, then upload the task directories:

```powershell
$TaskDirs = Get-ChildItem $ReadyBatch -Directory |
  ForEach-Object FullName

gcloud storage cp -r @TaskDirs `
  "gs://long-horizon-beta/tasks/" `
  --project turing-delivery-apac-dev
```

Only after upload succeeds, add the ready markers:

```powershell
$Marker = Join-Path $env:TEMP "harbor-ready-marker"
[System.IO.File]::WriteAllBytes($Marker, [byte[]] @())

foreach ($TaskId in $TaskIds) {
  gcloud storage cp $Marker `
    "gs://long-horizon-beta/tasks/$TaskId/v1/.harbor_package_ready" `
    --project turing-delivery-apac-dev
}
```

The enqueue cron must be suspended before this step. The marker name must be
exactly `.harbor_package_ready`.

## 3. Dry-run and start the eval

Fill in the approved app URL, `k`, and model list:

```powershell
$BaseUrl = "https://gdpval-worker-beta-pr-REPLACE.rd.atlas.turing.com"
$K = 1

$Models = @(
  @{
    name = "openai/gpt-5.6-sol"
    provider = "openai"
    reasoningEffort = "max"
  },
  @{
    name = "google/gemini-3.6-flash"
    provider = "google"
    reasoningEffort = "high"
  }
)

$ExpectedTrials = $TaskIds.Count * $Models.Count * $K
"Expected trials: $ExpectedTrials"
```

Other examples:

```powershell
# Opus 4.8 1m max + GPT-5.5 xhigh + Gemini 3.1 Pro high
$Models = @(
  @{
    name = "anthropic/claude-opus-4-8[1m]"
    provider = "claude"
    reasoningEffort = "max"
  },
  @{
    name = "openai/gpt-5.5"
    provider = "openai"
    reasoningEffort = "xhigh"
  },
  @{
    name = "google/gemini-3.1-pro-preview-customtools"
    provider = "google"
    reasoningEffort = "high"
  }
)

# GPT-5.5 xhigh
@{ name="openai/gpt-5.5"; provider="openai"; reasoningEffort="xhigh" }

# Claude Opus 4.7 max
@{ name="anthropic/claude-opus-4-7[1m]"; provider="claude"; reasoningEffort="max" }
```

Do not guess an unfamiliar model ID—get the exact object from the run owner.

Get the internal secret:

```powershell
$Secret = (
  gcloud secrets versions access latest `
    --secret gdpval_INTERNAL_WORKER_SECRET `
    --project turing-delivery-apac-dev |
  Out-String
).Trim()

$Headers = @{
  "X-Worker-Secret" = $Secret
  "Content-Type" = "application/json"
}
```

Dry-run:

```powershell
foreach ($TaskId in $TaskIds) {
  $Body = @{
    taskId=$TaskId
    k=$K
    models=$Models
    dryRun=$true
  } | ConvertTo-Json -Depth 8

  Invoke-RestMethod `
    -Method Post `
    -Uri "$BaseUrl/api/internal/harbor-enqueue-eval" `
    -Headers $Headers `
    -Body $Body
}
```

Every response must list the task under `enqueued` and leave
`skippedPending`/`skippedNoInput` empty.

If the dry run looks good and you want to proceed to the real run, do:

```powershell
$Runs = foreach ($TaskId in $TaskIds) {
  $Body = @{
    taskId=$TaskId
    k=$K
    models=$Models
    dryRun=$false
  } | ConvertTo-Json -Depth 8

  $Response = Invoke-RestMethod `
    -Method Post `
    -Uri "$BaseUrl/api/internal/harbor-enqueue-eval" `
    -Headers $Headers `
    -Body $Body

  [pscustomobject]@{
    task=$TaskId
    execution=$Response.execution
  }
}

$Runs | Export-Csv `
  (Join-Path $ReadyBatch "_eval-runs.csv") `
  -NoTypeInformation
```

Immediately remove the ready markers:

```powershell
foreach ($TaskId in $TaskIds) {
  gcloud storage rm `
    "gs://long-horizon-beta/tasks/$TaskId/v1/.harbor_package_ready" `
    --project turing-delivery-apac-dev 2>$null
}

Remove-Variable Secret, Headers -ErrorAction SilentlyContinue
```

## 4. Check progress and results

Set the batch prefix:

```powershell
$Prefix = "k1-0720"
```

Count status files:

```powershell
$Statuses = @(
  gcloud storage ls `
    "gs://long-horizon-evals-beta/evals/$Prefix-*/v1/execution_*/*/trial_*/trial_status/status.json" `
    --project turing-delivery-apac-dev 2>$null
)

"Status files: $($Statuses.Count) / $ExpectedTrials"
```

Check remaining pending tasks:

```powershell
$Pending = @(
  gcloud storage ls `
    "gs://long-horizon-evals-beta/pending/$Prefix-*/v1" `
    --project turing-delivery-apac-dev 2>$null
)

"Pending tasks: $($Pending.Count)"
```

Result location:

```text
gs://long-horizon-evals-beta/evals/<task-id>/v1/execution_<n>/<model>/trial_<n>/
```

The batch is ready to fetch when:

- status count equals expected trials;
- pending count is `0`; and
- every status has `send_to_retry = false`.

Read a status with:

```powershell
gcloud storage cat "<status-url>" |
  ConvertFrom-Json |
  Select-Object task_id, model_slug, trial, status, send_to_retry, reward
```

`healthy` is ready. Review `warning` or `accepted_by_verdict`. Escalate
`manual_review_required`, failures, missing trials, or `send_to_retry = true`.

## 5. Download and zip

Use the execution numbers saved during enqueue:

```powershell
$Runs = Import-Csv (Join-Path $ReadyBatch "_eval-runs.csv")
$Output = "D:\Turing\GDPVal\MY_BATCH_RESULTS"
New-Item -ItemType Directory -Force -Path $Output | Out-Null

foreach ($Run in $Runs) {
  $Destination = Join-Path $Output "$($Run.task)\v1"
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null

  gcloud storage cp -r `
    "gs://long-horizon-evals-beta/evals/$($Run.task)/v1/execution_$($Run.execution)" `
    $Destination `
    --project turing-delivery-apac-dev
}
```

Before delivery, confirm every downloaded trial:

- has `trial_status/status.json` with `send_to_retry = false`;
- has `job/.../verifier/reward.json`;
- has no top-level `job/result.json`; and
- contains the expected files under `artifacts/workspace/output/`.

Remove `node_modules`, then zip:

```powershell
Get-ChildItem $Output -Recurse -Directory -Filter node_modules |
  Remove-Item -Recurse -Force

$SevenZip = "$env:ProgramFiles\7-Zip\7z.exe"
$Zip = "D:\Turing\GDPVal\MY_BATCH_DELIVERY.zip"

& $SevenZip a -tzip -mx3 -mmt=on $Zip "$Output\*"
& $SevenZip t $Zip
```

Do not include secrets, `keys.csv`, temporary files, or a summary unless the
recipient asks for one.

## Cautions

- Dry-run first; real enqueue only after approval.
- Upload ready markers last and remove them immediately after enqueue.
- Never alter provider keys yourself.
- Never delete pending markers, purge queues, or kill pods.
- Never package a retrying or failed trial.
- When uncertain, stop and ask an engineer.
