# Propel MCP Server - Tool Reference Guide

## Overview

The Propel MCP Server provides tools for managing healthcare software implementation, user access, compliance tracking, and clinic configurations.

**Total Tools: ~40**

---

# USER MANAGEMENT TOOLS

## list_users

List users from the Propel Health database.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| program | string | No | Filter by program name (e.g., "Prevention4ME") |
| status | string | No | Filter by status: "Active", "Inactive", "Terminated" |
| organization | string | No | Filter by organization name |
| clinic | string | No | Filter by clinic name or code |
| location | string | No | Filter by location name or code |

**Examples:**
```
"List users"
"List users for Prevention4ME"
"List active users at Franz Clinic"
"List terminated users"
```

---

## get_user

Get detailed information about a specific user.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| email | string | Yes | User's email address |

**Examples:**
```
"Get user john.smith@providence.org"
"Show me details for jane.doe@clinic.com"
```

**Returns:** User details including status, organization, access grants, and training records.

---

## add_user

Create a new user in the system.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | string | Yes | Full name (e.g., "John Smith") |
| email | string | Yes | Email address (must be unique) |
| organization | string | No | Organization name (default: "Internal") |
| is_business_associate | boolean | No | True if external party requiring HIPAA BAA |

**Examples:**
```
"Add user John Smith with email john.smith@clinic.com"
"Create user Jane Doe, email jane@partner.com, organization Partner Corp, is_business_associate true"
```

---

## import_access_roster

Import users and access grants from an Excel roster file.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| file_path | string | Yes | Path to Excel file |
| granted_by | string | No | Who is granting access (default: "System Import") |
| preview_only | boolean | No | If true, show what would happen (default: true) |

**Import Logic:**
- New email → Create user + grant access
- Existing email, different clinic → Add new access grant
- Existing email, same clinic → Update existing access

**Supported File Formats:**
- With Clinic column: First Name, Last Name, Job Role, Credentials, Program, Clinic, Access Level, Email
- Without Clinic: First Name, Last Name, Job Role, Credentials, Program, Access Level, Email

**Access Level Mapping:**
| Spreadsheet | Database |
|-------------|----------|
| Read + Write + Order | Read-Write-Order |
| Read + Write | Read-Write |
| Read Only | Read-Only |

**Examples:**
```
"Import roster at ~/Downloads/Portland_Roster.xlsx"
"Import roster at ~/Downloads/Franz_Staff.xlsx granted by Glen Lewis"
"Import roster at ~/Downloads/New_Clinic.xlsx with preview_only false"
```

---

# ACCESS MANAGEMENT TOOLS

## list_access

List access grants with optional filters.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| user_email | string | No | Filter by user's email |
| program | string | No | Filter by program name |

**Examples:**
```
"List access for john.smith@providence.org"
"List all access grants for Prevention4ME"
```

---

## get_reviews_due

Get access reviews that are overdue or due soon.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| program | string | No | Filter by program name |

**Examples:**
```
"Get reviews due"
"Get reviews due for Prevention4ME"
```

---

# COMPLIANCE REPORTING TOOLS

## get_compliance_report

Generate a compliance report.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| report_type | string | Yes | Type of report (see below) |
| program | string | No | Filter by program name |

**Report Types:**
| Type | Description |
|------|-------------|
| access_list | Who has access to what |
| review_status | Are access reviews current? |
| training_compliance | Training completion status |
| terminated_audit | Check for terminated users with access |
| business_associates | List of business associates |

**Examples:**
```
"Get compliance report access_list"
"Get compliance report terminated_audit for Prevention4ME"
```

---

## export_review_status

Export access review status to Excel for compliance tracking.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| program | string | No | Filter by program name or prefix |
| include_current | boolean | No | Include reviews that are current (default: false) |
| output_format | string | No | "xlsx" or "csv" (default: "xlsx") |
| output_dir | string | No | Directory to save file (default: ~/Downloads) |

