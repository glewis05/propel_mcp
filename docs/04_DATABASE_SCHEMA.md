# Propel MCP Server - Database Schema

## Overview

The Propel system uses a single SQLite database that stores all data for both the Configurations Toolkit and Requirements Toolkit.

**Database Location:** `~/projects/data/client_product_database.db`

---

# CORE TABLES

## clients
Stores client organizations.

| Column | Type | Description |
|--------|------|-------------|
| client_id | TEXT (PK) | Unique identifier (UUID) |
| name | TEXT | Client name |
| status | TEXT | Active, Inactive |
| created_date | TIMESTAMP | Record creation date |
| updated_date | TIMESTAMP | Last update date |

---

## programs
Stores programs (products) that clients use.

| Column | Type | Description |
|--------|------|-------------|
| program_id | TEXT (PK) | Unique identifier (UUID) |
| client_id | TEXT (FK) | References clients |
| name | TEXT | Program name (e.g., "Prevention4ME") |
| prefix | TEXT | Short prefix (e.g., "P4M") |
| program_type | TEXT | standalone, clinic_based, attached |
| description | TEXT | Program description |
| created_date | TIMESTAMP | Record creation date |
| updated_date | TIMESTAMP | Last update date |

---

## clinics
Stores clinic locations within programs.

| Column | Type | Description |
|--------|------|-------------|
| clinic_id | TEXT (PK) | Unique identifier (UUID) |
| program_id | TEXT (FK) | References programs |
| name | TEXT | Clinic name |
| code | TEXT | Short code (e.g., "FRANZ") |
| address | TEXT | Street address |
| city | TEXT | City |
| state | TEXT | State |
| zip | TEXT | ZIP code |
| phone | TEXT | Phone number |
| created_date | TIMESTAMP | Record creation date |
| updated_date | TIMESTAMP | Last update date |

---

## locations
Stores specific locations within clinics (e.g., satellite offices).

| Column | Type | Description |
|--------|------|-------------|
| location_id | TEXT (PK) | Unique identifier (UUID) |
| clinic_id | TEXT (FK) | References clinics |
| name | TEXT | Location name |
| code | TEXT | Short code |
| address | TEXT | Street address |
| created_date | TIMESTAMP | Record creation date |
| updated_date | TIMESTAMP | Last update date |

---

# CONFIGURATION TABLES

## config_definitions
Defines what configuration options are available.

| Column | Type | Description |
|--------|------|-------------|
| config_key | TEXT (PK) | Unique key (e.g., "helpdesk_phone") |
| display_name | TEXT | Human-readable name |
| category | TEXT | Category grouping |
| data_type | TEXT | text, number, boolean, email, etc. |
| default_value | TEXT | System default value |
| description | TEXT | Help text |
| created_date | TIMESTAMP | Record creation date |

---

## config_values
Stores actual configuration values with inheritance.

| Column | Type | Description |
|--------|------|-------------|
| config_value_id | INTEGER (PK) | Auto-increment ID |
| config_key | TEXT (FK) | References config_definitions |
| program_id | TEXT (FK) | Program level (NULL for system) |
| clinic_id | TEXT (FK) | Clinic level (NULL for program) |
| location_id | TEXT (FK) | Location level (NULL for clinic) |
| config_value | TEXT | The actual value |
| created_date | TIMESTAMP | Record creation date |
| updated_date | TIMESTAMP | Last update date |
| updated_by | TEXT | Who made the change |

**Inheritance Logic:**
1. Location value (if set)
2. Clinic value (if set)
3. Program value (if set)
4. System default (from config_definitions)

---

## providers
Stores ordering providers for clinics.

| Column | Type | Description |
|--------|------|-------------|
| provider_id | TEXT (PK) | Unique identifier (UUID) |
| clinic_id | TEXT (FK) | References clinics |
| name | TEXT | Provider full name |
| npi | TEXT | National Provider Identifier |
| credentials | TEXT | MD, DO, NP, PA, etc. |
| specialty | TEXT | Medical specialty |
| email | TEXT | Email address |
| phone | TEXT | Phone number |
| is_ordering_provider | BOOLEAN | Can order tests |
| is_active | BOOLEAN | Currently active |
| created_date | TIMESTAMP | Record creation date |
| updated_date | TIMESTAMP | Last update date |

---

## appointment_types
Stores appointment types for clinics.

