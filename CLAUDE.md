# Propel MCP Server

## Project Purpose
Model Context Protocol (MCP) server that connects Claude to the Propel Health toolkits, enabling AI-assisted operations management.

## Owner Context
- Solo developer (no separate front-end/back-end team)
- Familiar with R, learning Python — explain Python concepts with R comparisons where helpful
- Aviation background — aviation analogies work well for complex concepts
- Prefers detailed explanations with heavy inline comments

## Code Standards

### Python Style
- Heavy inline comments explaining WHY, not just WHAT
- Every function needs a docstring with:
  - PURPOSE: What it does
  - PARAMETERS: Each param with type and example
  - RETURNS: What comes back, with example
- Use type hints for function signatures
- Prefer explicit over clever — readability beats brevity

### File Organization
```
propel_mcp/
├── server.py               # Main MCP server entry point
├── requirements.txt        # Dependencies
├── tools/                  # MCP tool implementations
│   ├── user_tools.py       # User management tools
│   ├── access_tools.py     # Access management tools
│   ├── config_tools.py     # Configuration tools
│   ├── requirements_tools.py # Requirements toolkit tools
│   ├── uat_tools.py        # UAT toolkit tools
│   └── roadmap_tools.py    # Roadmap tools
├── docs/                   # Documentation
└── uat_toolkit/            # UAT integration helpers
```

## Database Architecture

### Unified Database Design
All Propel Health toolkits share a **single unified database**:

| Location | Purpose |
|----------|---------|
| `~/projects/data/client_product_database.db` | Requirements, configurations, UAT, access management |

The MCP server connects directly to this database to expose tools from all toolkits.

### Toolkit Integration
This server imports from:
- **configurations_toolkit**: User access, training, compliance, and system configurations
- **requirements_toolkit**: User stories, UAT test cases, and traceability
- **uat_toolkit**: UAT cycle management and test execution

## Available Tool Categories

### User Management
- `hello_propel` - Test server connection
- `list_users` - List users with optional filters
- `get_user` - Get detailed user info
- `add_user` - Create a new user

### Access Management
- `list_access` - List access grants
- `get_reviews_due` - Show overdue access reviews
- `grant_access` - Grant access to a user
- `revoke_access` - Revoke access

### Training Management
- `get_training_status` - Get training status for a user
- `get_expired_training` - List users with expired training

### Compliance Reporting
- `get_compliance_report` - Generate compliance reports:
  - `access_list` - Who has access to what
  - `review_status` - Are access reviews current?
  - `training_compliance` - Training completion status
  - `terminated_audit` - Check for terminated users with access

### Configuration Management
- `list_programs` - List all programs with hierarchy
- `get_config` - Get a configuration value with inheritance info
- `set_config` - Set a configuration value

### Requirements Tools
- `list_user_stories` - List user stories
- `get_story_details` - Get full story with test cases
- `update_story_status` - Update story status

### UAT Tools
- `list_uat_cycles` - List UAT cycles
- `get_cycle_status` - Get cycle progress
- `update_test_result` - Record test execution result
- `import_notion_uat_results` - Import results from Notion export

### Roadmap Tools
- `create_roadmap_project` - Add a new project
- `update_roadmap_project` - Update project details
- `list_roadmap_projects` - List all projects
- `generate_roadmap_html` - Regenerate visualization
- `push_roadmap_to_github` - Deploy to GitHub Pages

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PROPEL_DB_PATH` | `~/projects/data/client_product_database.db` | Path to unified database |

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

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Install Propel Health toolkits as editable packages
pip install -e ../configurations_toolkit
pip install -e ../requirements_toolkit

# Run server directly for testing
python3 server.py
```

## Do NOT
- Modify database schema directly (use toolkit migrations)
- Skip audit logging for any data changes
- Expose raw SQL in tool responses
- Return sensitive data without proper filtering
