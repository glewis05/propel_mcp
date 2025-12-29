"""
Propel Health MCP Server
========================
Connects Claude to the Propel Health toolkits.
"""

# ============================================================
# IMPORTS
# ============================================================
import os

# MCP library
from mcp.server.fastmcp import FastMCP

# Import from configurations_toolkit (installed as editable package)
from configurations_toolkit import AccessManager

# ============================================================
# SERVER SETUP
# ============================================================
mcp = FastMCP("propel-health")

# Database path - use environment variable with sensible default
DB_PATH = os.environ.get(
    "PROPEL_DB_PATH",
    os.path.expanduser("~/projects/data/client_product_database.db")
)


# ============================================================
# TOOLS
# ============================================================

@mcp.tool()
def hello_propel() -> str:
    """
    Test function to verify MCP server is working.
    """
    return "Hello from Propel Health MCP Server! Connection successful."


@mcp.tool()
def list_users(
    program: str = None,
    status: str = None,
    organization: str = None
) -> str:
    """
    List users from the configurations database.
    
    Args:
        program: Filter by program (e.g., "Prevention4ME", "Precision4ME")
        status: Filter by status (e.g., "Active", "Inactive", "Terminated")
        organization: Filter by organization (e.g., "Providence", "Propel Health")
    
    Returns:
        Formatted list of users matching the criteria
    """
    try:
        # Create manager instance with database connection
        manager = AccessManager(db_path=DB_PATH)
        
        # Call the list_users method with correct parameter names
        users = manager.list_users(
            program_filter=program,
            status_filter=status,
            organization_filter=organization,
            include_access_count=True
        )
        
        # Close connection
        manager.close()
        
        # Format results
        if not users:
            return "No users found matching the criteria."
        
        # Build response
        result = f"Found {len(users)} user(s):\n\n"
        for user in users:
            result += f"• {user.get('name', 'Unknown')} ({user.get('email', 'No email')})\n"
            result += f"  Status: {user.get('status', 'Unknown')}\n"
            if user.get('organization'):
                result += f"  Organization: {user.get('organization')}\n"
            if user.get('active_access_count') is not None:
                result += f"  Access grants: {user.get('active_access_count')}\n"
            result += "\n"
        
        return result
        
    except Exception as e:
        return f"Error listing users: {str(e)}"


# ============================================================
# RUN SERVER
# ============================================================
if __name__ == "__main__":
    mcp.run()