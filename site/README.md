# Commissioner Discretionary Spending Dashboard

A public page that shows each commissioner's discretionary money, where it went, and whether each gift did what it was given for.

The page reads three CSV files. Making it the county's own page means hosting this folder and keeping those files current. No code changes are needed.

## Files

| File | Holds | Kept by |
|---|---|---|
| `index.html`, `app.js`, `styles.css`, `theme.js` | The page | Nobody. They don't change. |
| `config.json` | Title, banner text, data file paths | IT, once |
| `data/ledger.csv` | Every line of the yearly spending report | Finance |
| `data/gifts.csv` | One row per gift, from approval to outcome | Commission office, then the office that checks reports |
| `data/reports.csv` | One row per fiscal year, with its "as of" date | Finance |
| `web.config` | Lets IIS serve `.csv` and `.json` files | IT, once |

## Hosting

- Copy this folder to any path on the county site, such as `hamiltontn.gov/discretionary/`.
- The page is static files only. It needs no database, server code or build step.
- On IIS, keep `web.config` or merge its `staticContent` block into the site's existing one.
- To remove the prototype banner, set `"notice": ""` in `config.json`.
- The builder credit and the related-tools link at the bottom come from `"credit"` and `"more"` in `config.json`. Delete either block to remove it.
- Tested in Chrome at desktop and narrow widths, in light and dark mode. Other browsers are untested.
- The page follows the viewer's system light or dark setting. A Light/Dark switch at the top overrides it and is remembered in that browser.

## Updating the data

- Replace a CSV file and reload the page.
- From Excel, use Save As and pick "CSV UTF-8".
- Dates can be `2024-06-26` or `6/26/2024`.
- Amounts can include `$` and commas. Negatives can use a minus sign or parentheses.
- Column order doesn't matter. Column names do.
- Any page can link to one gift with `?gift=G2024-D09-005`, or to one commissioner's breakdown with `?year=2026&cm=4:Mackey`.

## ledger.csv

One row per line of the spending report Finance already produces. Finance can export it from CentralSquare instead of printing the PDF.

| Column | Required | Meaning |
|---|---|---|
| `fiscal_year` | Yes | Year the fiscal year ends. FY2027 is `2027`. |
| `district` | Yes | `1` to `11` |
| `commissioner` | Yes | Name as it should appear on the page |
| `fund` | Yes | `travel_discretionary`, `general_fund_discretionary` or `bond_fund` |
| `line_type` | Yes | See the line types below |
| `category` | For payments | `gift`, `travel_office`, `community_purchase` or `transfer` |
| `gift_id` | For gifts | Matches the gift's row in `gifts.csv` |
| `amount` | Yes | Money out is negative. Refunds and voids are positive. |
| `payee`, `purpose` | No | Shown in the gift record |
| `ledger_id`, `description`, `source`, `source_line` | No | Tracing back to the report |

| line_type | Meaning |
|---|---|
| `budget` | New money for the year |
| `carryover` | Money rolled in from an earlier year |
| `beginning_balance` | Opening balance, when the report prints one |
| `payment` | Money paid out, or a refund or void |
| `committed` | Money set aside for a gift that is not yet paid. Counted as spent in this year, as the county's reports do. |
| `commitment_paid` | A payment of money committed in an earlier year. Not counted again. |
| `transfer` | Money moved between funds or districts |
| `total_expenses` | The report's own total |
| `ending_balance` | The report's closing balance |

`category` should come from the account code each payment posts to. For FY2017 to FY2027 it was assigned from the report text. See Known limits.

## gifts.csv

One row per gift. The commission office adds the row when the resolution passes. The office that checks recipient reports fills in the rest later. Blank cells show as "Not recorded".

Set when the commission approves the gift:

| Column | Meaning |
|---|---|
| `gift_id` | Any unique ID. The prototype uses `G{year}-D{district}-{number}`. |
| `fiscal_year`, `district`, `commissioner` | Who gave it, and when |
| `recipient` | Organization name |
| `recipient_ein` | Federal tax ID from the IRS letter |
| `recipient_address` | Street address |
| `recipient_in_district` | `Yes`, `No` or `Countywide` |
| `project` | What the money is for |
| `amount_approved` | Dollars in the resolution |
| `resolution_no`, `resolution_date` | The approving resolution |
| `goal` | One line someone can check later, such as "Buy two thermal imaging cameras" |
| `report_due` | Date the recipient's report is due |

Filled in after the money goes out:

| Column | Meaning |
|---|---|
| `report_received` | Date the report arrived |
| `evidence_url` | Link to the invoice, receipt or photo |
| `outcome` | `met`, `not_met`, `no_report` or `voided` |
| `verified_by` | Office or person who checked it |
| `verified_date` | Date it was checked |
| `notes` | Anything else, shown under the record |
| `record_source` | Where the row's facts came from |

The page shows "Report due" until `report_due` passes, then "Report overdue" until an outcome is entered.

## reports.csv

| Column | Meaning |
|---|---|
| `fiscal_year` | `2027` |
| `period` | `July 1, 2026 to June 30, 2027` |
| `as_of` | Date the data runs through, such as `November 19, 2026` |
| `source_url` | Link to the published report |

A year whose `as_of` isn't June 30 shows as in progress.

## What the policy needs to require

Every blank column above is something no one records today. The dashboard can only show what the policy asks for.

| Field | Policy requirement |
|---|---|
| `recipient_ein` | IRS letter on file. Procedures since 2005 already require it. |
| `recipient_address`, `recipient_in_district` | Address on the request, and a rule for groups that serve the whole county |
| `goal` | A checkable goal written into each resolution |
| `report_due` | A reporting deadline, such as 90 days after payment |
| `report_received`, `evidence_url` | A report and proof from every recipient |
| `outcome`, `verified_by`, `verified_date` | A named office that checks each report |
| `outcome = no_report` | A consequence. The 2025 audit recommended no further gifts to a group until it sends its paperwork. |

## Known limits of the prototype data

- Categories for FY2017 to FY2027 were assigned by keyword from each report line. Fixes go in `scripts/category_overrides.csv`.
- Resolution numbers exist only for FY2023 and FY2024 gifts, taken from Exhibit I of the 2025 audit. All 87 audit rows matched a report line.
- Commissioner names appear as the reports print them, which is last names only.
- All 282 fund blocks reconcile. Each one's opening money minus its spending equals the closing balance the report prints.
- All 60 "Total Expenses" lines printed in FY2024 to FY2027 match the page's spending for that block.
- Money committed in one year and paid the next counts in the year it was committed, matching the county. The FY2026 payment for the Hardy Elementary sign is an example.
- No outcome data exists. Every gift shows "Not tracked" except voided gifts and the Kingship Chess Group gift, which the audit found had no documentation.
