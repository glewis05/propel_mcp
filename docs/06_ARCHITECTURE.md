# Propel MCP Server - Architecture Overview

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLAUDE DESKTOP                           │
│                    (User Interface Layer)                       │
└─────────────────────────────────────────────────────────────────┘
                               │
                               │ MCP Protocol
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PROPEL MCP SERVER                          │
│                    ~/projects/propel_mcp/                       │
│                                                                 │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐ │
│  │  User Management │  │   Compliance     │  │ Configuration │ │
│  │      Tools       │  │     Tools        │  │    Tools      │ │
│  └────────┬─────────┘  └────────┬─────────┘  └───────┬───────┘ │
│           │                     │                     │         │
│           └─────────────────────┼─────────────────────┘         │
│                                 │                               │
│                                 ▼                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    ACCESS MANAGER                         │  │
│  │      ~/projects/configurations_toolkit/managers/          │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                               │
                               │ SQLite
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SHARED DATABASE                              │
│          ~/projects/data/client_product_database.db             │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │    Core      │  │    User      │  │   Configuration    │    │
│  │   Tables     │  │   Access     │  │      Tables        │    │
│  │              │  │   Tables     │  │                    │    │
│  │  clients     │  │  users       │  │  config_definitions│    │
│  │  programs    │  │  user_access │  │  config_values     │    │
│  │  clinics     │  │  access_     │  │  providers         │    │
│  │  locations   │  │    reviews   │  │  appointment_types │    │
│  │              │  │  user_       │  │                    │    │
│  │              │  │    training  │  │                    │    │
│  └──────────────┘  └──────────────┘  └────────────────────┘    │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    AUDIT HISTORY                          │  │
│  │              (Complete Change Tracking)                   │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                               │
                               │ Notion API
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                         NOTION                                  │
│              (External Dashboard/Documentation)                 │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐    │
│  │        📊 Client Access Compliance Dashboard            │    │
│  │        https://notion.so/2dab5d1d163181bb...            │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Structure

```
~/projects/
├── propel_mcp/
│   ├── server.py              # MCP server with all tools
│   └── requirements.txt       # Python dependencies
│
├── configurations_toolkit/
│   ├── managers/
│   │   └── access_manager.py  # User/access management logic
│   ├── parsers/
│   │   └── word_parser.py     # Word document parser
│   └── schema/
│       └── access_schema.sql  # Database schema
│
├── requirements_toolkit/
│   ├── managers/
│   │   └── requirements_manager.py
│   └── parsers/
│       └── excel_parser.py
│
└── data/
    └── client_product_database.db  # Shared SQLite database
```

---

## Tool Categories

### User Management (7 tools)
```
list_users          → List/filter users
get_user            → Get user details
add_user            → Create new user
import_access_roster → Bulk import users
list_access         → List access grants
get_reviews_due     → Reviews needing attention
```

### Compliance Reporting (6 tools)
```
get_compliance_report      → Generate compliance report
export_review_status       → Export for clinic managers
import_review_response     → Process manager responses
export_terminated_audit    → Terminated user audit
get_training_status        → User training records
get_expired_training       → Expired training list
```

### Dashboard (3 tools)
```
get_compliance_dashboard   → Text + React visual
push_dashboard_to_notion   → Update Notion page
export_compliance_dashboard → Excel for stakeholders
```

### Configuration Viewing (7 tools)
```
get_program_overview       → Program summary
get_clinic_config          → Clinic configuration
compare_clinic_configs     → Side-by-side comparison
get_config_overrides       → Only overridden values
get_clinic_providers       → Provider list
get_clinic_appointment_types → Appointment types
export_program_configs     → Full Excel export
```

### Program/Client (4 tools)
```
list_programs         → All programs
list_clients          → All clients
get_client_programs   → Programs for client
get_program_by_prefix → Program details
```

### Requirements (8 tools)
```
list_stories          → User stories
get_story             → Story details
search_stories        → Search by keyword
list_test_cases       → UAT test cases
get_test_summary      → Test execution summary
get_program_health    → Health score
get_coverage_gaps     → Missing coverage
get_approval_pipeline → Kanban view
```

---

## Data Flow

### User Import Flow
```
Excel File → import_access_roster → AccessManager → Database
                    │
                    ├── New email? → Create user + Grant access
                    ├── Existing + new clinic? → Add access grant
                    └── Existing + same clinic? → Update access
```

### Access Review Flow
```
export_review_status → Excel File → Clinic Manager
                                          │
                                    (fills in decisions)
                                          │
                                          ▼
import_review_response ← Completed Excel
         │
         ├── Blank action → Recertify (set next review date)
         ├── Terminate → Revoke access
         └── Update → Change role
```

### Configuration Inheritance
```
System Default (config_definitions.default_value)
         │
         ▼
Program Level (config_values WHERE clinic_id IS NULL)
         │
         ▼
Clinic Level (config_values WHERE location_id IS NULL)
         │
         ▼
Location Level (config_values WHERE location_id IS NOT NULL)

* Lower levels override higher levels
* Empty = inherit from above
```

---

## Compliance Framework Coverage

| Framework | Coverage |
|-----------|----------|
| **21 CFR Part 11** | Unique user IDs, audit trail, electronic signatures (access grants) |
| **HIPAA** | Minimum necessary access, workforce training, BAA tracking |
| **SOC 2** | Access reviews, segregation of duties, change management |

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Single SQLite database | Simple deployment, no server needed, easy backup |
| MCP over REST API | Direct Claude integration, conversational interface |
| Preview mode default | Prevent accidental changes, review before commit |
| Excel for external | Universal format, clinic managers can edit |
| Inheritance model | Reduce duplication, single source of truth |
| Full audit trail | Compliance requirement, change tracking |

---

## Dependencies

| Package | Purpose |
|---------|---------|
| mcp | Model Context Protocol server |
| sqlite3 | Database access (built-in) |
| pandas | Excel reading/processing |
| openpyxl | Excel writing with formatting |
| python-docx | Word document parsing |

---

## Security Considerations

| Aspect | Implementation |
|--------|----------------|
| Database access | Local file, no network exposure |
| User authentication | Managed by Claude Desktop |
| Audit trail | All changes logged with who/when/why |
| Data at rest | SQLite file, standard OS permissions |
| PHI handling | Email/names only, no clinical data |

---

## Backup Strategy

```bash
# Daily backup command
cp ~/projects/data/client_product_database.db \
   ~/backups/propel_db_$(date +%Y%m%d).db

# Recommended: Automate via cron or launchd
```

---

## Future Considerations

### Planned: Onboarding Solution
- Client onboarding workflow automation
- Integration with configuration dashboard
- Checklist tracking
- Status visibility

### Potential Enhancements
- Web interface for clinic managers
- Automated review reminders
- Training assignment automation
- Multi-database support for scaling

---

*Last Updated: January 2025*
