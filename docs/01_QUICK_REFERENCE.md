# Propel MCP Server - Quick Reference Card

## 🚀 Daily Commands

### Compliance Dashboard
| Task | Command |
|------|---------|
| View dashboard | "Show me the compliance dashboard" |
| Push to Notion | "Push dashboard to Notion" |
| Export for stakeholders | "Export compliance dashboard" |

### Access Reviews
| Task | Command |
|------|---------|
| See what's due | "Get reviews due" |
| Export for clinic manager | "Export access review status for [Clinic]" |
| Export all (including current) | "Export access review status with include_current true" |
| Import completed review | "Import review response from ~/Downloads/[file].xlsx reviewed by [Manager Name]" |

### User Management
| Task | Command |
|------|---------|
| Import new roster | "Import roster at ~/Downloads/[file].xlsx" |
| Preview first | "Import roster at ~/Downloads/[file].xlsx" (default is preview) |
| Execute import | "Import roster at ~/Downloads/[file].xlsx with preview_only false" |
| List users | "List users" |
| Filter by program | "List users for Prevention4ME" |
| Filter by clinic | "List users for Franz Clinic" |
| Get user details | "Get user [email]" |

### Terminated User Audits
| Task | Command |
|------|---------|
| Full audit | "Export terminated user audit" |
| Since date | "Export terminated user audit since 2024-01-01" |

### Training
| Task | Command |
|------|---------|
| Check user training | "Get training status for [email]" |
| Expired training report | "Get expired training" |

---

## 🔧 Configuration Viewing

### Program Level
| Task | Command |
|------|---------|
| Program overview | "Show me Prevention4ME" |
| Export all configs | "Export configurations for P4M" |

### Clinic Level
| Task | Command |
|------|---------|
| View clinic config | "Show me Franz Clinic config" |
| See overrides only | "What configs are overridden at Franz?" |
| Compare two clinics | "Compare Franz and Kadlec" |
| List providers | "Who are the providers at Franz?" |
| List appointment types | "What appointment types does Franz have?" |

---

## 📊 Compliance Reports

| Report | Command |
|--------|---------|
| Access list | "Get compliance report access_list" |
| Review status | "Get compliance report review_status" |
| Training compliance | "Get compliance report training_compliance" |
| Terminated audit | "Get compliance report terminated_audit" |
| Business associates | "Get compliance report business_associates" |

---

## 📁 File Locations

| Type | Location |
|------|----------|
| Exports | ~/Downloads/ |
| Database | ~/projects/data/client_product_database.db |
| MCP Server | ~/projects/propel_mcp/server.py |
| Access Manager | ~/projects/configurations_toolkit/managers/access_manager.py |

---

## 🔄 Workflow Cheat Sheet

### New Clinic Onboarding
```
1. Import roster → "Import roster at ~/Downloads/[clinic]_roster.xlsx"
2. Preview → Review output
3. Execute → Same command with preview_only false
4. Verify → "List users for [Clinic]"
```

### Annual Access Review
```
1. Export → "Export access review status for [Clinic]"
2. Send Excel to clinic manager
3. Manager fills in Action/New Role/Manager Notes
4. Import → "Import review response from ~/Downloads/[file].xlsx reviewed by [Manager]"
5. Preview → Review output
6. Execute → Same command with preview_only false
```

### Compliance Check
```
1. Dashboard → "Show me the compliance dashboard"
2. Address issues:
   - Overdue reviews → Export and process
   - Violations → Investigate terminated users
   - Expired training → Follow up with users
3. Update Notion → "Push dashboard to Notion"
4. Stakeholder report → "Export compliance dashboard"
```

---

## ⚠️ Important Notes

- **Preview Mode**: Import tools default to preview (safe). Add `preview_only false` to execute.
- **Restart Required**: After code changes, restart Claude Desktop (Cmd+Q, reopen).
- **Notion Dashboard**: https://www.notion.so/2dab5d1d163181bb8eebc4f4397de747

---

*Last Updated: January 2025*
