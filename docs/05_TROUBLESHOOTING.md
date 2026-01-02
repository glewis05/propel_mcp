# Propel MCP Server - Troubleshooting Guide

## Quick Fixes

| Problem | Solution |
|---------|----------|
| Tools not appearing | Restart Claude Desktop (Cmd+Q, reopen) |
| "Tool not found" | Check MCP server is running |
| Import not working | Verify file path is correct |
| Changes not saving | Check preview_only is set to false |

---

# CONNECTION ISSUES

## MCP Server Not Responding

**Symptoms:**
- Tools don't appear in Claude
- "Tool not found" errors
- Timeout errors

**Solutions:**

1. **Restart Claude Desktop**
   - Cmd+Q to fully quit
   - Reopen Claude
   - Wait 10 seconds for MCP to initialize

2. **Check Server Status**
   ```bash
   # In terminal, check if server process is running
   ps aux | grep propel_mcp
   ```

3. **Check Server Logs**
   - Look in Claude Desktop logs for errors
   - Check ~/Library/Logs/Claude/ (macOS)

4. **Verify Configuration**
   - Check ~/Library/Application Support/Claude/claude_desktop_config.json
   - Ensure propel_mcp entry is correct

---

## Database Connection Errors

**Symptoms:**
- "Database not found"
- "Unable to connect to database"
- Empty results when data exists

**Solutions:**

1. **Verify Database Path**
   ```bash
   ls -la ~/projects/data/client_product_database.db
   ```

2. **Check Permissions**
   ```bash
   chmod 644 ~/projects/data/client_product_database.db
   ```

3. **Test Database**
   ```bash
   sqlite3 ~/projects/data/client_product_database.db "SELECT COUNT(*) FROM users;"
   ```

---

# IMPORT ERRORS

## "File not found"

**Cause:** Incorrect file path

**Solutions:**
1. Use full path: `~/Downloads/filename.xlsx`
2. Check filename spelling
3. Verify file exists:
   ```bash
   ls -la ~/Downloads/*.xlsx
   ```

---

## "Missing required columns"

**Cause:** Excel file doesn't have expected columns

**Required Columns for Access Roster:**
- First Name
- Last Name
- Program
- Access Level
- Email

**Optional Columns:**
- Job Role / Title
- Credentials
- Clinic (if clinic-specific access)

**Solutions:**
1. Check column headers match exactly (including spaces)
2. Remove trailing spaces from headers
3. Ensure "Email" column exists (not "E-mail" or "email address")

---

## "Program not found"

**Cause:** Program name doesn't match database

**Solutions:**
1. Check exact spelling:
   ```
   List programs
   ```
2. Try program prefix instead of full name
3. Check for typos in the Excel file

---

## "Clinic not found"

**Cause:** Clinic name doesn't match database

**Solutions:**
1. Check exact spelling:
   ```
   Show me [Program Name]
   ```
2. Try clinic code instead of full name
3. Verify clinic exists in the correct program

---

## Rows Skipped During Import

**Cause:** Rows without valid email addresses are skipped

**Solutions:**
1. Check for blank email cells
2. Verify email format (must contain @)
3. Remove instruction rows (headers, notes)

---

# EXPORT ERRORS

## "Permission denied"

**Cause:** Cannot write to output directory

**Solutions:**
1. Use default location (~/Downloads/)
2. Check directory permissions
3. Create directory if it doesn't exist

---

## Excel File Won't Open

**Cause:** File corruption or format issue

**Solutions:**
1. Try opening in different application
2. Re-export the file
3. Check file size (0 bytes = error during creation)

---

# DATA ISSUES

## "User not found"

**Cause:** Email doesn't exist in database

**Solutions:**
1. Check exact email spelling
2. Search with partial match:
   ```
   List users
   ```
3. User may have been imported under different email

---

## Duplicate Users

**Cause:** Same person imported multiple times with different emails

**Solutions:**
1. Identify duplicates:
   ```
   List users for [Clinic]
   ```
2. Manually merge or deactivate duplicates
3. Standardize email format before import

---

## Access Not Showing

**Cause:** Access may be inactive

**Solutions:**
1. Check user status:
   ```
   Get user [email]
   ```
2. Access may have been revoked
3. Check correct program/clinic filter

---

## Configuration Not Inheriting

**Cause:** Override exists at lower level

**Solutions:**
1. Check for overrides:
   ```
   What configs are overridden at [Clinic]?
   ```
2. Remove clinic-level override to inherit program default

---

# NOTION INTEGRATION

## Dashboard Not Updating

**Cause:** Notion API issue or page permissions

**Solutions:**
1. Verify Notion connection is active
2. Run push command again:
   ```
   Push dashboard to Notion
   ```
3. Refresh Notion page in browser
4. Check page wasn't deleted or moved

---

## "Page not found"

**Cause:** Dashboard page ID changed or deleted

**Solutions:**
1. Recreate dashboard page in Notion
2. Update NOTION_DASHBOARD_PAGE_ID in server.py
3. Restart Claude Desktop

---

# PERFORMANCE ISSUES

## Slow Queries

**Cause:** Large dataset or missing indexes

**Solutions:**
1. Add program/clinic filter to narrow results
2. Check database size
3. Vacuum database:
   ```bash
   sqlite3 ~/projects/data/client_product_database.db "VACUUM;"
   ```

---

## Memory Errors

**Cause:** Exporting too much data

**Solutions:**
1. Add filters to reduce dataset
2. Export in smaller batches
3. Close other applications

---

# COMMON ERROR MESSAGES

| Error | Cause | Solution |
|-------|-------|----------|
| "NoneType has no attribute" | Missing data in database | Check required fields exist |
| "Invalid date format" | Date not in YYYY-MM-DD | Fix date format in source file |
| "Foreign key constraint" | Referenced record doesn't exist | Create parent record first |
| "UNIQUE constraint failed" | Duplicate email | User already exists |
| "no such table" | Database schema incomplete | Run schema initialization |

---

# GETTING HELP

## Information to Gather

When reporting issues, collect:

1. **Exact command used**
2. **Complete error message**
3. **File details** (if import issue):
   - Column headers
   - Sample row (redact PII)
4. **Database state**:
   ```
   List programs
   List users
   ```

## Debug Mode

For detailed logging, check:
- Claude Desktop logs
- Terminal output if running manually

## Contact

- Review documentation in this package
- Check for updates to MCP server code
- Review database schema for data issues

---

*Last Updated: January 2025*
