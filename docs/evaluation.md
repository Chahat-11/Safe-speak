# SafeSpeak evaluation

Model: `qwen2.5:3b` on local Ollama, temperature 0. Code: commit `f70a9cf`.
Headline numbers come only from `data/test_real.csv` (463 real messages, never used for tuning).
Hard negatives (synthetic, all legitimate) are a separate robustness check, never merged into the headline.
Scam is the positive class; a verdict of scam or suspicious counts as flagged; uncertain counts as not flagged.
The three n40 runs use the same 40 messages, so they compare the architectures directly.
This file is regenerated with `python -m safespeak.report` as each run finishes; only finished runs are listed.

## Overview

| Run | Scored | Accuracy (95% CI) | Precision | Recall | F1 | False alarms | Uncertain | Errors | Mean s | p50 s | p95 s | Tokens/msg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| test_real_hierarchical_n40_seed0 | 40/40 | 95.0% (83.5%–98.6%) | 90.9% | 100.0% | 0.952 | 10.0% | 0 | 0 | 23.1 | 22.8 | 27.5 | 3366 |
| test_real_sequential_n40_seed0 | 40/40 | 97.5% (87.1%–99.6%) | 95.2% | 100.0% | 0.976 | 5.0% | 0 | 0 | 24.5 | 24.0 | 29.0 | 3403 |
| test_real_parallel_n40_seed0 | 40/40 | 97.5% (87.1%–99.6%) | 95.2% | 100.0% | 0.976 | 5.0% | 0 | 0 | 24.7 | 23.8 | 30.1 | 3403 |

## test_real_hierarchical_n40_seed0

| Agent | ms/message | LLM calls/message | Tokens/message |
|---|---|---|---|
| coordinator | 23100 | 0.00 | 0 |
| explainer | 6763 | 1.00 | 628 |
| reasoner | 6424 | 1.00 | 1349 |
| parser | 6322 | 1.00 | 715 |
| critic | 3425 | 1.00 | 663 |
| verifier | 137 | 0.03 | 11 |
| retrieval | 20 | 0.00 | 0 |
| pattern | 1 | 0.00 | 0 |
| router | 1 | 0.00 | 0 |
| correlation | 1 | 0.00 | 0 |

| Archetype | Messages | Correct | Accuracy |
|---|---|---|---|
| Courier_Legitimate | 2 | 2 | 100.0% |
| Courier_Scam | 4 | 4 | 100.0% |
| Digital_Arrest | 1 | 1 | 100.0% |
| Digital_Arrest_Legitimate | 2 | 2 | 100.0% |
| Echallan_Legitimate | 1 | 1 | 100.0% |
| Echallan_Scam | 1 | 1 | 100.0% |
| Electricity_Legitimate | 1 | 1 | 100.0% |
| Electricity_Scam | 5 | 5 | 100.0% |
| Job_Legitimate | 4 | 4 | 100.0% |
| Job_Scam | 2 | 2 | 100.0% |
| KYC_Legitimate | 4 | 2 | 50.0% |
| KYC_Suspension | 3 | 3 | 100.0% |
| Lottery_Legitimate | 1 | 1 | 100.0% |
| Lottery_Scam | 2 | 2 | 100.0% |
| Tax_Legitimate | 5 | 5 | 100.0% |
| Tax_Refund_Scam | 2 | 2 | 100.0% |

## test_real_sequential_n40_seed0

| Agent | ms/message | LLM calls/message | Tokens/message |
|---|---|---|---|
| coordinator | 24502 | 0.00 | 0 |
| reasoner | 8112 | 1.00 | 1383 |
| explainer | 7992 | 1.00 | 629 |
| critic | 4209 | 1.00 | 664 |
| parser | 4082 | 1.00 | 716 |
| verifier | 80 | 0.03 | 11 |
| retrieval | 19 | 0.00 | 0 |
| correlation | 1 | 0.00 | 0 |
| pattern | 1 | 0.00 | 0 |

