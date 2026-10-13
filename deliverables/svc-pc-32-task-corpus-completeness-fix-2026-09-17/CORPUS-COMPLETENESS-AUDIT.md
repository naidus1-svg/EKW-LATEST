# SVC-PC corpus-completeness audit, 2026-09-17

Scope: find SVC-PC tasks whose `_corpus_subtree/` is missing an entire top-level corpus
category that the task's own judge.toml / golden / instruction.md text references, when the
real full corpus (Cirrus Sleep Full Y1 FINAL VERSION) has that category. Same defect shape as
SVC-PC-19-0-0 (Accounting subtree absent, golden cited bank statements and trial balance).

Audit only. No live task files were modified or copied.

## 1. Definitive category list (real shared corpus)

Source of truth: `C:\ekwqc\cirrus-corpus-fetch\extracted\Cirrus Sleep Full Y1 (FINAL VERSION)\Company Shared Drive\`.
Immediate children (excluding .DS_Store):

| Company Shared Drive category | Immediate children |
|---|---|
| Accounting | 2021, Policies |
| All-Hands | 2021 |
| Board | Annual_Review, Governance, Investor_Relations, Meetings |
| Customer_Support | 2021, Playbooks |
| Finance | 2021, plus two FY2021 analysis docs |
| HR | Benefits, Onboarding, Org_Charts, Policies, _Restricted |
| Legal | many policy/COI/insurance PDFs and Compliance/Corporate/Tax subfolders |
| Marketing | 2021, Brand, Campaigns, Customers, Performance, Planning, Product, Results |
| Operations | 2021, IT, Policies_SOPs, Shipping, plus FY2021/FY2022 ops docs |
| Vendors | ADP, Apex_Logistics, Benefits_Carriers, BrightMark, CloudHost, NovaTex, Shopify, Stripe, SwiftShip_Express, Vendor_Master_List.xlsx |

10 Company Shared Drive categories total. Plus 15 per-person "My Drive - <person>" folders
(the corpus folder name uses an em dash; shown here with a hyphen): aisha.johnson,
alice.chen, brian.chang, david.nguyen, elena.torres, james.okafor, jessica.liu, kevin.wright,
laura.martinez, marcus.rivera, michelle.adams, priya.patel, ryan.park, sarah.kim, tom.baker.
Plus a top-level "System Exports - 2021Q4" folder (quickbooks, shopify, workday exports).

This audit's term/reference check covers the six Company Shared Drive categories named in the
task brief: Accounting, Finance, HR, Operations, Customer_Support, Vendors. All-Hands, Board,
Legal, and Marketing are present in the corpus but no reference-term list was supplied for
them, so absence is recorded but not flagged. System Exports is a separate hydration unit,
not a Company Shared Drive category; see the System Exports note below.

## 2. Method and coverage

Population: `pipeline/data/svc_pc_qc/03_dataos_ready/` holds 609 entries; 600 are task
directories (the other 9 are staging zip/manifest files, not tasks). All 600 task
directories were enumerated.

Per task I listed the immediate children of
`environment/initial_workspace/_corpus_subtree/` and parsed the hydration convention (three
variants exist, see below). For each task I read its instruction.md, tests/task_prompt.txt,
every tests/deliverables_*/judge.toml, and every golden .docx/.xlsx (Office XML text
extracted), then searched the absent categories for the reference terms AND for the
specific filenames that live in each category's real corpus folder.

A task is flagged only when BOTH hold: (a) a Company Shared Drive category is absent from its
`_corpus_subtree`, and (b) its own text cites at least one specific file that lives only in
that absent category's corpus folder (or, for Vendors, cites executed-MSA section numbers
whose MSA document lives only in Vendors). Concept-only matches (e.g. the word "payroll" or
"trial balance") were NOT treated as confirmed, because those artifacts often live in a
present category or in System Exports, not in the absent Company Shared Drive folder
(documented below).

## 3. Hydration conventions found

| Convention | Tasks | Category presence read from |
|---|---|---|
| split: child folders named `Company Shared Drive__<Category>` | 424 | the `<Category>` suffix |
| whole: a single `Company Shared Drive` folder with categories inside | 36 | its immediate children |
| none: subtree has only My Drive / System Exports, no Company Shared Drive | 2 | (no Company Shared Drive at all) |
| no `_corpus_subtree` folder | 138 | (different hydration model, see section 7) |

All 32 confirmed defects use the split convention, so each fix is a straight copy of the
missing `Company Shared Drive__<Category>` folder, byte-identical from the corpus, matching
the recipe already used for SVC-PC-19-0-0 (see deliverables/svc-pc-19-0-0-corpus-fix-2026-09-17).

## 4. Confirmed hydration gaps (32 tasks, 40 missing category instances)

Each row: the task's own text cites the named files, the category is absent, and the named
files exist in the real corpus (paths verified). Fix = copy the whole category folder into
`_corpus_subtree/` as `Company Shared Drive__<Category>`.

| Task | Missing category | Specific files/sections the task text cites | Real files available to copy (in corpus) |
|---|---|---|---|
| SVC-PC-14-2-0 | HR | Year_End_Headcount_Report, Option_Grant_Sarah_Kim, Year_End_Comp_Summary | .../HR/_Restricted/Compensation/Year_End_Headcount_Report.xlsx; .../HR/_Restricted/003_Sarah_Kim/Equity/Option_Grant_Sarah_Kim.pdf; .../HR/_Restricted/Compensation/Year_End_Comp_Summary.xlsx |
| SVC-PC-14-2-0 | Operations | Q4_Inventory_Snapshot | .../Operations/2021/Q4/Inventory/Q4_Inventory_Snapshot.xlsx |
| SVC-PC-14-2-0 | Vendors | Vendor_Master_List, MSA_SwiftShip_2021, MSA_NovaTex_2021, MSA_Apex_2021 | .../Vendors/Vendor_Master_List.xlsx; .../Vendors/SwiftShip_Express/Contracts/MSA_SwiftShip_2021.pdf; .../Vendors/NovaTex/Contracts/MSA_NovaTex_2021.pdf; .../Vendors/Apex_Logistics/Contracts/MSA_Apex_2021.pdf |
| SVC-PC-19-0-0 | Vendors | Annual_Processing_Summary | .../Vendors/Stripe/Statements/2021/Annual_Processing_Summary.pdf |
| SVC-PC-19-2-0 | Vendors | Service_Agreement_CloudHost, Merchant_Agreement_Stripe, Vendor_Agreement_Shopify, SOW_BrightMark_Launch, Vendor_Agreement_ADP, Rate_Card_Apex_2021, Vendor_Master_List, MSA_SwiftShip_2021, MSA_NovaTex_2021, MSA_Apex_2021 | .../Vendors/CloudHost/Contracts/Service_Agreement_CloudHost.pdf; .../Vendors/Stripe/Contracts/Merchant_Agreement_Stripe.pdf; .../Vendors/Shopify/Contracts/Vendor_Agreement_Shopify.pdf; .../Vendors/BrightMark/SOW_BrightMark_Launch.pdf; .../Vendors/ADP/Contracts/Vendor_Agreement_ADP.pdf; .../Vendors/Apex_Logistics/Contracts/Rate_Card_Apex_2021.xlsx; .../Vendors/Vendor_Master_List.xlsx; .../Vendors/SwiftShip_Express/Contracts/MSA_SwiftShip_2021.pdf; .../Vendors/NovaTex/Contracts/MSA_NovaTex_2021.pdf; .../Vendors/Apex_Logistics/Contracts/MSA_Apex_2021.pdf |
| SVC-PC-19-5-0 | Accounting | AR_Aging_2021-12 | .../Accounting/2021/AR_Aging/AR_Aging_2021-12.xlsx |
| SVC-PC-19-5-0 | Vendors | Merchant_Agreement_Stripe, Annual_Processing_Summary | .../Vendors/Stripe/Contracts/Merchant_Agreement_Stripe.pdf; .../Vendors/Stripe/Statements/2021/Annual_Processing_Summary.pdf |
| SVC-PC-19-6-0 | Accounting | Bank_Statement_2021-10, Bank_Statement_2021-11, Year_End_Trial_Balance, AP_Aging_2021-12, AR_Aging_2021-12 | .../Accounting/2021/Bank_Statements/Bank_Statement_2021-10.pdf; .../Accounting/2021/Bank_Statements/Bank_Statement_2021-11.pdf; .../Accounting/2021/Year_End/Year_End_Trial_Balance.xlsx; .../Accounting/2021/AP_Aging/AP_Aging_2021-12.xlsx; .../Accounting/2021/AR_Aging/AR_Aging_2021-12.xlsx |
| SVC-PC-19-7-0 | Vendors | Merchant_Agreement_Stripe | .../Vendors/Stripe/Contracts/Merchant_Agreement_Stripe.pdf |
| SVC-PC-2-3-0 | Operations | Apex_Delay_Incident_Report | .../Operations/2021/Q3/Vendor_Management/Apex_Delay_Incident_Report.docx |
| SVC-PC-2-3-0 | Vendors | Apex_Year_End_SLA_Review | .../Vendors/Apex_Logistics/Reviews/Apex_Year_End_SLA_Review.docx |
| SVC-PC-2-5-0 | Finance | Year_1_KPI_Report | .../Finance/2021/Annual/Year_1_KPI_Report.xlsx |
| SVC-PC-24-4-0 | Vendors | golden cites NovaTex MSA 9.1/9.2 and QSA 8 (chargeback/warranty recourse) (evidence: MSA section cites; the MSA docs live only in Vendors) | MSA_NovaTex_2021.pdf, MSA_Apex_2021.pdf, Apex_Year_End_SLA_Review.docx, Vendor_Master_List.xlsx (full Vendors folder) |
| SVC-PC-26-0-0 | Accounting | Year_End_Adjusting_Entries, Accounting_Policies_Manual, Q4_Bank_Reconciliation, Year_End_Trial_Balance, AP_Aging_2021-12 | .../Accounting/2021/Year_End/Year_End_Adjusting_Entries.xlsx; .../Accounting/Policies/Accounting_Policies_Manual.pdf; .../Accounting/2021/Q4/Reconciliations/Q4_Bank_Reconciliation.xlsx; .../Accounting/2021/Year_End/Year_End_Trial_Balance.xlsx; .../Accounting/2021/AP_Aging/AP_Aging_2021-12.xlsx |
| SVC-PC-26-0-0 | HR | 2022_Benefits_Broker_Quote_Woodruff_Sawyer, 2022_401k_Plan_Design_Guideline, Hiring_Plan_2021, Comp_Bands_2021 | .../HR/Benefits/2022_Benefits_Broker_Quote_Woodruff_Sawyer.xlsx; .../HR/Benefits/2022_401k_Plan_Design_Guideline.docx; .../HR/_Restricted/Recruiting/Hiring_Plan_2021.xlsx; .../HR/_Restricted/Compensation/Comp_Bands_2021.xlsx |
| SVC-PC-26-0-0 | Vendors | Vendor_Master_List | .../Vendors/Vendor_Master_List.xlsx |
| SVC-PC-26-3-0 | Vendors | SOW_BrightMark_Launch, Q1_Campaign_Report | .../Vendors/BrightMark/SOW_BrightMark_Launch.pdf; .../Vendors/BrightMark/Q1_Campaign_Report.pdf |
| SVC-PC-3-5-0 | Vendors | Vendor_Master_List | .../Vendors/Vendor_Master_List.xlsx |
| SVC-PC-33-5-0 | Finance | Year_1_KPI_Report, Q4_KPI_Dashboard | .../Finance/2021/Annual/Year_1_KPI_Report.xlsx; .../Finance/2021/Q4/KPIs/Q4_KPI_Dashboard.xlsx |
| SVC-PC-33-7-0 | Finance | Year_1_KPI_Report | .../Finance/2021/Annual/Year_1_KPI_Report.xlsx |
| SVC-PC-35-0-0 | Vendors | Rate_Card_Apex_2021, MSA_SwiftShip_2021 | .../Vendors/Apex_Logistics/Contracts/Rate_Card_Apex_2021.xlsx; .../Vendors/SwiftShip_Express/Contracts/MSA_SwiftShip_2021.pdf |
| SVC-PC-42-0-0 | Vendors | Apex_Year_End_SLA_Review | .../Vendors/Apex_Logistics/Reviews/Apex_Year_End_SLA_Review.docx |
| SVC-PC-42-5-0 | Vendors | golden cites NovaTex MSA 4.1/4.2 (cost-change adjustment, FOB destination) (evidence: MSA section cites; the MSA docs live only in Vendors) | MSA_NovaTex_2021.pdf, MSA_Apex_2021.pdf, Apex_Year_End_SLA_Review.docx, Vendor_Master_List.xlsx (full Vendors folder) |
| SVC-PC-42-7-0 | Vendors | golden cites executed NovaTex MSA 2.3/3.1/3.2/4.2 and Apex SLA Review 2 (evidence: MSA section cites; the MSA docs live only in Vendors) | MSA_NovaTex_2021.pdf, MSA_Apex_2021.pdf, Apex_Year_End_SLA_Review.docx, Vendor_Master_List.xlsx (full Vendors folder) |
| SVC-PC-53-2-0 | Accounting | Payroll_Register_2021-12 | .../Accounting/2021/Payroll/Payroll_Register_2021-12.xlsx |
| SVC-PC-53-2-0 | HR | Comp_Bands_2021 | .../HR/_Restricted/Compensation/Comp_Bands_2021.xlsx |
| SVC-PC-53-2-0 | Operations | FY2022 Ops Capacity & Headcount Plan ($4-5M, 20-22 FTE) (final) | .../Operations/FY2022 Ops Capacity & Headcount Plan ($4-5M, 20-22 FTE) (final).doc |
| SVC-PC-58-0-0 | Vendors | golden cites NovaTex MSA (Net-30, capacity, landed cost) and Apex rate card (evidence: MSA section cites; the MSA docs live only in Vendors) | MSA_NovaTex_2021.pdf, MSA_Apex_2021.pdf, Apex_Year_End_SLA_Review.docx, Vendor_Master_List.xlsx (full Vendors folder) |
| SVC-PC-58-3-0 | Accounting | Fixed_Asset_Depreciation, Year_End_Trial_Balance, 1099_Summary | .../Accounting/2021/Year_End/Fixed_Asset_Depreciation.xlsx; .../Accounting/2021/Year_End/Year_End_Trial_Balance.xlsx; .../Accounting/2021/Year_End/1099_Summary.xlsx |
| SVC-PC-58-5-0 | Accounting | 1099_Summary | .../Accounting/2021/Year_End/1099_Summary.xlsx |
| SVC-PC-58-8-0 | Vendors | Apex_Year_End_SLA_Review | .../Vendors/Apex_Logistics/Reviews/Apex_Year_End_SLA_Review.docx |
| SVC-PC-59-0-0 | Vendors | Vendor_Agreement_Shopify, Vendor_Master_List, MSA_SwiftShip_2021, MSA_NovaTex_2021, MSA_Apex_2021 | .../Vendors/Shopify/Contracts/Vendor_Agreement_Shopify.pdf; .../Vendors/Vendor_Master_List.xlsx; .../Vendors/SwiftShip_Express/Contracts/MSA_SwiftShip_2021.pdf; .../Vendors/NovaTex/Contracts/MSA_NovaTex_2021.pdf; .../Vendors/Apex_Logistics/Contracts/MSA_Apex_2021.pdf |
| SVC-PC-62-4-0 | Vendors | Merchant_Agreement_Stripe, Vendor_Agreement_Shopify | .../Vendors/Stripe/Contracts/Merchant_Agreement_Stripe.pdf; .../Vendors/Shopify/Contracts/Vendor_Agreement_Shopify.pdf |
| SVC-PC-62-5-0 | Vendors | Vendor_Master_List | .../Vendors/Vendor_Master_List.xlsx |
| SVC-PC-62-6-0 | Customer_Support | Returns_Policy_Customer_Facing, Q3_Top_Issues_Summary, Q4_Top_Issues_Summary, Refund_Decision_Tree | .../Customer_Support/Playbooks/Returns_Policy_Customer_Facing.docx; .../Customer_Support/2021/Q3/Reports/Q3_Top_Issues_Summary.docx; .../Customer_Support/2021/Q4/Reports/Q4_Top_Issues_Summary.docx; .../Customer_Support/Playbooks/Refund_Decision_Tree.docx |
| SVC-PC-8-4-0 | Operations | Q4_Fulfillment_Metrics | .../Operations/2021/Q4/Fulfillment/Q4_Fulfillment_Metrics.xlsx |
| SVC-PC-8-5-0 | Finance | Q4_KPI_Dashboard | .../Finance/2021/Q4/KPIs/Q4_KPI_Dashboard.xlsx |
| SVC-PC-81-3-0 | Finance | Q4_Management_Accounts, Year_1_Annual_PnL | .../Finance/2021/Q4/Close_Package/Q4_Management_Accounts.xlsx; .../Finance/2021/Annual/Year_1_Annual_PnL.xlsx |
| SVC-PC-93-2-0 | Vendors | Rate_Card_Apex_2021, Vendor_Master_List, Quality_Standards, MSA_Apex_2021 | .../Vendors/Apex_Logistics/Contracts/Rate_Card_Apex_2021.xlsx; .../Vendors/Vendor_Master_List.xlsx; .../Vendors/NovaTex/Contracts/Quality_Standards.pdf; .../Vendors/Apex_Logistics/Contracts/MSA_Apex_2021.pdf |
| SVC-PC-93-5-0 | Vendors | Vendor_Master_List | .../Vendors/Vendor_Master_List.xlsx |

Gaps by category: Vendors 21, Accounting 6, Finance 5, Operations 4, HR 3, Customer_Support 1.

Notes on the four Vendors rows marked "MSA section cites" (SVC-PC-24-4-0, -42-5-0, -42-7-0,
-58-0-0): the golden cites NovaTex MSA section numbers (for example "MSA 4.1", "MSA 9.2") as
the basis for a cost-change, warranty, or recourse claim. The executed NovaTex/Apex MSAs and
the Apex Year-End SLA Review live only in `Company Shared Drive/Vendors/`, which is absent,
so the agent cannot read the sections the golden relies on. Same defect shape, evidenced by
section cites instead of full filenames.

SVC-PC-19-0-0 itself reappears here with a Vendors gap (Annual_Processing_Summary.pdf, which
lives in `Vendors/Stripe/Statements/2021/`). Its known Accounting gap was already fixed and is
now present; this Vendors gap is a second, unfixed instance on the same task.

## 5. Rejected candidates (looked like gaps, were not)

- SVC-PC-80-7-0, Customer_Support: the only match was the stem `_conv_test`, a test stub
  that physically sits in `Customer_Support/2021/Annual/...`. The golden mentions it as a
  "Finance folder" catalog stub, not as a Customer_Support source. Coincidental. Not a gap.
- SVC-PC-26-5-0, Finance: its judge.toml explicitly lists `Financial_Model_v1` and
  `Year_2_Budget_Planning` as "outside scope". The task excludes them. Not a gap.
- SVC-PC-73-1-0, Finance: the golden says of `Year_2_Budget_Approved`, "the file ... says on
  its own first page that it is not approved. Ignored it." Not a grounding need. (Its
  Operations reference is real but the task has no Company Shared Drive at all; see section 6.)

## 6. No Company Shared Drive at all (2 tasks, different shape)

Two tasks have a `_corpus_subtree` that contains only My Drive folders, with no Company
Shared Drive category present:

| Task | Present | Own text references |
|---|---|---|
| SVC-PC-10-5-0 | none (1 My Drive) | not individually verified |
| SVC-PC-73-1-0 | none (2 My Drives) | Operations: Q4_Demand_Planning (used as a figure source); Finance: Year_2_Budget_Approved (golden says "ignored it") |

These are a different, more severe shape (the entire Company Shared Drive is missing from the
subtree), not the single-category gap this audit targets. They need separate triage: the fix
scope is the whole Company Shared Drive (or a deliberate subset), not one category folder.

## 7. No `_corpus_subtree` at all (138 tasks, different hydration model)

138 of 600 tasks have no `_corpus_subtree` folder. Spot-checks (SVC-PC-1-7-0, SVC-PC-12-0-0,
SVC-PC-12-1-0) show these tasks hydrate the working set a different way: the relevant corpus
files are placed as flat files directly in `environment/initial_workspace/` (and sometimes an
`L1-00-00/` subfolder), not via a per-category subtree. So "no _corpus_subtree" is not
automatically a broken hydration; it is a structurally different population. Whether each
flat-file working set is complete is a separate audit that this run did not perform.

Per the brief these are flagged separately and not conflated with the single-category gaps.
Full list (138):

```
SVC-PC-1-7-0
SVC-PC-12-0-0
SVC-PC-12-1-0
SVC-PC-12-3-0
SVC-PC-12-5-0
SVC-PC-12-6-0
SVC-PC-13-0-0
SVC-PC-13-3-0
SVC-PC-13-4-0
SVC-PC-13-6-0
SVC-PC-13-7-0
SVC-PC-14-6-0
SVC-PC-15-5-0
SVC-PC-16-2-0
SVC-PC-16-3-0
SVC-PC-17-0-0
SVC-PC-17-2-0
SVC-PC-20-0-0
SVC-PC-20-1-0
SVC-PC-20-3-0
SVC-PC-20-4-0
SVC-PC-20-5-0
SVC-PC-20-7-0
SVC-PC-20-8-0
SVC-PC-22-0-0
SVC-PC-3-0-0
SVC-PC-35-3-0
SVC-PC-36-0-0
SVC-PC-38-4-0
SVC-PC-40-0-0
SVC-PC-41-0-0
SVC-PC-44-1-0
SVC-PC-45-1-0
SVC-PC-45-8-0
SVC-PC-46-0-0
SVC-PC-46-1-0
SVC-PC-46-3-0
SVC-PC-47-0-0
SVC-PC-47-1-0
SVC-PC-47-2-0
SVC-PC-47-3-0
SVC-PC-47-4-0
SVC-PC-47-5-0
SVC-PC-47-6-0
SVC-PC-47-7-0
SVC-PC-47-8-0
SVC-PC-49-5-0
SVC-PC-5-1-0
SVC-PC-53-0-0
SVC-PC-54-1-0
SVC-PC-54-2-0
SVC-PC-54-3-0
SVC-PC-54-4-0
SVC-PC-59-1-0
SVC-PC-59-2-0
SVC-PC-59-4-0
SVC-PC-59-5-0
SVC-PC-59-6-0
SVC-PC-6-0-0
SVC-PC-6-6-0
SVC-PC-6-7-0
SVC-PC-6-8-0
SVC-PC-60-0-0
SVC-PC-60-2-0
SVC-PC-60-3-0
SVC-PC-60-4-0
SVC-PC-60-5-0
SVC-PC-60-6-0
SVC-PC-66-5-0
SVC-PC-67-0-0
SVC-PC-67-1-0
SVC-PC-67-2-0
SVC-PC-67-3-0
SVC-PC-67-4-0
SVC-PC-68-0-0
SVC-PC-68-1-0
SVC-PC-68-2-0
SVC-PC-68-3-0
SVC-PC-69-1-0
SVC-PC-7-1-0
SVC-PC-7-2-0
SVC-PC-7-3-0
SVC-PC-7-5-0
SVC-PC-70-1-0
SVC-PC-70-5-0
SVC-PC-72-1-0
SVC-PC-73-2-0
SVC-PC-73-4-0
SVC-PC-75-0-0
SVC-PC-75-1-0
SVC-PC-75-2-0
SVC-PC-75-3-0
SVC-PC-75-4-0
SVC-PC-75-5-0
SVC-PC-75-6-0
SVC-PC-75-7-0
SVC-PC-75-8-0
SVC-PC-76-0-0
SVC-PC-76-1-0
SVC-PC-76-2-0
SVC-PC-76-3-0
SVC-PC-76-4-0
SVC-PC-79-2-0
SVC-PC-79-3-0
SVC-PC-82-0-0
SVC-PC-82-1-0
SVC-PC-9-0-0
SVC-PC-9-1-0
SVC-PC-9-2-0
SVC-PC-9-3-0
SVC-PC-9-4-0
SVC-PC-9-5-0
SVC-PC-9-6-0
SVC-PC-90-3-0
SVC-PC-90-5-0
SVC-PC-90-6-0
SVC-PC-91-0-0
SVC-PC-91-1-0
SVC-PC-91-2-0
SVC-PC-91-3-0
SVC-PC-91-4-0
SVC-PC-91-5-0
SVC-PC-91-6-0
SVC-PC-91-7-0
SVC-PC-91-8-0
SVC-PC-92-0-0
SVC-PC-92-1-0
SVC-PC-92-3-0
SVC-PC-92-4-0
SVC-PC-94-0-0
SVC-PC-94-1-0
SVC-PC-94-2-0
SVC-PC-94-3-0
SVC-PC-94-4-0
SVC-PC-94-5-0
SVC-PC-94-6-0
SVC-PC-94-7-0
SVC-PC-94-8-0
```

## 8. Not flagged: concept-only matches and the System Exports distinction

A second tier of tasks (174 task-category pairs) had a strong reference term in a judge.toml
or golden but no specific filename from the absent category. These were NOT flagged, for two
reasons verified during the audit:

1. "payroll" and "headcount" are weak signals for the HR folder. The payroll registers
   (`Payroll_Register_2021-*.xlsx`) live in `Accounting/2021/Payroll/`, and the Workday
   `Payroll_Register.csv` lives in `System Exports - 2021Q4/workday/`. The HR folder holds
   comp bands, benefits, org charts, recruiting, equity, I9. Tasks whose only HR signal was
   "payroll" usually had Accounting present (payroll covered) and cited no HR-specific file.
   The confirmed HR gaps (14-2-0, 26-0-0, 53-2-0) all cite HR-specific files
   (Comp_Bands_2021, Year_End_Headcount_Report, 2022_Benefits_Broker_Quote_Woodruff_Sawyer,
   2022_401k_Plan_Design_Guideline, Hiring_Plan_2021, Option_Grant_Sarah_Kim).

2. "trial balance", "general ledger", "Journal", "GL" are weak signals for the Accounting
   folder. `Journal.csv` and `TrialBalance.csv` live in
   `System Exports - 2021Q4/quickbooks/`, not Accounting. Several concept-only Accounting
   matches (SVC-PC-2-1-0, -2-3-0, -24-4-0 Accounting, -71-5-0) reference the QuickBooks
   Journal/Trial Balance, which is a System Exports gap (out of scope for this Company Shared
   Drive audit), not an Accounting-folder gap. The confirmed Accounting gaps all cite
   Accounting-specific files (Bank_Statement_2021-*, AP/AR_Aging_2021-*, Year_End_Trial_Balance,
   1099_Summary, Year_End_Adjusting_Entries, Q4_Bank_Reconciliation, Fixed_Asset_Depreciation,
   Payroll_Register_2021-12) that live only in `Accounting/`.

Borderline, not confirmed (named in case the coordinator wants a manual look):

- SVC-PC-2-6-0, Finance: golden names `Financial_Model_v1` (a Finance file) but as an
  "unapproved" source of a figure the golden then rejects. May or may not be a real grounding
  need.
- SVC-PC-2-1-0, -2-3-0, -24-4-0 (Accounting), -71-5-0: reference the QuickBooks
  Journal/Trial Balance/GL. These look like System Exports/quickbooks gaps, not Accounting-
  folder gaps, but each task lacks System Exports too, so the underlying need is unmet by
  some route. Flagged for manual triage, not counted in the 32.

## 9. Summary

Of 600 SVC-PC tasks enumerated, 32 are confirmed with a real corpus-hydration gap: a Company
Shared Drive category absent from `_corpus_subtree` while the task's own judge.toml / golden
/ instruction text cites specific files (or executed-MSA sections) that live only in that
absent category. The named files exist in the real shared corpus (paths verified), so each
fix is a byte-identical copy of the missing `Company Shared Drive__<Category>` folder, the
same pattern already applied to SVC-PC-19-0-0.

40 missing-category instances across the 32 tasks. Vendors is the dominant gap (21), then
Accounting (6), Finance (5), Operations (4), HR (3), Customer_Support (1).

Two tasks (SVC-PC-10-5-0, SVC-PC-73-1-0) have no Company Shared Drive at all in their
subtree (different shape, separate triage). 138 tasks use a flat-file hydration model with
no `_corpus_subtree` (different population, completeness not audited here). All 600 task
directories were checked.
