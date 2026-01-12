# Propel Health MCP Server

Model Context Protocol (MCP) server that connects Claude to the Propel Health toolkits.

## Overview

This MCP server connects to the **unified Propel Health database** and exposes tools from:
- **Configurations Toolkit**: User access, training, compliance, and system configurations
- **Requirements Toolkit**: User stories, UAT test cases, and traceability
- **UAT Toolkit**: UAT cycle management and test execution

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Install Propel Health toolkits as editable packages
pip install -e ../configurations_toolkit
pip install -e ../requirements_toolkit
```

## Configuration

Add to Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "propel-health": {
      "command": "python3",
      "args": ["/Users/glenlewis/projects/propel_mcp/server.py"]
    }
  }
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PROPEL_DB_PATH` | `~/projects/data/client_product_database.db` | Path to unified database |

## Database Architecture

All toolkits share a single unified database at `~/projects/data/client_product_database.db`:
- Programs (P4M, Px4M, ONB, etc.) are the central entity
- Contains requirements, user stories, test cases, configurations, and access management
- Other toolkits access via symlinks

## Available Tools

### User Management
- `hello_propel` - Test server connection
- `list_users` - List users with optional filters (program, status, organization)
- `get_user` - Get detailed info for a specific user by email
- `add_user` - Create a new user

### Access Management
- `list_access` - List access grants filtered by user or program
- `get_reviews_due` - Show overdue and upcoming access reviews

### Training Management
- `get_training_status` - Get training status for a specific user
- `get_expired_training` - List all users with expired training

### Compliance Reporting
- `get_compliance_report` - Generate compliance reports:
  - `access_list` - Who has access to what
  - `review_status` - Are access reviews current?
  - `training_compliance` - Training completion status
  - `terminated_audit` - Check for terminated users with access
  - `business_associates` - List of business associates

### Configuration Management
- `list_programs` - List all programs with clinic/location hierarchy
- `get_config` - Get a configuration value with inheritance info

## Development

```bash
# Run server directly for testing
python3 server.py

# Test MCP connection
# (Use Claude Desktop or MCP inspector)
```
