# Pending calibration cases

These are generated configurations, not executed results. Each file contains two original cases, retaining the 600-second budget and old runtime/V2-disabled configuration. Only missing or interrupted cases are listed; no finished unsuccessful case is rerun.

Inspect one batch before scheduling the next. Keep outputs separate and preserve each attempt.

| Batch | Cases |
|---|---|
| [batch_01.json](batch_01.json) | C_n4_nominal_control_s42, C_n4_nominal_loss_s42 |
| [batch_02.json](batch_02.json) | C_n4_severe_control_s42, C_n4_severe_loss_s42 |
| [batch_03.json](batch_03.json) | D_n2_nominal_control_s42, D_n2_nominal_loss_s42 |
| [batch_04.json](batch_04.json) | D_n2_severe_control_s42, D_n2_severe_loss_s42 |
| [batch_05.json](batch_05.json) | D_n4_nominal_control_s42, D_n4_nominal_loss_s42 |
| [batch_06.json](batch_06.json) | D_n4_severe_control_s42, D_n4_severe_loss_s42 |
| [batch_07.json](batch_07.json) | C_n2_nominal_control_s43, C_n2_nominal_loss_s43 |
| [batch_08.json](batch_08.json) | C_n2_severe_control_s43, C_n2_severe_loss_s43 |
| [batch_09.json](batch_09.json) | C_n4_nominal_control_s43, C_n4_nominal_loss_s43 |
| [batch_10.json](batch_10.json) | C_n4_severe_control_s43, C_n4_severe_loss_s43 |
| [batch_11.json](batch_11.json) | D_n2_nominal_control_s43, D_n2_nominal_loss_s43 |
| [batch_12.json](batch_12.json) | D_n2_severe_control_s43, D_n2_severe_loss_s43 |
| [batch_13.json](batch_13.json) | D_n4_nominal_control_s43, D_n4_nominal_loss_s43 |
| [batch_14.json](batch_14.json) | D_n4_severe_control_s43, D_n4_severe_loss_s43 |

First batch:

```bash
python -u scripts/run_phase14_experiments.py \
  --batch results/phase17/main_calibration_run1/pending_batches/batch_01.json \
  --output-dir results/phase17/main_calibration_pending_run1/batch_01 \
  --evaluate
```

Do not launch all batches to try to repair known recovery defects. These complete the existing cohort; a V2 configuration requires separately declared calibration.
