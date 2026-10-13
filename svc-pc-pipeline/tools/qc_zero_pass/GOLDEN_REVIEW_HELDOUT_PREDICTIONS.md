# Held-out predictions: golden criterion review on QC batches 6, 8, 9 (written 2026-10-02, before any TFRL verdict for these batches was read)

Tool: `golden_criterion_review.py` (team repo branch golden-criterion-review-2026-10-02, commit 52b0392), run on 78 bundles that have at least one zero-pass criterion (651 criteria), 3 golden Opus passes plus 1 no-golden Opus pass, lanes a2 j w a5 b c d f g. Tiers: HOLD_AI = golden 2 of 3 AND no-golden pass say defect; READ_FIRST = golden 2 of 3 only. The rule and thresholds were fixed on batches 1 to 5 labels before this run. Raw outputs: the local analysis folder.

Bundles with a HOLD flag are predicted TFRL-rejectable; bundles with only READ_FIRST flags are predicted weaker. Score against TFRL verdicts when they arrive.

| Bundle | Zero-pass criteria | HOLD criteria | READ_FIRST criteria |
|---|---|---|---|
| b6__svc-pc-14-1-0 | 129 | j3a2, r-42b, r-42c1, r-42c2, r-42c3, r-42c4, r-42c5, r-42d1, r-42d2, r-42f1, r-42f2, r-42f3, j6v, j6w, j6y, j6z, j6aa, j6ab, j6ae, j6ah, j6ax, j6ay, j6az, j6ba, j6bb, j6bc, j6bd, j3ad, j3ae | j3a-02, j3a-04, j3a-05, j3a-07, j3a-08, j3a-10, j3h, r-33d3d, r-43v4, r-42g1, j6h, j6o, r-37e, r-37f, j6t, j6u, j6af, j6ag, j3w, j3u, j3x, j3y, j3aa, j3ab, j3ac, j3z, j3af, j3ag, j3ah |
| b6__svc-pc-25-4-0 | 29 | c20ag | c03b, c20u, c20ah, c20ai, c20aj |
| b6__svc-pc-53-0-0 | 8 | - | r007a |
| b6__svc-pc-58-10-0 | 7 | c20i19, c20h8 | c32 |
| b6__svc-pc-88-0-0 | 126 | jdg-02aa, jdg-02ap-q1, jdg-02ap-q2, jdg-02ap-q3, jdg-02ap-q4 | jdg-02al-rodriguez, jdg-02al-lee, jdg-02al-liu, jdg-02al-okafor, jdg-02o-kim, jdg-02o-adams, jdg-02o-johnson, jdg-02af-oct, jdg-02af-dec |
| b6__svc-pc-92-0-0 | 1 | - | r09b |
| b6__task_num-508-rewardkit | 12 | ebitda-build-2, coverage, coverage-8, maturity, maturity-12, no_fabrication | ebitda-build-nci, provenance-22, ebitda-build-28, no-fabrication-36 |
| b8__601 | 6 | - | pue-choice, gs5-exposure |
| b8__eng-104 | 1 | - | v16c-memo-blocked |
| b8__eng-108 | 1 | qa-hypothesis | - |
| b8__fin-237 | 1 | - | v8a |
| b8__fin-340 | 26 | v19, v27e_fy2000, v27f_fy2001 | v4, v5, v7, v14a, v14b, v14c, v23, v21a, v27g_availability, v27h_debt |
| b8__fin-375 | 2 | v16 | - |
| b8__num-601 | 6 | - | pue-choice, gs5-exposure, yield-cost-base, memo-yield |
| b8__phr-156 | 5 | epst-11 | epst-18, epst-19 |
| b8__phr-164 | 2 | governance | retention-20 |
| b8__sco-226 | 1 | - | v28-c28-wb-late-attribution-reconciled |
| b8__sco-232 | 1 | v11c-execution-vendor-followup | - |
| b8__sco-239 | 13 | v1-financial, v26d-financial, v19g-financial | - |
| b8__svc-pc-67-2-0 | 10 | r009g | - |
| b8__task_eng-108 | 1 | qa-hypothesis | - |
| b8__task_fin-237 | 1 | v8a | - |
| b8__task_fin-340 | 26 | v19, v21a, v27e_fy2000, v27f_fy2001 | v4, v5, v7, v14a, v14b, v14c, v23, v27g_availability, v27h_debt |
| b8__task_fin-375 | 2 | - | v16 |
| b8__task_phr-156 | 5 | epst-11, epst-17, epst-18 | epst-19 |
| b8__task_phr-164 | 2 | governance | retention-20 |
| b9__419 | 2 | - | unresolved-performance-allocation |
| b9__fin-273 | 1 | post-cure-capex-condition | - |
| b9__fin-452 | 8 | wb_l2_entitlement | - |
| b9__svc-pc-26-7-0 | 7 | - | e2g |
| b9__svc-pc-77-0-0 | 21 | c04p, c04q, c04r | - |
| b9__task_436 | 1 | - | communication |

Bundles with no flag: b6__hlt-214, b6__mkt-112, b6__svc-pc-31-4-0, b6__svc-pc-33-2-0, b6__svc-pc-37-5-0, b6__svc-pc-42-3-0, b6__svc-pc-72-3-0, b6__svc-pc-73-2-0, b6__svc-pc-73-3-0, b6__svc-pc-77-0-0, b6__svc-pc-8-7-0, b6__task_pump-procurement-nitration-spent-acid, b6__task_sco-136, b6__task_sco-142, b6__task_sco-269, b8__fin-311, b8__fin-404, b8__lgl-131, b8__mkt-162, b8__mkt-188, b8__phr-154, b8__sco-198, b8__sco-206, b8__sco-237, b8__svc-pc-24-4-0, b8__svc-pc-93-5-0, b8__task_fin-404, b8__taskid-mkt-188, b8__taskid-phr-154, b9__436, b9__454, b9__478, b9__fin-206, b9__mkt-188, b9__num-483, b9__phr-118, b9__phr-136, b9__phr-137, b9__sco-143, b9__task_419, b9__task_454, b9__task_478, b9__taskid-fin-363, b9__taskid-mkt-188, b9__taskid-num-483, b9__taskid-phr-137_dataos_upload

Totals: 78 bundles, 651 zero-pass criteria, 70 HOLD criteria in 21 bundles, 87 READ_FIRST criteria, 32 bundles with any flag.

## Cross-check against the internal review of the same batches (RAN 2026-10-02, before TFRL verdicts exist)

Internal reviews exist for 94 tasks in batches 6, 8, 9 (19 rejected, 75 passed). Of the 78 bundles: HOLD flag on 21: 10 internal-rejected, 10 internal-passed, 1 no internal verdict. READ_FIRST only on 11: 4 internal-rejected, 5 internal-passed, 2 none. No flag on 46: 2 internal-rejected, 36 internal-passed, 8 none. So HOLD agrees with an internal rejection on 10 of 20 and adds 10 tasks the internal review passed (b6: svc-pc-14-1-0, svc-pc-25-4-0, svc-pc-58-10-0, svc-pc-88-0-0; b8: phr-156 (two versions), sco-232, svc-pc-67-2-0, fin-237; b9: svc-pc-77-0-0), the incremental reading list. Of the 19 internal rejections, HOLD or READ_FIRST flags 14 and 2 are unflagged (3 have no zero-pass criteria in the staged bundles). This is agreement between two of our reviews, not accuracy: TFRL verdicts decide.