| Archetype | Messages | Correct | Accuracy |
|---|---|---|---|
| Courier_Legitimate | 2 | 2 | 100.0% |
| Courier_Scam | 4 | 4 | 100.0% |
| Digital_Arrest | 1 | 1 | 100.0% |
| Digital_Arrest_Legitimate | 2 | 2 | 100.0% |
| Echallan_Legitimate | 1 | 1 | 100.0% |
| Echallan_Scam | 1 | 1 | 100.0% |
| Electricity_Legitimate | 1 | 1 | 100.0% |
| Electricity_Scam | 5 | 5 | 100.0% |
| Job_Legitimate | 4 | 4 | 100.0% |
| Job_Scam | 2 | 2 | 100.0% |
| KYC_Legitimate | 4 | 3 | 75.0% |
| KYC_Suspension | 3 | 3 | 100.0% |
| Lottery_Legitimate | 1 | 1 | 100.0% |
| Lottery_Scam | 2 | 2 | 100.0% |
| Tax_Legitimate | 5 | 5 | 100.0% |
| Tax_Refund_Scam | 2 | 2 | 100.0% |

## test_real_parallel_n40_seed0

| Agent | ms/message | LLM calls/message | Tokens/message |
|---|---|---|---|
| coordinator | 24648 | 0.00 | 0 |
| explainer | 8167 | 1.00 | 629 |
| reasoner | 8100 | 1.00 | 1383 |
| critic | 4294 | 1.00 | 664 |
| parser | 3975 | 1.00 | 716 |
| verifier | 84 | 0.03 | 11 |
| pattern | 21 | 0.00 | 0 |
| retrieval | 21 | 0.00 | 0 |
| correlation | 2 | 0.00 | 0 |

| Archetype | Messages | Correct | Accuracy |
|---|---|---|---|
| Courier_Legitimate | 2 | 2 | 100.0% |
| Courier_Scam | 4 | 4 | 100.0% |
| Digital_Arrest | 1 | 1 | 100.0% |
| Digital_Arrest_Legitimate | 2 | 2 | 100.0% |
| Echallan_Legitimate | 1 | 1 | 100.0% |
| Echallan_Scam | 1 | 1 | 100.0% |
| Electricity_Legitimate | 1 | 1 | 100.0% |
| Electricity_Scam | 5 | 5 | 100.0% |
| Job_Legitimate | 4 | 4 | 100.0% |
| Job_Scam | 2 | 2 | 100.0% |
| KYC_Legitimate | 4 | 3 | 75.0% |
| KYC_Suspension | 3 | 3 | 100.0% |
| Lottery_Legitimate | 1 | 1 | 100.0% |
| Lottery_Scam | 2 | 2 | 100.0% |
| Tax_Legitimate | 5 | 5 | 100.0% |
| Tax_Refund_Scam | 2 | 2 | 100.0% |
## Overview

| Run | Scored | Accuracy (95% CI) | Precision | Recall | F1 | False alarms | Uncertain | Errors | Mean s | p50 s | p95 s | Tokens/msg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| test_real_hierarchical_n40_seed0 | 40/40 | 95.0% (83.5%–98.6%) | 90.9% | 100.0% | 0.952 | 10.0% | 0 | 0 | 23.1 | 22.8 | 27.5 | 3366 |
| test_real_sequential_n40_seed0 | 40/40 | 97.5% (87.1%–99.6%) | 95.2% | 100.0% | 0.976 | 5.0% | 0 | 0 | 24.5 | 24.0 | 29.0 | 3403 |
| test_real_parallel_n40_seed0 | 40/40 | 97.5% (87.1%–99.6%) | 95.2% | 100.0% | 0.976 | 5.0% | 0 | 0 | 24.7 | 23.8 | 30.1 | 3403 |

## test_real_hierarchical_n40_seed0

| Agent | ms/message | LLM calls/message | Tokens/message |
|---|---|---|---|
| coordinator | 23100 | 0.00 | 0 |
| explainer | 6763 | 1.00 | 628 |
| reasoner | 6424 | 1.00 | 1349 |
| parser | 6322 | 1.00 | 715 |
| critic | 3425 | 1.00 | 663 |
| verifier | 137 | 0.03 | 11 |
| retrieval | 20 | 0.00 | 0 |
| pattern | 1 | 0.00 | 0 |
| router | 1 | 0.00 | 0 |
| correlation | 1 | 0.00 | 0 |