| Column | Type | Description |
|--------|------|-------------|
| appointment_type_id | TEXT (PK) | Unique identifier (UUID) |
| clinic_id | TEXT (FK) | References clinics |
| name | TEXT | Appointment type name |
| code | TEXT | Short code |
| duration_minutes | INTEGER | Default duration |
| description | TEXT | Description |
| visit_type | TEXT | In-person, Telehealth, etc. |
| is_active | BOOLEAN | Currently active |
| created_date | TIMESTAMP | Record creation date |
| updated_date | TIMESTAMP | Last update date |

---

# USER ACCESS TABLES

## users
Stores all users who access the system.

| Column | Type | Description |
|--------|------|-------------|
| user_id | TEXT (PK) | Unique identifier (UUID) |
| name | TEXT | Full name |
| email | TEXT (UNIQUE) | Email address |
| organization | TEXT | Organization name |
| status | TEXT | Active, Inactive, Terminated |
| is_business_associate | BOOLEAN | Requires BAA |
| notes | TEXT | Additional notes |
| created_date | TIMESTAMP | Record creation date |
| updated_date | TIMESTAMP | Last update date |

---

## user_access
Stores access grants linking users to programs/clinics.

| Column | Type | Description |
|--------|------|-------------|
| access_id | INTEGER (PK) | Auto-increment ID |
| user_id | TEXT (FK) | References users |
| program_id | TEXT (FK) | References programs |
| clinic_id | TEXT (FK) | References clinics (NULL = program-wide) |
| location_id | TEXT (FK) | References locations (NULL = clinic-wide) |
| role | TEXT | Read-Write-Order, Read-Write, Read-Only |
| is_active | BOOLEAN | Currently active |
| granted_date | DATE | When access was granted |
| granted_by | TEXT | Who granted access |
| revoked_date | DATE | When access was revoked |
| revoked_by | TEXT | Who revoked access |
| revoke_reason | TEXT | Reason for revocation |
| review_cycle | TEXT | Quarterly, Annual |
| next_review_due | DATE | When review is due |
| ticket | TEXT | Reference ticket number |
| created_date | TIMESTAMP | Record creation date |
| updated_date | TIMESTAMP | Last update date |

---

## access_reviews
Stores history of access reviews (recertification).

| Column | Type | Description |
|--------|------|-------------|
| review_id | INTEGER (PK) | Auto-increment ID |
| access_id | INTEGER (FK) | References user_access |
| review_date | DATE | When review was completed |
| reviewed_by | TEXT | Who performed review |
| status | TEXT | Certified, Revoked, Modified |
| notes | TEXT | Review notes |
| next_review_due | DATE | Next review date |
| created_date | TIMESTAMP | Record creation date |

---

## user_training
Stores training records for users.

| Column | Type | Description |
|--------|------|-------------|
| training_id | INTEGER (PK) | Auto-increment ID |
| user_id | TEXT (FK) | References users |
| training_type | TEXT | HIPAA Privacy, HIPAA Security, Part 11, etc. |
| completed_date | DATE | When completed |
| expires_date | DATE | When expires |
| certificate_reference | TEXT | Certificate ID/link |
| status | TEXT | Pending, Current, Expired |
| assigned_date | DATE | When assigned |
| assigned_by | TEXT | Who assigned |
| created_date | TIMESTAMP | Record creation date |
| updated_date | TIMESTAMP | Last update date |

---

## role_conflicts
Stores segregation of duties rules.

| Column | Type | Description |
|--------|------|-------------|
| conflict_id | INTEGER (PK) | Auto-increment ID |
| role_a | TEXT | First role |
| role_b | TEXT | Conflicting role |
| conflict_reason | TEXT | Why roles conflict |
| severity | TEXT | Warning, Block |
| created_date | TIMESTAMP | Record creation date |

---

# AUDIT TABLES

## audit_history
Stores complete audit trail for compliance.

| Column | Type | Description |
|--------|------|-------------|
| audit_id | INTEGER (PK) | Auto-increment ID |
| record_type | TEXT | user, user_access, config_value, etc. |
| record_id | TEXT | ID of affected record |
| action | TEXT | CREATE, UPDATE, DELETE, TERMINATE, GRANT, REVOKE |
| old_value | TEXT | Previous value (JSON) |
| new_value | TEXT | New value (JSON) |
| changed_by | TEXT | Who made change |
| change_reason | TEXT | Why change was made |
| changed_date | TIMESTAMP | When change occurred |

---

# REQUIREMENTS TABLES

