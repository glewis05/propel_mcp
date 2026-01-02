# Propel MCP Server Documentation

**Version:** 1.0  
**Last Updated:** January 2025

---

## 📚 Documentation Index

| Document | Description | When to Use |
|----------|-------------|-------------|
| [01_QUICK_REFERENCE.md](01_QUICK_REFERENCE.md) | One-page command reference | Daily use, quick lookups |
| [02_TOOL_REFERENCE.md](02_TOOL_REFERENCE.md) | Complete tool documentation | Learning tools, checking parameters |
| [03_WORKFLOW_GUIDE.md](03_WORKFLOW_GUIDE.md) | Step-by-step procedures | Common tasks, onboarding, reviews |
| [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md) | Database tables and relationships | Troubleshooting, custom queries |
| [05_TROUBLESHOOTING.md](05_TROUBLESHOOTING.md) | Common issues and solutions | When things go wrong |
| [06_ARCHITECTURE.md](06_ARCHITECTURE.md) | System design overview | Understanding how it works |

---

## 🚀 Quick Start

### Daily Compliance Check
```
Show me the compliance dashboard
```

### Import New Clinic Roster
```
Import roster at ~/Downloads/NewClinic_Roster.xlsx
```

### Send Access Review to Clinic
```
Export access review status for [Clinic Name]
```

### Update Notion Dashboard
```
Push dashboard to Notion
```

---

## 📁 Key File Locations

| Type | Path |
|------|------|
| MCP Server | ~/projects/propel_mcp/server.py |
| Access Manager | ~/projects/configurations_toolkit/managers/access_manager.py |
| Database | ~/projects/data/client_product_database.db |
| Exports | ~/Downloads/ |
| Documentation | (this folder) |

---

## 🔗 Key Links

| Resource | URL |
|----------|-----|
| Notion Dashboard | https://www.notion.so/2dab5d1d163181bb8eebc4f4397de747 |

---

## 📊 Tool Summary

| Category | Count | Examples |
|----------|-------|----------|
| User Management | 7 | list_users, import_access_roster |
| Compliance | 6 | export_review_status, get_expired_training |
| Dashboard | 3 | get_compliance_dashboard, push_dashboard_to_notion |
| Configuration | 7 | get_clinic_config, compare_clinic_configs |
| Programs/Clients | 4 | list_programs, get_client_programs |
| Requirements | 8 | list_stories, get_test_summary |
| **Total** | **~35+** | |

---

## ⚠️ Important Reminders

1. **Preview First**: Import tools default to preview mode. Add `preview_only false` to execute.

2. **Restart After Changes**: After code updates, restart Claude Desktop (Cmd+Q, reopen).

3. **Backup Regularly**: 
   ```bash
   cp ~/projects/data/client_product_database.db ~/backups/propel_db_$(date +%Y%m%d).db
   ```

4. **Check Dashboard Weekly**: Stay on top of overdue reviews and violations.

---

## 🆘 Getting Help

1. Check [Troubleshooting Guide](05_TROUBLESHOOTING.md)
2. Review [Tool Reference](02_TOOL_REFERENCE.md) for correct parameters
3. Verify database has expected data: `List programs` and `List users`

---

## 🔄 Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | January 2025 | Initial release with user management, compliance, config viewing |

---

*Propel Health MCP Server - Streamlining Healthcare Compliance*