| Archetype | Messages | Correct | Accuracy |
|---|---|---|---|
| Courier_Legitimate | 2 | 2 | 100.0% |
| Courier_Scam | 4 | 4 | 100.0% |
| Digital_Arrest | 1 | 1 | 100.0% |
| Digital_Arrest_Legitimate | 2 | 2 | 100.0% |
| Echallan_Legitimate | 1 | 1 | 100.0% |
| Echallan_Scam | 1 | 1 | 100.0% |
| Electricity_Legitimate | 1 | 1 | 100.0% |
| Electricity_Scam | 5 | 5 | 100.0% |
| Job_Legitimate | 4 | 4 | 100.0% |
| Job_Scam | 2 | 2 | 100.0% |
| KYC_Legitimate | 4 | 2 | 50.0% |
| KYC_Suspension | 3 | 3 | 100.0% |
| Lottery_Legitimate | 1 | 1 | 100.0% |
| Lottery_Scam | 2 | 2 | 100.0% |
| Tax_Legitimate | 5 | 5 | 100.0% |
| Tax_Refund_Scam | 2 | 2 | 100.0% |

## test_real_sequential_n40_seed0

| Agent | ms/message | LLM calls/message | Tokens/message |
|---|---|---|---|
| coordinator | 24502 | 0.00 | 0 |
| reasoner | 8112 | 1.00 | 1383 |
| explainer | 7992 | 1.00 | 629 |
| critic | 4209 | 1.00 | 664 |
| parser | 4082 | 1.00 | 716 |
| verifier | 80 | 0.03 | 11 |
| retrieval | 19 | 0.00 | 0 |
| correlation | 1 | 0.00 | 0 |
| pattern | 1 | 0.00 | 0 |

| Archetype | Messages | Correct | Accuracy |
|---|---|---|---|
| Courier_Legitimate | 2 | 2 | 100.0% |
| Courier_Scam | 4 | 4 | 100.0% |
| Digital_Arrest | 1 | 1 | 100.0% |
| Digital_Arrest_Legitimate | 2 | 2 | 100.0% |
| Echallan_Legitimate | 1 | 1 | 100.0% |
| Echallan_Scam | 1 | 1 | 100.0% |
| Electricity_Legitimate | 1 | 1 | 100.0% |
| Electricity_Scam | 5 | 5 | 100.0% |
| Job_Legitimate | 4 | 4 | 100.0% |
| Job_Scam | 2 | 2 | 100.0% |
| KYC_Legitimate | 4 | 3 | 75.0% |
| KYC_Suspension | 3 | 3 | 100.0% |
| Lottery_Legitimate | 1 | 1 | 100.0% |
| Lottery_Scam | 2 | 2 | 100.0% |
| Tax_Legitimate | 5 | 5 | 100.0% |
| Tax_Refund_Scam | 2 | 2 | 100.0% |

## test_real_parallel_n40_seed0

| Agent | ms/message | LLM calls/message | Tokens/message |
|---|---|---|---|
| coordinator | 24648 | 0.00 | 0 |
| explainer | 8167 | 1.00 | 629 |
| reasoner | 8100 | 1.00 | 1383 |
| critic | 4294 | 1.00 | 664 |
| parser | 3975 | 1.00 | 716 |
| verifier | 84 | 0.03 | 11 |
| pattern | 21 | 0.00 | 0 |
| retrieval | 21 | 0.00 | 0 |
| correlation | 2 | 0.00 | 0 |

| Archetype | Messages | Correct | Accuracy |
|---|---|---|---|
| Courier_Legitimate | 2 | 2 | 100.0% |
| Courier_Scam | 4 | 4 | 100.0% |
| Digital_Arrest | 1 | 1 | 100.0% |
| Digital_Arrest_Legitimate | 2 | 2 | 100.0% |
| Echallan_Legitimate | 1 | 1 | 100.0% |
| Echallan_Scam | 1 | 1 | 100.0% |
| Electricity_Legitimate | 1 | 1 | 100.0% |
| Electricity_Scam | 5 | 5 | 100.0% |
| Job_Legitimate | 4 | 4 | 100.0% |
| Job_Scam | 2 | 2 | 100.0% |
| KYC_Legitimate | 4 | 3 | 75.0% |
| KYC_Suspension | 3 | 3 | 100.0% |
| Lottery_Legitimate | 1 | 1 | 100.0% |
| Lottery_Scam | 2 | 2 | 100.0% |
| Tax_Legitimate | 5 | 5 | 100.0% |
| Tax_Refund_Scam | 2 | 2 | 100.0% |