**Output Columns:**
Review Status, Days Overdue, User Name, Email, Role, Program, Clinic, Location, Granted Date, Last Review, Next Review Due, Review Cycle, Action, New Role, Manager Notes

**Examples:**
```
"Export access review status"
"Export access review status for Franz Clinic"
"Export access review status including current reviews"
```

---

## import_review_response

Import completed annual access review responses from clinic manager.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| file_path | string | Yes | Path to completed Excel review file |
| reviewed_by | string | Yes | Name of clinic manager who completed review |
| preview_only | boolean | No | If true, show what would happen (default: true) |

**Action Column Values:**
| Value | Result |
|-------|--------|
| (blank) | Recertify - confirm access, set next review date |
| Terminate | Revoke access (Manager Notes required) |
| Update | Change role to New Role value (New Role required) |

**Examples:**
```
"Import review response from ~/Downloads/Franz_Review.xlsx reviewed by Jerry Cain"
"Import review response from ~/Downloads/Kadlec_Review.xlsx reviewed by Sarah Johnson with preview_only false"
```

---

## export_terminated_audit

Export full terminated user audit to Excel.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| since_date | string | No | Only include users terminated on/after this date (YYYY-MM-DD) |
| output_format | string | No | "xlsx" or "csv" (default: "xlsx") |
| output_dir | string | No | Directory to save file (default: ~/Downloads) |

**Examples:**
```
"Export terminated user audit"
"Export terminated user audit since 2024-01-01"
```

---

# TRAINING TOOLS

## get_training_status

Get training status for a specific user.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| user_email | string | Yes | User's email address |

**Examples:**
```
"Get training status for john.smith@providence.org"
```

---

## get_expired_training

Get all users with expired training that needs renewal.

**Parameters:** None

**Examples:**
```
"Get expired training"
"Show me all expired training records"
```

---

# DASHBOARD TOOLS

## get_compliance_dashboard

Get compliance dashboard with text summary and visual artifact.

**Parameters:** None

**Returns:**
- Text summary with alerts, totals, and metrics
- React artifact with charts for visual display

**Metrics Included:**
- Access reviews overdue
- Terminated users with active access (violations)
- Training expired
- Reviews due soon (30 days)
- Users by program
- Users by clinic
- Role distribution
- Recent activity (last 30 days)

**Examples:**
```
"Show me the compliance dashboard"
"Get compliance dashboard"
```

---

## push_dashboard_to_notion

Update the Notion compliance dashboard page with current data.

**Parameters:** None

**Target Page:** https://www.notion.so/2dab5d1d163181bb8eebc4f4397de747

**Examples:**
```
"Push dashboard to Notion"
"Update the Notion dashboard"
```

---

## export_compliance_dashboard

Export compliance dashboard to Excel for stakeholders.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| output_dir | string | No | Directory to save file (default: ~/Downloads) |

**Sheets Included:**
- Summary (all metrics)
- Users by Program
- Users by Clinic
- Role Distribution
- Recent Activity

**Examples:**
```
"Export compliance dashboard"
"Export compliance dashboard to ~/Documents/Reports"
```

---

# CONFIGURATION VIEWING TOOLS

## get_program_overview

Get overview of a program including its clinics and locations.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| program | string | Yes | Program name or prefix |

**Examples:**
```
"Show me Prevention4ME"
"Get program overview for P4M"
"Show me Precision4ME"
```

---

## get_clinic_config

Get all configuration values for a clinic, showing inheritance.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| clinic | string | Yes | Clinic name or code |
| program | string | No | Program name/prefix if clinic name is ambiguous |

**Shows:**
- All configs grouped by category
- Source for each value (Program Default, Clinic Override, System Default)
- Location-level overrides if any

**Examples:**
```
"Show me Franz Clinic config"
"Get config for Kadlec"
"Show me Portland Cancer Center config for Prevention4ME"
```

---

## compare_clinic_configs

Compare configurations between two clinics side-by-side.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| clinic1 | string | Yes | First clinic name or code |
| clinic2 | string | Yes | Second clinic name or code |

