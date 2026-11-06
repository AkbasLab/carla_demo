# Phase 17 development validation evidence

Both replay pilot batches are preserved, including the first batch that exposed invalid route lengths. These are software/methodology pilots, not actual-model or live-flight results. The software verification summary records 246 passing tests.

The original raw batches total approximately 1.1 GB. To keep the repository practical, their complete file trees are preserved in losslessly compressed ZIP archives split into 2 MiB parts under `evidence/`. The archive index records SHA256 checksums for every part and complete archive, original file counts and uncompressed sizes. No failed case was omitted.

Reports, timeline PNGs, batch definitions, fixtures, manifests, summaries, arrivals and evaluated metrics are also available as ordinary browsable files. Complete raw message, telemetry, policy and JSONL event logs are inside the archives.

Verify an archive without extracting:

```bash
python results/phase17/restore_evidence.py --batch validation_run2
```

Restore into a fresh directory and inspect/rebuild all individual plots:

```bash
python results/phase17/restore_evidence.py \
  --batch validation_run2 \
  --output-dir /tmp/phase17_validation_run2_restored

python scripts/run_phase17_pilots.py analyze \
  --pilot-dir /tmp/phase17_validation_run2_restored
```

Use `validation_run1` for the earlier unsuccessful batch. The restore tool validates part/combined hashes and archive CRCs before extraction and refuses to overwrite a nonempty directory. Restoring logs does not rerun an experiment. Preserve the original pilot files rather than rerunning into these existing result directories.

The original manifests retain their actual working-tree provenance and original path strings. Archives preserve those records unchanged; they do not retroactively claim a clean checkout of the publication commit.
