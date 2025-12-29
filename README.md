# Propel Health MCP Server

Model Context Protocol (MCP) server that connects Claude to the Propel Health toolkits.

## Overview

This MCP server exposes tools from:
- **Configurations Toolkit**: User access, training, compliance, and system configurations
- **Requirements Toolkit**: User stories, UAT test cases, and traceability (future)

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
| `PROPEL_DB_PATH` | `~/projects/data/client_product_database.db` | Path to shared database |

## Available Tools

### User Management
- `list_users` - List users with optional filters (program, status, organization)

### Configuration Management
- *(Coming soon)*

### Compliance & Reporting
- *(Coming soon)*

## Development

```bash
# Run server directly for testing
python3 server.py

# Test MCP connection
# (Use Claude Desktop or MCP inspector)
```