**Examples:**
```
"Compare Franz and Kadlec"
"Compare Portland Cancer Center and Kadlec configurations"
```

---

## get_config_overrides

Get only the configuration values that are overridden at a clinic.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| clinic | string | Yes | Clinic name or code |
| program | string | No | Program name/prefix if ambiguous |

**Shows:**
- Clinic-level overrides with program default comparison
- Location-level overrides

**Examples:**
```
"What configs are overridden at Franz?"
"Show me overrides for Kadlec"
```

---

## get_clinic_providers

Get list of providers at a clinic.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| clinic | string | Yes | Clinic name or code |
| program | string | No | Program name/prefix if ambiguous |

**Returns:** Provider name, credentials, NPI, specialty, ordering provider status, active status

**Examples:**
```
"Who are the providers at Franz?"
"List providers for Kadlec Clinic"
```

---

## get_clinic_appointment_types

Get list of appointment types at a clinic.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| clinic | string | Yes | Clinic name or code |
| program | string | No | Program name/prefix if ambiguous |

**Returns:** Appointment type name, code, duration, visit type, active status

**Examples:**
```
"What appointment types does Franz have?"
"Show me appointment types for Kadlec"
```

---

## export_program_configs

Export all configurations for a program to Excel.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| program | string | Yes | Program name or prefix |
| output_dir | string | No | Directory to save file (default: ~/Downloads) |

**Sheets Included:**
- Overview (program and clinic list)
- Configuration Matrix (all configs, all clinics side-by-side, overrides highlighted)
- Providers (all clinics)
- Appointment Types (all clinics)

**Examples:**
```
"Export all configurations for Prevention4ME"
"Export configs for P4M"
"Export Precision4ME configurations to ~/Documents"
```

---

# PROGRAM/CLIENT TOOLS

## list_programs

List all programs with their clinic and location hierarchy.

**Parameters:** None

**Examples:**
```
"List programs"
"Show me all programs"
```

---

## list_clients

List all clients in the requirements database.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| status | string | No | Filter by status: "Active", "Inactive" (default: "Active") |

**Examples:**
```
"List clients"
"List all clients including inactive"
```

---

## get_client_programs

Get all programs for a specific client.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| client_name | string | Yes | Name of the client |

**Examples:**
```
"Get programs for Providence"
"Show me client programs for St. Joseph"
```

---

# REQUIREMENTS TOOLS

## list_stories

List user stories for a program.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| program_prefix | string | Yes | Program prefix (e.g., "PROP") |
| status | string | No | Filter by status |
| category | string | No | Filter by category |

**Examples:**
```
"List stories for PROP"
"List approved stories for P4M"
```

---

## get_story

Get detailed information about a specific user story.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| story_id | string | Yes | The story ID (e.g., "PROP-AUTH-001") |

**Examples:**
```
"Get story PROP-AUTH-001"
"Show me story P4M-ENROLL-003"
```

---

## search_stories

Search for stories across all programs by keyword.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| keyword | string | Yes | Search term |

**Examples:**
```
"Search stories for enrollment"
"Find stories about consent"
```

---

## list_test_cases

List UAT test cases for a program.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| program_prefix | string | Yes | Program prefix |
| status | string | No | Filter by status: Not Run, Pass, Fail, Blocked, Skipped |
| test_type | string | No | Filter by type: happy_path, negative, validation, edge_case |

**Examples:**
```
"List test cases for PROP"
"List failed test cases for P4M"
```

---

## get_test_summary

Get test execution summary for a program.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| program_prefix | string | Yes | Program prefix |

**Examples:**
```
"Get test summary for PROP"
```

---

## get_program_health

Get health score and recommendations for a program.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| program_prefix | string | Yes | Program prefix |

**Examples:**
```
"Get program health for PROP"
"Show me health score for P4M"
```

---

## get_coverage_gaps

Find requirements without stories and stories without tests.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| program_prefix | string | Yes | Program prefix |

**Examples:**
```
"Get coverage gaps for PROP"
"Show me what's missing test coverage for P4M"
```

---

*Last Updated: January 2025*
