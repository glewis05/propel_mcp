# Propel MCP Server - Workflow Guide

This guide provides step-by-step procedures for common tasks.

---

# CLINIC ONBOARDING WORKFLOW

## Scenario: New clinic going live with Prevention4ME

### Step 1: Receive Roster from Clinic
- Clinic manager sends Excel file with staff list
- Expected columns: First Name, Last Name, Job Role, Credentials, Program, Clinic, Access Level, Email

### Step 2: Preview the Import
```
Import roster at ~/Downloads/NewClinic_Roster.xlsx
```
- Review the preview output
- Check for errors (missing emails, unknown programs/clinics)
- Verify user counts match expectations

### Step 3: Execute the Import
```
Import roster at ~/Downloads/NewClinic_Roster.xlsx granted by [Your Name] with preview_only false
```
- Confirm success message
- Note any errors for follow-up

### Step 4: Verify Import
```
List users for [New Clinic Name]
```
- Confirm all users appear
- Check role assignments are correct

### Step 5: Update Compliance Dashboard
```
Push dashboard to Notion
```
- Dashboard now reflects new users

---

# ANNUAL ACCESS REVIEW WORKFLOW

## Scenario: Quarterly/Annual recertification for a clinic

### Step 1: Export Review Status
```
Export access review status for [Clinic Name]
```
- File saved to ~/Downloads/
- Contains all users with overdue or upcoming reviews
- Includes Action, New Role, Manager Notes columns (empty)

### Step 2: Send to Clinic Manager
- Email the Excel file to clinic manager
- Include instructions:
  - **Action column**: Leave blank to keep, enter "Terminate" or "Update"
  - **New Role column**: Required if Action = Update
  - **Manager Notes**: Required for Terminate/Update, optional for Keep

### Step 3: Receive Completed File
- Clinic manager returns file with decisions filled in

### Step 4: Preview the Response Import
```
Import review response from ~/Downloads/[Clinic]_Review_Completed.xlsx reviewed by [Manager Name]
```
- Review planned actions:
  - ✅ Recertify (blank action)
  - 🔄 Update (role change)
  - ❌ Terminate (revoke access)
- Check for errors

### Step 5: Execute the Import
```
Import review response from ~/Downloads/[Clinic]_Review_Completed.xlsx reviewed by [Manager Name] with preview_only false
```
- Confirm success
- Next review dates automatically set

### Step 6: Verify and Document
```
Show me the compliance dashboard
```
- Overdue count should decrease
- Push to Notion for record keeping

---

# COMPLIANCE CHECK WORKFLOW

## Scenario: Weekly/Monthly compliance review

### Step 1: View Dashboard
```
Show me the compliance dashboard
```
- Check Immediate Attention section:
  - 🔴 Reviews overdue
  - 🔴 Terminated with active access (violations!)
  - 🔴 Training expired

### Step 2: Address Violations (URGENT)
If terminated users have active access:
```
Export terminated user audit
```
- Open Excel file
- Identify users with "YES - VIOLATION!" in Access Still Active column
- Manually revoke access or investigate

### Step 3: Address Overdue Reviews
```
Export access review status
```
- Send to appropriate clinic managers
- Follow Annual Access Review workflow

### Step 4: Address Expired Training
```
Get expired training
```
- Contact users or managers for renewal
- Update training records when completed

### Step 5: Update Stakeholders
```
Push dashboard to Notion
Export compliance dashboard
```
- Notion page shows current status
- Excel file for stakeholder meetings/audits

---

# TERMINATED USER WORKFLOW

## Scenario: Employee leaves organization

### Step 1: Identify User
```
Get user [email@domain.com]
```
- Confirm user details
- Note all access grants

### Step 2: Terminate User
(Currently manual in database or through access review process)

### Step 3: Verify Access Revoked
```
Export terminated user audit
```
- Find user in report
- Confirm "Compliance Status" = Compliant
- Confirm "Access Still Active" = No for all grants

### Step 4: Document
- Audit trail automatically maintained in database
- Dashboard reflects change after refresh

---

# CONFIGURATION REVIEW WORKFLOW

## Scenario: Reviewing clinic setup before go-live

### Step 1: Check Program Overview
```
Show me [Program Name]
```
- Verify clinics are listed
- Check location counts
- Confirm user counts

### Step 2: Review Clinic Configuration
```
Show me [Clinic Name] config
```
- Review all settings
- Note which are Program Defaults vs Clinic Overrides
- Verify critical settings (helpdesk, email, workflows)

### Step 3: Check What's Different
```
What configs are overridden at [Clinic Name]?
```
- See only the customized settings
- Verify overrides are intentional

### Step 4: Compare to Known-Good Clinic
```
Compare [New Clinic] and [Existing Clinic]
```
- Identify unexpected differences
- Ensure consistency where needed

### Step 5: Verify Providers
```
Who are the providers at [Clinic Name]?
```
- Confirm all ordering providers listed
- Verify NPIs are correct

### Step 6: Verify Appointment Types
```
What appointment types does [Clinic Name] have?
```
- Confirm all expected types exist
- Verify durations are correct

### Step 7: Export for Documentation
```
Export all configurations for [Program]
```
- Archive Excel file
- Use for go-live checklist

---

# MULTI-CLINIC COMPARISON WORKFLOW

## Scenario: Ensuring consistency across clinics

### Step 1: Export All Configurations
```
Export configurations for [Program]
```

### Step 2: Open Configuration Matrix Sheet
- Yellow highlighted cells = overrides
- Blank cells = using program default
- Compare columns to identify inconsistencies

### Step 3: Investigate Differences
For any unexpected differences:
```
What configs are overridden at [Clinic]?
```
- Determine if override is intentional
- Document or correct as needed

---

# STAKEHOLDER REPORTING WORKFLOW

## Scenario: Preparing for audit or executive review

### Step 1: Generate Dashboard Export
```
Export compliance dashboard
```
- Summary sheet has key metrics
- Detail sheets for drill-down

### Step 2: Generate Terminated Audit
```
Export terminated user audit since [start-of-review-period]
```
- Shows all terminations in period
- Confirms access properly revoked

### Step 3: Generate Access Review Status
```
Export access review status including current reviews
```
- Shows all access with review history
- Demonstrates recertification compliance

### Step 4: Generate Configuration Export
```
Export configurations for [Program]
```
- Shows current state of all settings
- Provides audit trail of configuration

### Step 5: Update Notion
```
Push dashboard to Notion
```
- Provides live link for stakeholders

---

# TROUBLESHOOTING WORKFLOWS

## "Program not found" Error
1. Check exact spelling: `List programs`
2. Try using prefix: "P4M" instead of "Prevention4ME"
3. Verify program exists in database

## "Clinic not found" Error
1. Check exact spelling: `Show me [Program]` to see clinic list
2. Try clinic code: "FRANZ" instead of "Franz Clinic"
3. Specify program if ambiguous: `Show me Franz config for Prevention4ME`

## Import Errors
1. Check file path is correct
2. Verify Excel has required columns
3. Check for missing email addresses
4. Verify program/clinic names match database

## Dashboard Not Updating in Notion
1. Run: `Push dashboard to Notion`
2. Refresh Notion page in browser
3. Check Notion connection is active

---

*Last Updated: January 2025*
