# SVC-PC full-corpus DVC pointer

`data.dvc` + `.dvc/config` here are the DVC pointer + remote config for the
shared "Cirrus Sleep Full Y1 (FINAL VERSION)" corpus (1181 files, ~57MB),
pushed to `gs://colab-bench` per the platform's documented large-file
mechanism (https://data-os.turing.com/docs/dvc-large-files).

Every SVC-PC task whose prompt expects the agent to explore the whole shared
corpus (rather than a short list of named files `hydrate_environment.py` can
resolve) ships these same two small files instead of the corpus itself.
`assemble_task.py --dvc-fullcorpus` copies them in automatically; from there
`to_rewardkit.py` detects `environment/.dvc/config` + `environment/data.dvc`
in the source harbor task and injects the `dvc pull` Dockerfile block
(declaring the exact `ARG COLAB_BENCH_BUCKET_TOKEN_JSON` the platform
requires to route the build to Modal, which is the only environment that
gets the GCS credential injected — a task built on Daytona instead has no
route to the bucket at all).

Content is identical across every task that uses it (same corpus, so DVC's
content-addressed hash is the same) — pushed once, reused everywhere. No
per-task `dvc add`/`dvc push` needed.

## If the corpus changes

Re-run the real steps from a checkout of the corpus folder (needs
`gs://colab-bench` write access — see the doc above):

```bash
mkdir -p /tmp/svc_corpus_dvc/environment/data
cp -R "<updated corpus folder>"/* /tmp/svc_corpus_dvc/environment/data/
cd /tmp/svc_corpus_dvc/environment
pip install "dvc[gs]==3.67.1"
dvc init --no-scm
dvc remote add -d colab-bench gs://colab-bench
dvc add data
dvc push
rm -rf .dvc/cache .dvc/tmp data
```

Then copy the resulting `data.dvc` and `.dvc/config` over the ones in this
directory. Every task built with `assemble_task.py --dvc-fullcorpus` after
that picks up the new pointer automatically on its next `cycle.py bundle` /
`svc_pc_batch_convert.py` run.

## Verified (2026-08-27)

- `dvc push` from a real copy of the corpus: 1179 files pushed.
- `dvc pull` using only this directory's `data.dvc` + `.dvc/config` in a
  clean scratch dir: 1180 files fetched, 1181 added, structure matched the
  source corpus exactly.
- Not yet verified: an actual Modal build consuming `COLAB_BENCH_BUCKET_TOKEN_JSON`
  end-to-end (the local pull proves the bucket/pointer are correct, not the
  platform's credential-injection path).