## requirements
Stores high-level requirements.

| Column | Type | Description |
|--------|------|-------------|
| requirement_id | TEXT (PK) | Unique identifier |
| program_id | TEXT (FK) | References programs |
| title | TEXT | Requirement title |
| description | TEXT | Full description |
| category | TEXT | Category grouping |
| priority | TEXT | High, Medium, Low |
| status | TEXT | Draft, Approved, Implemented |
| created_date | TIMESTAMP | Record creation date |
| updated_date | TIMESTAMP | Last update date |

---

## user_stories
Stores user stories derived from requirements.

| Column | Type | Description |
|--------|------|-------------|
| story_id | TEXT (PK) | Story ID (e.g., "PROP-AUTH-001") |
| program_id | TEXT (FK) | References programs |
| requirement_id | TEXT (FK) | References requirements |
| title | TEXT | Story title |
| user_story | TEXT | As a... I want... So that... |
| role | TEXT | User role extracted from story |
| acceptance_criteria | TEXT | Acceptance criteria (multi-line text) |
| category | TEXT | Category code (e.g., AUTH, DASH) |
| category_full | TEXT | Full category name |
| priority | TEXT | MoSCoW: Must Have, Should Have, Could Have, Won't Have |
| roadmap_target | TEXT | Annual planning: Q1-Q4 2026, 2027, or Backlog |
| status | TEXT | Draft, Internal Review, Pending Client Review, Approved, Needs Discussion, Out of Scope |
| version | INTEGER | Version number (auto-incremented on changes) |
| internal_notes | TEXT | Internal team notes |
| client_feedback | TEXT | Feedback from client review |
| created_date | TIMESTAMP | Record creation date |
| updated_date | TIMESTAMP | Last update date |
| draft_date | TIMESTAMP | When moved to Draft status |
| internal_review_date | TIMESTAMP | When moved to Internal Review status |
| client_review_date | TIMESTAMP | When moved to Pending Client Review status |
| approved_date | TIMESTAMP | When moved to Approved status |
| approved_by | TEXT | Who approved the story |
| needs_discussion_date | TIMESTAMP | When moved to Needs Discussion status |

**Status Timeline Notes:**
- Each status transition automatically sets its corresponding date field
- This creates an audit trail showing when stories moved through each workflow stage
- Priority (MoSCoW) = what's in THIS release; Roadmap Target = WHEN on annual roadmap

---

## uat_test_cases
Stores test cases for user stories.

| Column | Type | Description |
|--------|------|-------------|
| test_case_id | TEXT (PK) | Test case ID |
| story_id | TEXT (FK) | References user_stories |
| test_type | TEXT | happy_path, negative, validation, edge_case |
| title | TEXT | Test case title |
| preconditions | TEXT | Setup required |
| steps | TEXT | Test steps (JSON) |
| expected_result | TEXT | Expected outcome |
| status | TEXT | Not Run, Pass, Fail, Blocked, Skipped |
| executed_by | TEXT | Who ran the test |
| executed_date | DATE | When test was run |
| notes | TEXT | Test notes |
| created_date | TIMESTAMP | Record creation date |
| updated_date | TIMESTAMP | Last update date |

---

# ENTITY RELATIONSHIP DIAGRAM

```
clients
    └── programs
            ├── clinics
            │       ├── locations
            │       ├── providers
            │       ├── appointment_types
            │       └── config_values (clinic level)
            ├── config_values (program level)
            ├── requirements
            │       └── user_stories
            │               └── uat_test_cases
            └── user_access
                    ├── users
                    │       └── user_training
                    └── access_reviews

config_definitions ──> config_values (defines valid keys)
audit_history (tracks all changes)
```

---

# INDEXES

| Table | Index | Columns |
|-------|-------|---------|
| users | idx_users_status | status |
| users | idx_users_email | email |
| user_access | idx_user_access_user | user_id |
| user_access | idx_user_access_program | program_id |
| user_access | idx_user_access_clinic | clinic_id |
| user_access | idx_user_access_active | is_active |
| user_access | idx_user_access_review_due | next_review_due |
| access_reviews | idx_access_reviews_access | access_id |
| user_training | idx_user_training_user | user_id |
| user_training | idx_user_training_status | status |
| config_values | idx_config_values_key | config_key |
| config_values | idx_config_values_program | program_id |
| config_values | idx_config_values_clinic | clinic_id |

---

*Last Updated: January 2026*
