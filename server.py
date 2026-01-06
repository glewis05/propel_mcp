"""
Propel Health MCP Server
========================
Connects Claude to the Propel Health toolkits.

Available Tool Categories:

CONFIGURATIONS TOOLKIT:
- User Management: list_users, get_user, add_user, export_annual_review
- Access Management: list_access, get_reviews_due
- Training: get_training_status, get_expired_training
- Compliance: get_compliance_report
- Configuration: list_programs, get_config

REQUIREMENTS TOOLKIT:
- Client/Program: list_clients, get_client_programs, get_program_by_prefix
- User Stories: list_stories, get_story, get_approval_pipeline
- Test Cases: list_test_cases, get_test_summary
- Reporting: get_program_health, get_client_tree, search_stories, get_coverage_gaps
"""

# ============================================================
# IMPORTS
# ============================================================
import os
import sys
import csv
import importlib.util
from datetime import datetime, date, timedelta
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# MCP library
from mcp.server.fastmcp import FastMCP

# Import from configurations_toolkit (installed as editable package)
from configurations_toolkit import (
    AccessManager,
    ConfigurationManager,
    InheritanceManager,
    ComplianceReports,
)


# Load requirements_toolkit modules using importlib to avoid name conflicts
# (both toolkits have a 'database' module)
def _import_from_path(name: str, path: str):
    """Import a module from file path without polluting sys.modules."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        # Temporarily add parent path for internal imports
        parent = os.path.dirname(os.path.dirname(path))
        sys.path.insert(0, parent)
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(parent)
        return module
    raise ImportError(f"Could not load {path}")


_REQ_PATH = os.path.expanduser("~/projects/requirements_toolkit")
_req_db_manager = _import_from_path(
    "req_db_manager",
    os.path.join(_REQ_PATH, "database", "db_manager.py")
)
_req_queries_mod = _import_from_path(
    "req_queries_mod",
    os.path.join(_REQ_PATH, "database", "queries.py")
)

# Expose with cleaner names
ReqClientProductDatabase = _req_db_manager.ClientProductDatabase
req_queries = _req_queries_mod

# ============================================================
# SERVER SETUP
# ============================================================
mcp = FastMCP("propel-health")

# Database path - use environment variable with sensible default
DB_PATH = os.environ.get(
    "PROPEL_DB_PATH",
    os.path.expanduser("~/projects/data/client_product_database.db")
)

# Requirements database path
REQ_DB_PATH = os.environ.get(
    "REQUIREMENTS_DB_PATH",
    os.path.expanduser("~/projects/requirements_toolkit/data/client_product_database.db")
)

# Notion Dashboard Page ID (created by Claude)
NOTION_DASHBOARD_PAGE_ID = "2dab5d1d-1631-81bb-8eeb-c4f4397de747"


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_access_manager() -> AccessManager:
    """Create AccessManager instance with configured DB path."""
    return AccessManager(db_path=DB_PATH)


def get_config_manager() -> ConfigurationManager:
    """Create ConfigurationManager instance with configured DB path."""
    return ConfigurationManager(db_path=DB_PATH)


def get_req_database() -> ReqClientProductDatabase:
    """Create ClientProductDatabase instance with configured DB path."""
    return ReqClientProductDatabase(db_path=REQ_DB_PATH)


# ============================================================
# USER MANAGEMENT TOOLS
# ============================================================

@mcp.tool()
def hello_propel() -> str:
    """
    Test function to verify MCP server is working.
    """
    return "Hello from Propel Health MCP Server! Connection successful."


@mcp.tool()
def list_users(
    program: Optional[str] = None,
    status: Optional[str] = None,
    organization: Optional[str] = None,
    clinic: Optional[str] = None,
    location: Optional[str] = None
) -> str:
    """
    List users from the Propel Health database.

    Args:
        program: Filter by program name (e.g., "Prevention4ME")
        status: Filter by status ("Active", "Inactive", "Terminated")
        organization: Filter by organization name
        clinic: Filter by clinic name or code (e.g., "Franz", "FRANZ")
        location: Filter by location name or code (e.g., "Richland")

    Returns:
        Formatted list of users with their status and access count
    """
    manager = None
    try:
        manager = get_access_manager()

        # If clinic or location filter is provided, use get_access_by_scope
        if clinic or location:
            # Resolve program_id if provided
            program_id = None
            if program:
                try:
                    program_id = manager._resolve_program_id(program)
                except ValueError:
                    return f"Program not found: {program}"

            # Resolve clinic_id
            clinic_id = None
            if clinic:
                if not program_id:
                    # Need to find which program this clinic belongs to
                    conn = manager.conn
                    cursor = conn.execute(
                        "SELECT clinic_id, program_id FROM clinics WHERE name LIKE ? OR code LIKE ?",
                        (f"%{clinic}%", f"%{clinic.upper()}%")
                    )
                    row = cursor.fetchone()
                    if not row:
                        return f"Clinic not found: {clinic}"
                    clinic_id = row['clinic_id']
                    program_id = row['program_id']
                else:
                    try:
                        clinic_id = manager._resolve_clinic_id(clinic, program_id)
                    except ValueError:
                        return f"Clinic not found: {clinic}"

            # Resolve location_id
            location_id = None
            if location:
                if not clinic_id:
                    return "Location filter requires a clinic to be specified."
                try:
                    location_id = manager._resolve_location_id(location, clinic_id)
                except ValueError:
                    return f"Location not found: {location}"

            # Get users by scope
            access_list = manager.get_access_by_scope(
                program_id=program_id,
                clinic_id=clinic_id,
                location_id=location_id,
                active_only=True
            )

            # get_access_by_scope doesn't include user status, so fetch it separately
            if access_list:
                conn = manager.conn
                user_ids = list(set(a.get('user_id') for a in access_list if a.get('user_id')))
                if user_ids:
                    placeholders = ','.join(['?' for _ in user_ids])
                    cursor = conn.execute(
                        f"SELECT user_id, status FROM users WHERE user_id IN ({placeholders})",
                        user_ids
                    )
                    status_map = {row['user_id']: row['status'] for row in cursor.fetchall()}
                    for access in access_list:
                        access['status'] = status_map.get(access.get('user_id'))

            # Filter by status and organization if provided
            if status:
                access_list = [a for a in access_list if a.get('status') == status]
            if organization:
                access_list = [a for a in access_list
                              if organization.lower() in (a.get('organization') or '').lower()]

            if not access_list:
                return "No users found matching the criteria."

            # Deduplicate by user (a user might have multiple access grants)
            seen_users = {}
            for access in access_list:
                user_id = access.get('user_id')
                if user_id not in seen_users:
                    seen_users[user_id] = {
                        'name': access.get('user_name'),
                        'email': access.get('email'),
                        'status': access.get('status'),
                        'organization': access.get('organization'),
                        'roles': [access.get('role')],
                        'clinics': [access.get('clinic_name')] if access.get('clinic_name') else [],
                        'locations': [access.get('location_name')] if access.get('location_name') else []
                    }
                else:
                    if access.get('role') and access.get('role') not in seen_users[user_id]['roles']:
                        seen_users[user_id]['roles'].append(access.get('role'))
                    if access.get('clinic_name') and access.get('clinic_name') not in seen_users[user_id]['clinics']:
                        seen_users[user_id]['clinics'].append(access.get('clinic_name'))
                    if access.get('location_name') and access.get('location_name') not in seen_users[user_id]['locations']:
                        seen_users[user_id]['locations'].append(access.get('location_name'))

            users = list(seen_users.values())

            # Build filter description
            filters = []
            if program:
                filters.append(f"program={program}")
            if clinic:
                filters.append(f"clinic={clinic}")
            if location:
                filters.append(f"location={location}")
            if status:
                filters.append(f"status={status}")
            if organization:
                filters.append(f"org={organization}")
            filter_str = f" [{', '.join(filters)}]" if filters else ""

            result = f"Found {len(users)} user(s){filter_str}:\n\n"
            for user in users:
                result += f"• {user.get('name', 'Unknown')} ({user.get('email', 'No email')})\n"
                result += f"  Status: {user.get('status', 'Unknown')}"
                if user.get('organization'):
                    result += f" | Org: {user.get('organization')}"
                result += "\n"
                if user.get('roles'):
                    result += f"  Roles: {', '.join(user['roles'])}\n"
                if user.get('clinics'):
                    result += f"  Clinics: {', '.join(user['clinics'])}\n"

            return result

        else:
            # Use original list_users for non-clinic/location filters
            users = manager.list_users(
                program_filter=program,
                status_filter=status,
                organization_filter=organization,
                include_access_count=True
            )

            if not users:
                return "No users found matching the criteria."

            result = f"Found {len(users)} user(s):\n\n"
            for user in users:
                result += f"• {user.get('name', 'Unknown')} ({user.get('email', 'No email')})\n"
                result += f"  Status: {user.get('status', 'Unknown')}"
                if user.get('organization'):
                    result += f" | Org: {user.get('organization')}"
                if user.get('active_access_count') is not None:
                    result += f" | Access grants: {user.get('active_access_count')}"
                result += "\n"

            return result

    except Exception as e:
        return f"Error listing users: {str(e)}"
    finally:
        if manager:
            manager.close()


@mcp.tool()
def get_user(email: str) -> str:
    """
    Get detailed information about a specific user.

    Args:
        email: User's email address

    Returns:
        User details including status, organization, and access grants
    """
    manager = None
    try:
        manager = get_access_manager()
        user = manager.get_user(email=email)

        if not user:
            return f"User not found: {email}"

        # Get user's access grants
        access_list = manager.get_user_access(user['user_id'], active_only=False)

        # Get user's training status
        training = manager.get_training_status(user['user_id'])

        result = f"User: {user['name']}\n"
        result += f"Email: {user['email']}\n"
        result += f"Status: {user['status']}\n"
        result += f"Organization: {user.get('organization', 'N/A')}\n"
        result += f"Business Associate: {'Yes' if user.get('is_business_associate') else 'No'}\n"
        result += f"User ID: {user['user_id']}\n"

        if access_list:
            result += f"\nAccess Grants ({len(access_list)}):\n"
            for access in access_list:
                if access.get('is_active'):
                    result += f"  • {access.get('program_name', 'Unknown')} - {access.get('role')}"
                    if access.get('clinic_name'):
                        result += f" ({access.get('clinic_name')})"
                    result += "\n"

        if training:
            result += f"\nTraining Records ({len(training)}):\n"
            for t in training:
                result += f"  • {t.get('training_type')}: {t.get('status')}"
                if t.get('expires_date'):
                    result += f" (expires: {t.get('expires_date')})"
                result += "\n"

        return result

    except Exception as e:
        return f"Error getting user: {str(e)}"
    finally:
        if manager:
            manager.close()


@mcp.tool()
def add_user(
    name: str,
    email: str,
    organization: str = "Internal",
    is_business_associate: bool = False
) -> str:
    """
    Create a new user in the system.

    Args:
        name: Full name (e.g., "John Smith")
        email: Email address (must be unique)
        organization: Organization name (default: "Internal")
        is_business_associate: True if external party requiring HIPAA BAA

    Returns:
        Confirmation with new user's ID
    """
    manager = None
    try:
        manager = get_access_manager()

        # Check if user already exists
        existing = manager.get_user(email=email)
        if existing:
            return f"User already exists with email: {email}"

        user_id = manager.create_user(
            name=name,
            email=email,
            organization=organization,
            is_business_associate=is_business_associate
        )

        result = f"User created successfully!\n"
        result += f"  Name: {name}\n"
        result += f"  Email: {email}\n"
        result += f"  User ID: {user_id}\n"
        result += f"  Organization: {organization}\n"
        if is_business_associate:
            result += f"  Business Associate: Yes (HIPAA BAA required)\n"

        return result

    except Exception as e:
        return f"Error creating user: {str(e)}"
    finally:
        if manager:
            manager.close()


@mcp.tool()
def export_annual_review(
    program: Optional[str] = None,
    clinic: Optional[str] = None,
    location: Optional[str] = None,
    output_format: str = "csv",
    output_dir: Optional[str] = None
) -> str:
    """
    Generate an annual access review export for clinic managers.

    Creates a formatted spreadsheet for HIPAA annual access review compliance.
    Clinic managers can use this to review and confirm user access.

    Args:
        program: Filter by program name (e.g., "Prevention4ME")
        clinic: Filter by clinic name or code (e.g., "Franz", "FRANZ")
        location: Filter by location name or code (e.g., "Richland")
        output_format: Output format - "csv" or "xlsx" (default: "csv")
        output_dir: Directory to save the file (default: ~/Downloads)

    Returns:
        Path to the generated file and summary statistics
    """
    manager = None
    try:
        manager = get_access_manager()

        # Resolve filters
        program_id = None
        clinic_id = None
        location_id = None
        clinic_name = None

        if program:
            try:
                program_id = manager._resolve_program_id(program)
            except ValueError:
                return f"Program not found: {program}"

        if clinic:
            if not program_id:
                # Find which program this clinic belongs to
                conn = manager.conn
                cursor = conn.execute(
                    "SELECT clinic_id, program_id, name FROM clinics WHERE name LIKE ? OR code LIKE ?",
                    (f"%{clinic}%", f"%{clinic.upper()}%")
                )
                row = cursor.fetchone()
                if not row:
                    return f"Clinic not found: {clinic}"
                clinic_id = row['clinic_id']
                program_id = row['program_id']
                clinic_name = row['name']
            else:
                try:
                    clinic_id = manager._resolve_clinic_id(clinic, program_id)
                    # Get clinic name for file naming
                    conn = manager.conn
                    cursor = conn.execute("SELECT name FROM clinics WHERE clinic_id = ?", (clinic_id,))
                    row = cursor.fetchone()
                    clinic_name = row['name'] if row else clinic
                except ValueError:
                    return f"Clinic not found: {clinic}"

        if location:
            if not clinic_id:
                return "Location filter requires a clinic to be specified."
            try:
                location_id = manager._resolve_location_id(location, clinic_id)
            except ValueError:
                return f"Location not found: {location}"

        # Must have at least a program or clinic filter
        if not program_id and not clinic_id:
            return "Please specify at least a program or clinic filter."

        # Get access data
        access_list = manager.get_access_by_scope(
            program_id=program_id,
            clinic_id=clinic_id,
            location_id=location_id,
            active_only=True
        )

        if not access_list:
            return "No users found matching the criteria."

        # get_access_by_scope doesn't include user status, so fetch it separately
        conn = manager.conn
        user_ids = list(set(a.get('user_id') for a in access_list if a.get('user_id')))
        if user_ids:
            placeholders = ','.join(['?' for _ in user_ids])
            cursor = conn.execute(
                f"SELECT user_id, status FROM users WHERE user_id IN ({placeholders})",
                user_ids
            )
            status_map = {row['user_id']: row['status'] for row in cursor.fetchall()}
            for access in access_list:
                access['status'] = status_map.get(access.get('user_id'))

        # Get program name for file
        program_name = None
        if program_id:
            conn = manager.conn
            cursor = conn.execute("SELECT name FROM programs WHERE program_id = ?", (program_id,))
            row = cursor.fetchone()
            program_name = row['name'] if row else "Unknown"

        # Prepare export data
        export_rows = []
        for access in access_list:
            # Get last review date if available
            last_review = None
            try:
                conn = manager.conn
                cursor = conn.execute("""
                    SELECT MAX(review_date) as last_review
                    FROM access_reviews
                    WHERE access_id = ?
                """, (access.get('access_id'),))
                row = cursor.fetchone()
                if row and row['last_review']:
                    last_review = row['last_review']
            except Exception:
                pass

            export_rows.append({
                'Name': access.get('user_name', ''),
                'Email': access.get('email', ''),
                'Status': access.get('status', ''),
                'Role': access.get('role', ''),
                'Program': access.get('program_name', ''),
                'Clinic': access.get('clinic_name', ''),
                'Location': access.get('location_name', ''),
                'Access Granted': access.get('granted_date', ''),
                'Last Review Date': last_review or '',
                'Next Review Due': access.get('next_review_due', ''),
                'Review Action': '',  # For manager to fill in: Keep/Remove/Modify
                'Notes': ''  # For manager comments
            })

        # Generate filename
        today = datetime.now().strftime('%Y-%m-%d')
        if clinic_name:
            safe_name = clinic_name.replace(' ', '_').replace('/', '-')
            filename = f"{safe_name}_access_review_{today}"
        elif program_name:
            safe_name = program_name.replace(' ', '_').replace('/', '-')
            filename = f"{safe_name}_access_review_{today}"
        else:
            filename = f"access_review_{today}"

        # Determine output directory
        if output_dir:
            out_path = os.path.expanduser(output_dir)
        else:
            out_path = os.path.expanduser("~/Downloads")

        os.makedirs(out_path, exist_ok=True)

        # Generate the file
        if output_format.lower() == "xlsx":
            try:
                import openpyxl
                from openpyxl.styles import Font, Alignment, PatternFill

                filepath = os.path.join(out_path, f"{filename}.xlsx")
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Access Review"

                # Header row
                headers = list(export_rows[0].keys()) if export_rows else []
                header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
                header_font = Font(bold=True, color="FFFFFF")

                for col, header in enumerate(headers, 1):
                    cell = ws.cell(row=1, column=col, value=header)
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = Alignment(horizontal='center')

                # Data rows
                for row_num, row_data in enumerate(export_rows, 2):
                    for col, header in enumerate(headers, 1):
                        cell = ws.cell(row=row_num, column=col, value=row_data.get(header, ''))

                # Auto-adjust column widths
                for col in ws.columns:
                    max_length = 0
                    column = col[0].column_letter
                    for cell in col:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except Exception:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    ws.column_dimensions[column].width = adjusted_width

                # Add review action dropdown hint
                if export_rows:
                    ws.cell(row=1, column=len(headers) + 1, value="Review Actions: Keep / Remove / Modify")

                wb.save(filepath)

            except ImportError:
                return ("Excel export requires openpyxl. Install with: pip install openpyxl\n"
                        "Alternatively, use output_format='csv'")
        else:
            # CSV export
            filepath = os.path.join(out_path, f"{filename}.csv")
            headers = list(export_rows[0].keys()) if export_rows else []

            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(export_rows)

        # Build summary
        result = f"Annual Access Review Export Generated\n"
        result += f"{'=' * 50}\n\n"
        result += f"File: {filepath}\n"
        result += f"Format: {output_format.upper()}\n"
        result += f"Generated: {today}\n\n"

        result += f"Scope:\n"
        if program_name:
            result += f"  Program: {program_name}\n"
        if clinic_name:
            result += f"  Clinic: {clinic_name}\n"
        if location:
            result += f"  Location: {location}\n"

        result += f"\nStatistics:\n"
        result += f"  Total Users: {len(export_rows)}\n"

        # Count by status
        status_counts = {}
        role_counts = {}
        for row in export_rows:
            status = row.get('Status', 'Unknown')
            role = row.get('Role', 'Unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
            role_counts[role] = role_counts.get(role, 0) + 1

        result += f"  By Status:\n"
        for status, count in status_counts.items():
            result += f"    • {status}: {count}\n"

        result += f"  By Role:\n"
        for role, count in role_counts.items():
            result += f"    • {role}: {count}\n"

        result += f"\nWorkflow:\n"
        result += f"  1. Share this file with the clinic manager\n"
        result += f"  2. Manager reviews each user and fills in 'Review Action' column\n"
        result += f"  3. Collect marked-up spreadsheet and process changes\n"

        return result

    except Exception as e:
        return f"Error generating export: {str(e)}"
    finally:
        if manager:
            manager.close()


# ============================================================
# ACCESS MANAGEMENT TOOLS
# ============================================================

@mcp.tool()
def list_access(
    user_email: Optional[str] = None,
    program: Optional[str] = None
) -> str:
    """
    List access grants, optionally filtered by user or program.

    Args:
        user_email: Filter by user's email address
        program: Filter by program name

    Returns:
        List of access grants with roles and scope
    """
    manager = None
    try:
        manager = get_access_manager()

        user_id = None
        user_info = None
        if user_email:
            user = manager.get_user(email=user_email)
            if not user:
                return f"User not found: {user_email}"
            user_id = user['user_id']
            user_info = user  # Store for display

        # Get access based on filters provided
        if user_id:
            # User-specific access
            access_list = manager.get_user_access(user_id, active_only=True)
            # Filter by program if provided
            if program:
                try:
                    program_id = manager._resolve_program_id(program)
                    access_list = [a for a in access_list if a.get('program_id') == program_id]
                except ValueError:
                    return f"Program not found: {program}"
        elif program:
            # Scope-specific access
            try:
                program_id = manager._resolve_program_id(program)
                access_list = manager.get_access_by_scope(program_id=program_id, active_only=True)
            except ValueError:
                return f"Program not found: {program}"
        else:
            # No filters - get all access (scope-based with no filter)
            access_list = manager.get_access_by_scope(active_only=True)

        if not access_list:
            return "No access grants found matching the criteria."

        # Format results
        result = f"Found {len(access_list)} access grant(s):\n\n"

        # If user-specific query, show user header once
        if user_info:
            result += f"User: {user_info['name']} ({user_info['email']})\n\n"

        for access in access_list:
            status = "Active" if access.get('is_active') else "Revoked"
            # For scope-based queries, show user per access grant
            if not user_info:
                result += f"• {access.get('user_name', 'Unknown')} ({access.get('email', 'N/A')})\n"
            result += f"  Program: {access.get('program_name')} | Role: {access.get('role')} | Status: {status}\n"
            if access.get('clinic_name'):
                result += f"  Scope: {access.get('clinic_name')}"
                if access.get('location_name'):
                    result += f" > {access.get('location_name')}"
                result += "\n"
            if access.get('next_review_due'):
                result += f"  Next review: {access.get('next_review_due')}\n"
            result += "\n"

        return result

    except Exception as e:
        return f"Error listing access: {str(e)}"
    finally:
        if manager:
            manager.close()


@mcp.tool()
def get_reviews_due(program: Optional[str] = None) -> str:
    """
    Get access reviews that are overdue or due soon.

    Args:
        program: Filter by program name (optional)

    Returns:
        List of access grants needing review
    """
    manager = None
    try:
        manager = get_access_manager()

        program_id = None
        if program:
            try:
                program_id = manager._resolve_program_id(program)
            except ValueError:
                return f"Program not found: {program}"

        reviews = manager.get_reviews_due(program_id=program_id)

        if not reviews:
            return "No reviews are currently due. All access reviews are up to date!"

        overdue = [r for r in reviews if r.get('is_overdue')]
        due_soon = [r for r in reviews if not r.get('is_overdue')]

        result = f"Access Reviews Due: {len(reviews)} total\n\n"

        if overdue:
            result += f"OVERDUE ({len(overdue)}):\n"
            for r in overdue:
                result += f"  • {r.get('user_name')} - {r.get('program_name')} ({r.get('role')})\n"
                result += f"    Due: {r.get('next_review_due')} | Days overdue: {r.get('days_overdue')}\n"
            result += "\n"

        if due_soon:
            result += f"Due Soon ({len(due_soon)}):\n"
            for r in due_soon:
                result += f"  • {r.get('user_name')} - {r.get('program_name')} ({r.get('role')})\n"
                result += f"    Due: {r.get('next_review_due')}\n"

        return result

    except Exception as e:
        return f"Error getting reviews: {str(e)}"
    finally:
        if manager:
            manager.close()


# ============================================================
# TRAINING MANAGEMENT TOOLS
# ============================================================

@mcp.tool()
def get_training_status(user_email: str) -> str:
    """
    Get training status for a specific user.

    Args:
        user_email: User's email address

    Returns:
        List of training records with completion status
    """
    manager = None
    try:
        manager = get_access_manager()

        user = manager.get_user(email=user_email)
        if not user:
            return f"User not found: {user_email}"

        training = manager.get_training_status(user['user_id'])

        if not training:
            return f"No training records found for {user['name']}."

        result = f"Training Status for {user['name']}:\n\n"

        # Group by status
        current = [t for t in training if t.get('status') == 'Current']
        pending = [t for t in training if t.get('status') == 'Pending']
        expired = [t for t in training if t.get('status') == 'Expired']

        if current:
            result += f"Current ({len(current)}):\n"
            for t in current:
                result += f"  • {t.get('training_type')}"
                if t.get('expires_date'):
                    result += f" (expires: {t.get('expires_date')})"
                result += "\n"
            result += "\n"

        if pending:
            result += f"Pending ({len(pending)}):\n"
            for t in pending:
                result += f"  • {t.get('training_type')} (assigned: {t.get('assigned_date')})\n"
            result += "\n"

        if expired:
            result += f"Expired ({len(expired)}):\n"
            for t in expired:
                result += f"  • {t.get('training_type')} (expired: {t.get('expires_date')})\n"

        return result

    except Exception as e:
        return f"Error getting training status: {str(e)}"
    finally:
        if manager:
            manager.close()


@mcp.tool()
def get_expired_training() -> str:
    """
    Get all users with expired training that needs renewal.

    Returns:
        List of users and their expired training records
    """
    manager = None
    try:
        manager = get_access_manager()
        expired = manager.get_expired_training()

        if not expired:
            return "No expired training found. All training is current!"

        result = f"Expired Training: {len(expired)} record(s)\n\n"

        for record in expired:
            result += f"• {record.get('user_name')} ({record.get('user_email')})\n"
            result += f"  Training: {record.get('training_type')}\n"
            result += f"  Expired: {record.get('expires_date')}\n\n"

        return result

    except Exception as e:
        return f"Error getting expired training: {str(e)}"
    finally:
        if manager:
            manager.close()


# ============================================================
# COMPLIANCE REPORTING TOOLS
# ============================================================

@mcp.tool()
def get_compliance_report(
    report_type: str,
    program: Optional[str] = None
) -> str:
    """
    Generate a compliance report.

    Args:
        report_type: Type of report:
            - "access_list": Who has access to what
            - "review_status": Are access reviews current?
            - "training_compliance": Training completion status
            - "terminated_audit": Check for terminated users with access
            - "business_associates": List of business associates
        program: Filter by program name (optional)

    Returns:
        Formatted compliance report
    """
    valid_reports = [
        'access_list', 'review_status', 'training_compliance',
        'terminated_audit', 'business_associates'
    ]

    if report_type not in valid_reports:
        return f"Invalid report type. Choose from: {', '.join(valid_reports)}"

    manager = None
    try:
        manager = get_access_manager()
        reports = ComplianceReports(manager)

        program_id = None
        if program:
            try:
                program_id = manager._resolve_program_id(program)
            except ValueError:
                return f"Program not found: {program}"

        result = ""

        if report_type == 'access_list':
            data = reports.access_list_report(program_id=program_id)
            result = f"Access List Report\n"
            result += f"==================\n\n"
            result += f"Total Users: {data['summary']['total_users']}\n"
            result += f"Total Access Grants: {data['summary']['total_access_grants']}\n\n"

            # Group by user for cleaner display
            users_seen = set()
            for access in data.get('access_list', [])[:50]:  # Limit to 50 entries
                user_key = access.get('user_id')
                if user_key not in users_seen:
                    result += f"• {access.get('user_name')} ({access.get('email')})\n"
                    users_seen.add(user_key)
                result += f"  - {access.get('program_name')}: {access.get('role')}\n"

            if len(data.get('access_list', [])) > 50:
                result += f"\n... and {len(data['access_list']) - 50} more access grants\n"

        elif report_type == 'review_status':
            data = reports.review_status_report(program_id=program_id)
            result = f"Access Review Status\n"
            result += f"====================\n\n"
            result += f"Current: {data['summary']['current']}\n"
            result += f"Due Soon: {data['summary']['due_soon']}\n"
            result += f"Overdue: {data['summary']['overdue']}\n"

            if data['summary']['overdue'] > 0:
                result += f"\nAction Required: {data['summary']['overdue']} overdue reviews\n"

        elif report_type == 'training_compliance':
            data = reports.training_compliance_report()
            result = f"Training Compliance Report\n"
            result += f"==========================\n\n"
            result += f"Total Users: {data['summary']['total_users']}\n"
            result += f"Fully Compliant: {data['summary']['compliant']}\n"
            result += f"Missing Training: {data['summary']['missing_training']}\n"
            result += f"Expired Training: {data['summary']['expired_training']}\n"

        elif report_type == 'terminated_audit':
            data = reports.terminated_user_audit()
            result = f"Terminated User Audit\n"
            result += f"=====================\n\n"

            if not data.get('violations'):
                result += "No issues found. All terminated users have had access revoked.\n"
            else:
                result += f"VIOLATIONS FOUND: {len(data['violations'])}\n\n"
                for v in data['violations']:
                    result += f"• {v.get('user_name')} - still has {v.get('active_grants')} active grant(s)\n"

        elif report_type == 'business_associates':
            data = reports.business_associate_report()
            result = f"Business Associates Report\n"
            result += f"==========================\n\n"
            result += f"Total External Users: {data['summary']['total_external_users']}\n"
            result += f"Organizations: {data['summary']['organizations']}\n"
            result += f"Total Access Grants: {data['summary']['total_access_grants']}\n\n"

            for ba in data.get('all_external_users', []):
                result += f"• {ba.get('name')} ({ba.get('organization')})\n"
                result += f"  Email: {ba.get('email')} | Programs: {ba.get('programs')}\n\n"

        return result

    except Exception as e:
        return f"Error generating report: {str(e)}"
    finally:
        if manager:
            manager.close()


# ============================================================
# CONFIGURATION MANAGEMENT TOOLS
# ============================================================

@mcp.tool()
def list_programs() -> str:
    """
    List all programs with their clinic and location hierarchy.

    Returns:
        Formatted hierarchy of programs, clinics, and locations
    """
    cm = None
    try:
        cm = get_config_manager()
        programs = cm.list_programs()

        if not programs:
            return "No programs found in the database."

        result = "Programs:\n"
        result += "=========\n\n"

        for program in programs:
            result += f"[{program.get('prefix')}] {program.get('name')}\n"
            result += f"   Type: {program.get('program_type')} | Status: {program.get('status')}\n"

            clinics = program.get('clinics', [])
            if clinics:
                for clinic in clinics:
                    result += f"   +-- {clinic.get('name')}"
                    if clinic.get('code'):
                        result += f" [{clinic.get('code')}]"
                    result += "\n"

                    locations = clinic.get('locations', [])
                    for loc in locations:
                        result += f"       +-- {loc.get('name')}"
                        if loc.get('code'):
                            result += f" [{loc.get('code')}]"
                        result += "\n"

            result += "\n"

        return result

    except Exception as e:
        return f"Error listing programs: {str(e)}"
    finally:
        if cm:
            cm.close()


@mcp.tool()
def get_config(
    config_key: str,
    program: str,
    clinic: Optional[str] = None,
    location: Optional[str] = None
) -> str:
    """
    Get a configuration value with inheritance information.

    Args:
        config_key: Configuration key (e.g., "helpdesk_phone", "hours_open")
        program: Program prefix (e.g., "P4M")
        clinic: Clinic name (optional)
        location: Location name (optional, requires clinic)

    Returns:
        Configuration value with source and inheritance chain
    """
    cm = None
    try:
        cm = get_config_manager()
        im = InheritanceManager(cm)

        # Resolve IDs
        program_id = cm.get_program_id(program)
        if not program_id:
            return f"Program not found: {program}"

        clinic_id = None
        if clinic:
            clinic_id = cm.get_clinic_id(program_id, clinic)
            if not clinic_id:
                return f"Clinic not found: {clinic}"

        location_id = None
        if location:
            if not clinic_id:
                return "Location requires clinic to be specified"
            location_id = cm.get_location_id(clinic_id, location)
            if not location_id:
                return f"Location not found: {location}"

        # Get config with inheritance
        config = im.resolve_with_inheritance(
            config_key, program_id, clinic_id, location_id
        )

        if not config:
            return f"Configuration not found: {config_key}"

        result = f"Configuration: {config_key}\n"
        result += f"{'=' * 40}\n\n"
        result += f"Effective Value: {config.get('value', '(not set)')}\n"
        result += f"Set At: {config.get('effective_level', 'default')}\n"
        result += f"Is Override: {'Yes' if config.get('is_override') else 'No'}\n"

        chain = config.get('inheritance_chain', [])
        if chain:
            result += f"\nInheritance Chain:\n"
            for level in chain:
                marker = ">" if level.get('is_effective') else " "
                override = "*" if level.get('is_override') else ""
                result += f"  {marker} {level.get('level')}: {level.get('value', '(inherited)')}{override}\n"

        return result

    except Exception as e:
        return f"Error getting config: {str(e)}"
    finally:
        if cm:
            cm.close()


# ============================================================
# REQUIREMENTS TOOLKIT - CLIENT/PROGRAM TOOLS
# ============================================================

@mcp.tool()
def list_clients(status: Optional[str] = "Active") -> str:
    """
    List all clients in the requirements database.

    Args:
        status: Filter by status ("Active", "Inactive", or None for all)

    Returns:
        Formatted list of clients
    """
    db = None
    try:
        db = get_req_database()
        clients = db.list_clients(status_filter=status)

        if not clients:
            return "No clients found."

        result = f"Found {len(clients)} client(s):\n\n"
        for client in clients:
            result += f"• {client['name']}\n"
            result += f"  ID: {client['client_id']} | Status: {client['status']}\n"
            if client.get('description'):
                result += f"  Description: {client['description']}\n"
            if client.get('primary_contact'):
                result += f"  Contact: {client['primary_contact']}"
                if client.get('contact_email'):
                    result += f" ({client['contact_email']})"
                result += "\n"
            result += "\n"

        return result

    except Exception as e:
        return f"Error listing clients: {str(e)}"
    finally:
        if db:
            db.close()


@mcp.tool()
def get_client_programs(client_name: str) -> str:
    """
    Get all programs for a specific client.

    Args:
        client_name: Name of the client

    Returns:
        List of programs with story/test counts
    """
    db = None
    try:
        db = get_req_database()
        client = db.get_client_by_name(client_name)
        if not client:
            return f"Client not found: {client_name}"

        programs = db.list_programs(client_id=client['client_id'], status_filter=None)

        if not programs:
            return f"No programs found for {client_name}."

        result = f"Programs for {client_name}:\n\n"
        for prog in programs:
            summary = db.get_program_summary(prog['program_id'])
            result += f"[{prog['prefix']}] {prog['name']}\n"
            result += f"  Status: {prog['status']}"
            if prog.get('program_type'):
                result += f" | Type: {prog['program_type']}"
            result += "\n"
            result += f"  Stories: {summary['story_count']} | Tests: {summary['test_count']} | Requirements: {summary['requirement_count']}\n"
            if summary.get('stories_by_status'):
                approved = summary['stories_by_status'].get('Approved', 0)
                result += f"  Approved stories: {approved}\n"
            result += "\n"

        return result

    except Exception as e:
        return f"Error getting programs: {str(e)}"
    finally:
        if db:
            db.close()


@mcp.tool()
def get_program_by_prefix(prefix: str) -> str:
    """
    Get detailed information about a program by its prefix.

    Args:
        prefix: Program prefix (e.g., "PROP", "GRX")

    Returns:
        Program details with summary statistics
    """
    db = None
    try:
        db = get_req_database()
        program = db.get_program_by_prefix(prefix.upper())

        if not program:
            return f"Program not found with prefix: {prefix}"

        summary = db.get_program_summary(program['program_id'])

        result = f"Program: {program['name']} [{program['prefix']}]\n"
        result += f"{'=' * 50}\n\n"
        result += f"ID: {program['program_id']}\n"
        result += f"Status: {program['status']}\n"
        if program.get('program_type'):
            result += f"Type: {program['program_type']}\n"
        if program.get('description'):
            result += f"Description: {program['description']}\n"
        if program.get('source_file'):
            result += f"Source: {program['source_file']}\n"

        result += f"\nStatistics:\n"
        result += f"  Requirements: {summary['requirement_count']}\n"
        result += f"  User Stories: {summary['story_count']}\n"
        result += f"  Test Cases: {summary['test_count']}\n"

        if summary.get('stories_by_status'):
            result += f"\nStories by Status:\n"
            for status, count in summary['stories_by_status'].items():
                result += f"  • {status}: {count}\n"

        if summary.get('tests_by_status'):
            result += f"\nTests by Status:\n"
            for status, count in summary['tests_by_status'].items():
                result += f"  • {status}: {count}\n"

        if summary.get('coverage'):
            cov = summary['coverage']
            result += f"\nCoverage:\n"
            result += f"  Full: {cov.get('full_pct', 0)}% | Partial: {cov.get('partial_pct', 0)}% | None: {cov.get('none_pct', 0)}%\n"

        return result

    except Exception as e:
        return f"Error getting program: {str(e)}"
    finally:
        if db:
            db.close()


# ============================================================
# REQUIREMENTS TOOLKIT - USER STORY TOOLS
# ============================================================

@mcp.tool()
def list_stories(
    program_prefix: str,
    status: Optional[str] = None,
    category: Optional[str] = None
) -> str:
    """
    List user stories for a program.

    Args:
        program_prefix: Program prefix (e.g., "PROP")
        status: Filter by status (Draft, Approved, etc.)
        category: Filter by category

    Returns:
        List of user stories
    """
    db = None
    try:
        db = get_req_database()
        program = db.get_program_by_prefix(program_prefix.upper())

        if not program:
            return f"Program not found: {program_prefix}"

        stories = db.get_stories(
            program_id=program['program_id'],
            status_filter=status,
            category_filter=category
        )

        if not stories:
            filters = []
            if status:
                filters.append(f"status={status}")
            if category:
                filters.append(f"category={category}")
            filter_str = f" (filters: {', '.join(filters)})" if filters else ""
            return f"No stories found for {program_prefix}{filter_str}."

        result = f"User Stories for {program['name']} [{program_prefix}]:\n"
        result += f"Found {len(stories)} story(ies)\n\n"

        for story in stories[:50]:  # Limit display
            result += f"[{story['story_id']}] {story.get('title', 'Untitled')}\n"
            result += f"  Status: {story['status']} | Priority: {story.get('priority', 'N/A')}"
            if story.get('category'):
                result += f" | Category: {story['category']}"
            result += "\n"

        if len(stories) > 50:
            result += f"\n... and {len(stories) - 50} more stories\n"

        return result

    except Exception as e:
        return f"Error listing stories: {str(e)}"
    finally:
        if db:
            db.close()


@mcp.tool()
def get_story(story_id: str) -> str:
    """
    Get detailed information about a specific user story.

    Args:
        story_id: The story ID (e.g., "PROP-AUTH-001")

    Returns:
        Full story details including acceptance criteria
    """
    db = None
    try:
        db = get_req_database()
        conn = db.get_connection()

        cursor = conn.execute(
            "SELECT * FROM user_stories WHERE story_id = ?",
            (story_id,)
        )
        row = cursor.fetchone()

        if not row:
            return f"Story not found: {story_id}"

        story = dict(row)

        result = f"Story: {story['story_id']}\n"
        result += f"{'=' * 50}\n\n"
        result += f"Title: {story.get('title', 'N/A')}\n"
        result += f"Status: {story['status']} | Version: {story.get('version', 1)}\n"
        result += f"Priority: {story.get('priority', 'N/A')}\n"
        if story.get('category'):
            result += f"Category: {story['category']}"
            if story.get('category_full'):
                result += f" ({story['category_full']})"
            result += "\n"

        if story.get('user_story'):
            result += f"\nUser Story:\n{story['user_story']}\n"

        if story.get('acceptance_criteria'):
            result += f"\nAcceptance Criteria:\n"
            criteria = story['acceptance_criteria'].split('\n')
            for i, ac in enumerate(criteria, 1):
                if ac.strip():
                    result += f"  {i}. {ac.strip()}\n"

        if story.get('success_metrics'):
            result += f"\nSuccess Metrics: {story['success_metrics']}\n"

        if story.get('approved_date'):
            result += f"\nApproved: {story['approved_date']}"
            if story.get('approved_by'):
                result += f" by {story['approved_by']}"
            result += "\n"

        return result

    except Exception as e:
        return f"Error getting story: {str(e)}"
    finally:
        if db:
            db.close()


@mcp.tool()
def get_approval_pipeline(program_prefix: str) -> str:
    """
    Get Kanban-style view of story workflow status.

    Args:
        program_prefix: Program prefix (e.g., "PROP")

    Returns:
        Stories grouped by workflow status
    """
    db = None
    try:
        db = get_req_database()
        program = db.get_program_by_prefix(program_prefix.upper())

        if not program:
            return f"Program not found: {program_prefix}"

        pipeline = req_queries.get_approval_pipeline(db, program['program_id'])

        result = f"Approval Pipeline for {program['name']}:\n"
        result += f"{'=' * 50}\n\n"

        for status, stories in pipeline.items():
            result += f"{status} ({len(stories)}):\n"
            if stories:
                for story in stories[:5]:
                    result += f"  • [{story['story_id']}] {story['title'][:40]}\n"
                if len(stories) > 5:
                    result += f"  ... and {len(stories) - 5} more\n"
            else:
                result += "  (none)\n"
            result += "\n"

        return result

    except Exception as e:
        return f"Error getting pipeline: {str(e)}"
    finally:
        if db:
            db.close()


# ============================================================
# REQUIREMENTS TOOLKIT - TEST CASE TOOLS
# ============================================================

@mcp.tool()
def list_test_cases(
    program_prefix: str,
    status: Optional[str] = None,
    test_type: Optional[str] = None
) -> str:
    """
    List UAT test cases for a program.

    Args:
        program_prefix: Program prefix (e.g., "PROP")
        status: Filter by status (Not Run, Pass, Fail, Blocked, Skipped)
        test_type: Filter by type (happy_path, negative, validation, edge_case)

    Returns:
        List of test cases
    """
    db = None
    try:
        db = get_req_database()
        program = db.get_program_by_prefix(program_prefix.upper())

        if not program:
            return f"Program not found: {program_prefix}"

        tests = db.get_test_cases(
            program_id=program['program_id'],
            status_filter=status,
            test_type=test_type
        )

        if not tests:
            return f"No test cases found for {program_prefix}."

        result = f"Test Cases for {program['name']} [{program_prefix}]:\n"
        result += f"Found {len(tests)} test(s)\n\n"

        for test in tests[:30]:
            result += f"[{test['test_id']}] {test.get('title', 'Untitled')}\n"
            result += f"  Status: {test.get('test_status', 'Not Run')} | Type: {test.get('test_type', 'N/A')}\n"

        if len(tests) > 30:
            result += f"\n... and {len(tests) - 30} more tests\n"

        return result

    except Exception as e:
        return f"Error listing tests: {str(e)}"
    finally:
        if db:
            db.close()


@mcp.tool()
def get_test_summary(program_prefix: str) -> str:
    """
    Get test execution summary for a program.

    Args:
        program_prefix: Program prefix (e.g., "PROP")

    Returns:
        Test execution statistics including pass/fail rates
    """
    db = None
    try:
        db = get_req_database()
        program = db.get_program_by_prefix(program_prefix.upper())

        if not program:
            return f"Program not found: {program_prefix}"

        summary = req_queries.get_test_execution_summary(db, program['program_id'])

        result = f"Test Execution Summary for {program['name']}:\n"
        result += f"{'=' * 50}\n\n"
        result += f"Total Tests: {summary['total']}\n"
        result += f"Execution Rate: {summary['execution_rate']}%\n"
        result += f"Pass Rate: {summary['pass_rate']}%\n\n"

        result += "By Status:\n"
        for status, count in summary['by_status'].items():
            result += f"  • {status}: {count}\n"

        if summary['by_type']:
            result += "\nBy Test Type:\n"
            for test_type, data in summary['by_type'].items():
                result += f"  {test_type}: {data['total']} total"
                if data.get('Pass'):
                    result += f", {data['Pass']} passed"
                if data.get('Fail'):
                    result += f", {data['Fail']} failed"
                result += "\n"

        return result

    except Exception as e:
        return f"Error getting test summary: {str(e)}"
    finally:
        if db:
            db.close()


# ============================================================
# REQUIREMENTS TOOLKIT - REPORTING TOOLS
# ============================================================

@mcp.tool()
def get_program_health(program_prefix: str) -> str:
    """
    Get health score and recommendations for a program.

    Args:
        program_prefix: Program prefix (e.g., "PROP")

    Returns:
        Health score (0-100), grade, and recommendations
    """
    db = None
    try:
        db = get_req_database()
        program = db.get_program_by_prefix(program_prefix.upper())

        if not program:
            return f"Program not found: {program_prefix}"

        health = req_queries.get_program_health_score(db, program['program_id'])

        result = f"Program Health: {program['name']}\n"
        result += f"{'=' * 50}\n\n"
        result += f"Overall Score: {health['score']}/100 (Grade: {health['grade']})\n\n"

        result += "Component Scores:\n"
        for name, data in health['components'].items():
            bar = "█" * (data['score'] // 10) + "░" * (10 - data['score'] // 10)
            result += f"  {name}: {bar} {data['score']}% (weight: {int(data['weight']*100)}%)\n"

        if health['recommendations']:
            result += f"\nRecommendations:\n"
            for rec in health['recommendations']:
                result += f"  • {rec}\n"

        return result

    except Exception as e:
        return f"Error getting health score: {str(e)}"
    finally:
        if db:
            db.close()


@mcp.tool()
def get_client_tree() -> str:
    """
    Get hierarchical view of all clients and their programs.

    Returns:
        Tree view: Clients → Programs with story/test counts
    """
    db = None
    try:
        db = get_req_database()
        tree = req_queries.get_client_program_tree(db)

        if not tree:
            return "No clients found in the database."

        result = "Client/Program Hierarchy:\n"
        result += "=" * 50 + "\n\n"

        for client in tree:
            result += f"📁 {client['name']}\n"
            programs = client.get('programs', [])
            if programs:
                for i, prog in enumerate(programs):
                    prefix = "└──" if i == len(programs) - 1 else "├──"
                    result += f"   {prefix} [{prog['prefix']}] {prog['name']}\n"
                    result += f"       Stories: {prog['story_count']} ({prog['approved_count']} approved) | Tests: {prog['test_count']}\n"
            else:
                result += "   (no programs)\n"
            result += "\n"

        return result

    except Exception as e:
        return f"Error getting client tree: {str(e)}"
    finally:
        if db:
            db.close()


@mcp.tool()
def search_stories(keyword: str) -> str:
    """
    Search for stories across all programs by keyword.

    Args:
        keyword: Search term to find in title, story, or acceptance criteria

    Returns:
        Matching stories with program context
    """
    db = None
    try:
        db = get_req_database()
        results = req_queries.search_stories_global(db, keyword)

        if not results:
            return f"No stories found matching: {keyword}"

        result = f"Search Results for '{keyword}':\n"
        result += f"Found {len(results)} matching story(ies)\n\n"

        for story in results:
            result += f"[{story['story_id']}] {story['title']}\n"
            result += f"  Program: {story['program_name']} [{story['prefix']}] | Client: {story['client_name']}\n"
            result += f"  Status: {story['status']} | Priority: {story.get('priority', 'N/A')}\n\n"

        return result

    except Exception as e:
        return f"Error searching stories: {str(e)}"
    finally:
        if db:
            db.close()


@mcp.tool()
def get_coverage_gaps(program_prefix: str) -> str:
    """
    Find requirements without stories and stories without tests.

    Args:
        program_prefix: Program prefix (e.g., "PROP")

    Returns:
        List of coverage gaps
    """
    db = None
    try:
        db = get_req_database()
        program = db.get_program_by_prefix(program_prefix.upper())

        if not program:
            return f"Program not found: {program_prefix}"

        orphan_reqs = req_queries.get_orphan_requirements(db, program['program_id'])
        untested_stories = req_queries.get_stories_without_tests(db, program['program_id'])

        result = f"Coverage Gaps for {program['name']}:\n"
        result += "=" * 50 + "\n\n"

        result += f"Requirements without Stories ({len(orphan_reqs)}):\n"
        if orphan_reqs:
            for req in orphan_reqs[:10]:
                result += f"  • [{req['requirement_id']}] {req.get('title', req.get('description', '')[:50])}\n"
            if len(orphan_reqs) > 10:
                result += f"  ... and {len(orphan_reqs) - 10} more\n"
        else:
            result += "  None - all requirements have stories!\n"

        result += f"\nApproved Stories without Tests ({len(untested_stories)}):\n"
        if untested_stories:
            for story in untested_stories[:10]:
                result += f"  • [{story['story_id']}] {story.get('title', 'Untitled')}\n"
            if len(untested_stories) > 10:
                result += f"  ... and {len(untested_stories) - 10} more\n"
        else:
            result += "  None - all approved stories have tests!\n"

        return result

    except Exception as e:
        return f"Error getting coverage gaps: {str(e)}"
    finally:
        if db:
            db.close()


# ============================================================
# EXCEL EXPORT HELPER FUNCTIONS
# ============================================================

def _create_review_status_excel(rows: list, output_dir: str, filename: str) -> str:
    """Create formatted Excel file for review status report with manager response columns."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Review Status"

    # Styles
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    overdue_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    due_soon_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
    response_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")  # Light green for response columns
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    if rows:
        # Add manager response columns to each row
        for row in rows:
            row['Action'] = ''  # Blank = Keep, or "Terminate" or "Update"
            row['New Role'] = ''  # Only if Action = Update
            row['Manager Notes'] = ''  # Reason for change

        headers = list(rows[0].keys())

        # Find which columns are response columns
        response_cols = ['Action', 'New Role', 'Manager Notes']

        # Write headers
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = thin_border

        # Write data rows
        for row_num, row_data in enumerate(rows, 2):
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=row_num, column=col, value=row_data.get(header, ''))
                cell.border = thin_border

                # Apply status-based highlighting to non-response columns
                if header not in response_cols:
                    if row_data.get('Review Status') == 'OVERDUE':
                        cell.fill = overdue_fill
                    elif row_data.get('Review Status') == 'Due Soon':
                        cell.fill = due_soon_fill
                else:
                    # Light green background for response columns (to fill in)
                    cell.fill = response_fill

        # Auto-adjust column widths
        for col in range(1, len(headers) + 1):
            max_length = 0
            column_letter = get_column_letter(col)
            for row in range(1, len(rows) + 2):
                try:
                    cell_value = ws.cell(row=row, column=col).value
                    if cell_value:
                        max_length = max(max_length, len(str(cell_value)))
                except:
                    pass
            ws.column_dimensions[column_letter].width = min(max_length + 2, 40)

        # Make response columns wider for easier data entry
        for col, header in enumerate(headers, 1):
            if header in response_cols:
                ws.column_dimensions[get_column_letter(col)].width = 20

    # Add instructions sheet
    instructions_ws = wb.create_sheet("Instructions")
    instructions_ws['A1'] = "Annual Access Review Instructions"
    instructions_ws['A1'].font = Font(bold=True, size=14)
    instructions_ws['A3'] = "For each user, review their access and fill in the green columns:"
    instructions_ws['A5'] = "ACTION Column:"
    instructions_ws['B5'] = "Leave BLANK to keep current access (recertify)"
    instructions_ws['B6'] = "Enter 'Terminate' to revoke access"
    instructions_ws['B7'] = "Enter 'Update' to change their role"
    instructions_ws['A9'] = "NEW ROLE Column (only if Action = Update):"
    instructions_ws['B9'] = "Read-Write-Order"
    instructions_ws['B10'] = "Read-Write"
    instructions_ws['B11'] = "Read-Only"
    instructions_ws['A13'] = "MANAGER NOTES Column:"
    instructions_ws['B13'] = "Required for Terminate or Update actions"
    instructions_ws['B14'] = "Example: 'Left organization', 'Role change per manager request'"
    instructions_ws['A16'] = "When complete, save the file and send back for import."
    instructions_ws.column_dimensions['A'].width = 35
    instructions_ws.column_dimensions['B'].width = 50

    # Freeze header row on main sheet
    ws.freeze_panes = 'A2'

    filepath = os.path.join(output_dir, f"{filename}.xlsx")
    wb.save(filepath)
    return filepath


def _create_terminated_audit_excel(rows: list, output_dir: str, filename: str, violations_count: int) -> str:
    """Create formatted Excel file for terminated user audit."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Terminated Audit"

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    violation_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    compliant_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    if rows:
        headers = list(rows[0].keys())
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = thin_border

        for row_num, row_data in enumerate(rows, 2):
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=row_num, column=col, value=row_data.get(header, ''))
                cell.border = thin_border
                compliance_status = row_data.get('Compliance Status', '')
                if 'VIOLATION' in compliance_status:
                    cell.fill = violation_fill
                elif 'Compliant' in compliance_status:
                    cell.fill = compliant_fill
                if header == 'Access Still Active' and 'VIOLATION' in str(row_data.get(header, '')):
                    cell.fill = violation_fill
                    cell.font = Font(bold=True, color="9C0006")

        for col in range(1, len(headers) + 1):
            max_length = 0
            column_letter = get_column_letter(col)
            for row in range(1, len(rows) + 2):
                try:
                    cell_value = ws.cell(row=row, column=col).value
                    if cell_value:
                        max_length = max(max_length, len(str(cell_value)))
                except:
                    pass
            ws.column_dimensions[column_letter].width = min(max_length + 2, 40)

    ws.freeze_panes = 'A2'

    summary_ws = wb.create_sheet("Summary")
    summary_ws['A1'] = "Terminated User Audit Summary"
    summary_ws['A1'].font = Font(bold=True, size=14)
    summary_ws['A3'] = "Generated:"
    summary_ws['B3'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    summary_ws['A4'] = "Total Users:"
    summary_ws['B4'] = len(set(r.get('Email') for r in rows if r.get('Email')))
    summary_ws['A5'] = "Violations:"
    summary_ws['B5'] = violations_count
    if violations_count > 0:
        summary_ws['B5'].fill = violation_fill
        summary_ws['C5'] = "ACTION REQUIRED"
        summary_ws['C5'].font = Font(bold=True, color="9C0006")
    else:
        summary_ws['B5'].fill = compliant_fill
        summary_ws['C5'] = "All access properly revoked"
        summary_ws['C5'].font = Font(color="006100")

    filepath = os.path.join(output_dir, f"{filename}.xlsx")
    wb.save(filepath)
    return filepath


# ============================================================
# COMPLIANCE EXCEL EXPORT TOOLS
# ============================================================

@mcp.tool()
def export_review_status(
    program: Optional[str] = None,
    include_current: bool = False,
    output_format: str = "xlsx",
    output_dir: Optional[str] = None
) -> str:
    """
    Export access review status to Excel for compliance tracking.

    Args:
        program: Filter by program name or prefix
        include_current: If True, include reviews that are current (not just issues)
        output_format: "xlsx" or "csv"
        output_dir: Directory to save file (default: ~/Downloads)

    Returns:
        Path to generated file and summary statistics
    """
    manager = None
    try:
        manager = get_access_manager()

        program_id = None
        program_name = None
        if program:
            try:
                program_id = manager._resolve_program_id(program)
                cursor = manager.conn.cursor()
                cursor.execute("SELECT name FROM programs WHERE program_id = ?", (program_id,))
                row = cursor.fetchone()
                if row:
                    program_name = row['name']
            except ValueError:
                return f"Program not found: {program}"

        try:
            status_data = manager.get_review_status_detail(
                program_id=program_id,
                include_current=include_current
            )
        except AttributeError:
            reviews_due = manager.get_reviews_due(program_id=program_id)
            today = date.today()
            due_soon_cutoff = (today + timedelta(days=30)).isoformat()
            today_str = today.isoformat()

            status_data = {
                'overdue': [],
                'due_soon': [],
                'current': [],
                'summary': {'overdue_count': 0, 'due_soon_count': 0, 'current_count': 0, 'as_of_date': today_str}
            }

            for review in reviews_due:
                next_due = review.get('next_review_due')
                if next_due and next_due <= today_str:
                    status_data['overdue'].append(review)
                elif next_due and next_due <= due_soon_cutoff:
                    status_data['due_soon'].append(review)

            status_data['summary']['overdue_count'] = len(status_data['overdue'])
            status_data['summary']['due_soon_count'] = len(status_data['due_soon'])

        has_issues = (status_data['summary']['overdue_count'] > 0 or
                      status_data['summary']['due_soon_count'] > 0)

        if not has_issues and not include_current:
            return (
                "All access reviews are current!\n\n"
                f"Summary (as of {status_data['summary']['as_of_date']}):\n"
                f"  Overdue: 0\n"
                f"  Due Soon: 0\n"
                f"  Current: {status_data['summary'].get('current_count', 'N/A')}\n\n"
                "No export generated - use include_current=True for full export."
            )

        if output_dir:
            out_path = os.path.expanduser(output_dir)
        else:
            out_path = os.path.expanduser("~/Downloads")
        os.makedirs(out_path, exist_ok=True)

        today_str = datetime.now().strftime('%Y-%m-%d')
        if program_name:
            safe_name = program_name.replace(' ', '_').replace('/', '-')
            filename = f"{safe_name}_review_status_{today_str}"
        else:
            filename = f"access_review_status_{today_str}"

        export_rows = []

        for item in status_data['overdue']:
            export_rows.append({
                'Review Status': 'OVERDUE',
                'Days Overdue': item.get('days_overdue', ''),
                'User Name': item.get('user_name', ''),
                'Email': item.get('email', ''),
                'Role': item.get('role', ''),
                'Program': item.get('program_name', ''),
                'Clinic': item.get('clinic_name', ''),
                'Location': item.get('location_name', ''),
                'Granted Date': item.get('granted_date', ''),
                'Last Review': item.get('last_review_date', ''),
                'Next Review Due': item.get('next_review_due', ''),
                'Review Cycle': item.get('review_cycle', ''),
                'Action Needed': ''
            })

        for item in status_data['due_soon']:
            export_rows.append({
                'Review Status': 'Due Soon',
                'Days Overdue': '',
                'User Name': item.get('user_name', ''),
                'Email': item.get('email', ''),
                'Role': item.get('role', ''),
                'Program': item.get('program_name', ''),
                'Clinic': item.get('clinic_name', ''),
                'Location': item.get('location_name', ''),
                'Granted Date': item.get('granted_date', ''),
                'Last Review': item.get('last_review_date', ''),
                'Next Review Due': item.get('next_review_due', ''),
                'Review Cycle': item.get('review_cycle', ''),
                'Action Needed': ''
            })

        if include_current:
            for item in status_data.get('current', []):
                export_rows.append({
                    'Review Status': 'Current',
                    'Days Overdue': '',
                    'User Name': item.get('user_name', ''),
                    'Email': item.get('email', ''),
                    'Role': item.get('role', ''),
                    'Program': item.get('program_name', ''),
                    'Clinic': item.get('clinic_name', ''),
                    'Location': item.get('location_name', ''),
                    'Granted Date': item.get('granted_date', ''),
                    'Last Review': item.get('last_review_date', ''),
                    'Next Review Due': item.get('next_review_due', ''),
                    'Review Cycle': item.get('review_cycle', ''),
                    'Action Needed': ''
                })

        if not export_rows:
            return "No data to export."

        if output_format.lower() == "xlsx":
            filepath = _create_review_status_excel(export_rows, out_path, filename)
        else:
            filepath = os.path.join(out_path, f"{filename}.csv")
            headers = list(export_rows[0].keys())
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(export_rows)

        result = f"Access Review Status Export\n"
        result += f"{'=' * 50}\n\n"
        result += f"File: {filepath}\n"
        result += f"Generated: {today_str}\n\n"
        if program_name:
            result += f"Program: {program_name}\n\n"
        result += f"Summary:\n"
        result += f"  OVERDUE: {status_data['summary']['overdue_count']}"
        if status_data['summary']['overdue_count'] > 0:
            result += " - ACTION REQUIRED"
        result += "\n"
        result += f"  Due Soon: {status_data['summary']['due_soon_count']}\n"
        result += f"  Total exported: {len(export_rows)}\n"

        return result

    except Exception as e:
        return f"Error exporting review status: {str(e)}"
    finally:
        if manager:
            manager.close()


@mcp.tool()
def import_review_response(
    file_path: str,
    reviewed_by: str,
    preview_only: bool = True
) -> str:
    """
    Import completed annual access review responses from clinic manager.

    Processes the Excel file that was exported with export_review_status
    and filled in by the clinic manager.

    Action column values:
    - Blank or empty: Recertify (confirm access, set next review date)
    - "Terminate": Revoke access (Manager Notes required)
    - "Update": Change role to New Role value (New Role required)

    Args:
        file_path: Path to completed Excel review file
        reviewed_by: Name of clinic manager who completed the review
        preview_only: If True (default), show what WOULD happen without making changes.
                     Set to False to actually process the review.

    Returns:
        Summary of review actions taken or planned
    """
    manager = None
    try:
        manager = get_access_manager()

        result = manager.process_review_response(
            file_path=file_path,
            reviewed_by=reviewed_by,
            preview_only=preview_only
        )

        # Build response
        mode = "PREVIEW MODE (no changes made)" if preview_only else "REVIEW IMPORT COMPLETE"

        output = f"Annual Access Review Import - {mode}\n"
        output += f"{'=' * 50}\n\n"
        output += f"File: {file_path}\n"
        output += f"Reviewed By: {reviewed_by}\n\n"

        # Summary
        summary = result['summary']
        output += f"Summary:\n"
        output += f"  Total rows: {summary['total_rows']}\n"
        output += f"  Recertified (keep): {summary['recertified']}\n"
        output += f"  Updated (role change): {summary['updated']}\n"
        output += f"  Terminated (revoked): {summary['terminated']}\n"
        output += f"  Skipped: {summary['skipped']}\n"
        output += f"  Errors: {summary['errors']}\n\n"

        # Show preview actions
        if result['preview']:
            output += f"Actions:\n"
            for action in result['preview'][:30]:
                icon = {
                    'RECERTIFY': '[KEEP]',
                    'UPDATE': '[UPDATE]',
                    'TERMINATE': '[REVOKE]'
                }.get(action['action'], '-')

                output += f"  {icon} {action['name']} ({action['email']})\n"
                output += f"      {action['action']}: {action['details']}\n"

            if len(result['preview']) > 30:
                remaining = len(result['preview']) - 30
                output += f"\n  ... and {remaining} more actions\n"

        # Show errors
        if result['errors']:
            output += f"\nErrors:\n"
            for err in result['errors'][:10]:
                output += f"  Row {err['row']}: {err['email']} - {err['error']}\n"
            if len(result['errors']) > 10:
                output += f"  ... and {len(result['errors']) - 10} more errors\n"

        # Next step hint
        if preview_only:
            total_actions = summary['recertified'] + summary['updated'] + summary['terminated']
            if total_actions > 0:
                output += f"\nTo apply these changes, run again with preview_only=False"

        return output

    except FileNotFoundError as e:
        return f"File not found: {file_path}\n\nMake sure the file exists and the path is correct."
    except Exception as e:
        return f"Error processing review: {str(e)}"
    finally:
        if manager:
            manager.close()


@mcp.tool()
def export_terminated_audit(
    since_date: Optional[str] = None,
    output_format: str = "xlsx",
    output_dir: Optional[str] = None
) -> str:
    """
    Export full terminated user audit to Excel.

    Args:
        since_date: Only include users terminated on/after this date (YYYY-MM-DD)
        output_format: "xlsx" or "csv"
        output_dir: Directory to save file (default: ~/Downloads)

    Returns:
        Path to generated file and compliance summary
    """
    manager = None
    try:
        manager = get_access_manager()

        try:
            terminated_users = manager.get_all_terminated_users(
                include_access_history=True,
                since_date=since_date
            )
        except AttributeError:
            cursor = manager.conn.cursor()
            query = """
                SELECT u.user_id, u.name, u.email, u.organization, u.updated_date as termination_date
                FROM users u WHERE u.status = 'Terminated'
            """
            params = []
            if since_date:
                query += " AND u.updated_date >= ?"
                params.append(since_date)
            query += " ORDER BY u.updated_date DESC"

            cursor.execute(query, params)
            terminated_users = []

            for row in cursor.fetchall():
                user = dict(row)
                user['terminated_by'] = 'See audit log'
                user['termination_reason'] = 'See audit log'

                cursor.execute("""
                    SELECT ua.access_id, ua.role, ua.is_active, ua.granted_date,
                           ua.revoked_date, ua.revoked_by, ua.revoke_reason,
                           p.name as program_name, c.name as clinic_name, l.name as location_name
                    FROM user_access ua
                    JOIN programs p ON ua.program_id = p.program_id
                    LEFT JOIN clinics c ON ua.clinic_id = c.clinic_id
                    LEFT JOIN locations l ON ua.location_id = l.location_id
                    WHERE ua.user_id = ?
                """, (user['user_id'],))

                access_history = [dict(r) for r in cursor.fetchall()]
                user['access_history'] = access_history
                active_count = sum(1 for a in access_history if a['is_active'])
                user['active_access_count'] = active_count
                user['compliance_status'] = 'VIOLATION' if active_count > 0 else 'Compliant'
                terminated_users.append(user)

        if not terminated_users:
            period = f" since {since_date}" if since_date else ""
            return f"No terminated users found{period}."

        if output_dir:
            out_path = os.path.expanduser(output_dir)
        else:
            out_path = os.path.expanduser("~/Downloads")
        os.makedirs(out_path, exist_ok=True)

        today_str = datetime.now().strftime('%Y-%m-%d')
        if since_date:
            filename = f"terminated_audit_{since_date}_to_{today_str}"
        else:
            filename = f"terminated_audit_full_{today_str}"

        export_rows = []
        violations_count = 0

        for user in terminated_users:
            is_violation = user['compliance_status'] == 'VIOLATION'
            if is_violation:
                violations_count += 1

            access_history = user.get('access_history', [])

            if not access_history:
                export_rows.append({
                    'Compliance Status': 'Compliant' if not is_violation else 'VIOLATION',
                    'User Name': user.get('name', ''),
                    'Email': user.get('email', ''),
                    'Organization': user.get('organization', ''),
                    'Termination Date': user.get('termination_date', ''),
                    'Terminated By': user.get('terminated_by', ''),
                    'Termination Reason': user.get('termination_reason', ''),
                    'Previous Role': '(No access grants)',
                    'Previous Program': '',
                    'Previous Clinic': '',
                    'Access Granted': '',
                    'Access Revoked': '',
                    'Revoked By': '',
                    'Revocation Reason': '',
                    'Access Still Active': 'No'
                })
            else:
                for i, access in enumerate(access_history):
                    export_rows.append({
                        'Compliance Status': ('Compliant' if not is_violation else 'VIOLATION') if i == 0 else '',
                        'User Name': user.get('name', '') if i == 0 else '',
                        'Email': user.get('email', '') if i == 0 else '',
                        'Organization': user.get('organization', '') if i == 0 else '',
                        'Termination Date': user.get('termination_date', '') if i == 0 else '',
                        'Terminated By': user.get('terminated_by', '') if i == 0 else '',
                        'Termination Reason': user.get('termination_reason', '') if i == 0 else '',
                        'Previous Role': access.get('role', ''),
                        'Previous Program': access.get('program_name', ''),
                        'Previous Clinic': access.get('clinic_name', ''),
                        'Access Granted': access.get('granted_date', ''),
                        'Access Revoked': access.get('revoked_date', '') if not access.get('is_active') else '',
                        'Revoked By': access.get('revoked_by', '') if not access.get('is_active') else '',
                        'Revocation Reason': access.get('revoke_reason', '') if not access.get('is_active') else '',
                        'Access Still Active': 'YES - VIOLATION!' if access.get('is_active') else 'No'
                    })

        if output_format.lower() == "xlsx":
            filepath = _create_terminated_audit_excel(export_rows, out_path, filename, violations_count)
        else:
            filepath = os.path.join(out_path, f"{filename}.csv")
            headers = list(export_rows[0].keys())
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(export_rows)

        result = f"Terminated User Audit Export\n"
        result += f"{'=' * 50}\n\n"
        result += f"File: {filepath}\n"
        result += f"Generated: {today_str}\n"
        if since_date:
            result += f"Period: {since_date} to present\n"
        result += "\n"
        result += f"Summary:\n"
        result += f"  Total terminated users: {len(terminated_users)}\n"
        result += f"  Compliant: {len(terminated_users) - violations_count}\n"
        result += f"  VIOLATIONS: {violations_count}"
        if violations_count > 0:
            result += " - IMMEDIATE ACTION REQUIRED"
        result += "\n"

        return result

    except Exception as e:
        return f"Error exporting terminated audit: {str(e)}"
    finally:
        if manager:
            manager.close()


# ============================================================
# DASHBOARD TOOLS
# ============================================================

def _generate_dashboard_react(data: dict) -> str:
    """Generate React component code for visual dashboard."""

    # Prepare data for the component
    programs_data = json.dumps([
        {"name": p["program_name"], "users": p["user_count"]}
        for p in data["users_by_program"]
    ])

    roles_data = json.dumps([
        {"name": r["role"], "count": r["count"], "percentage": r["percentage"]}
        for r in data["role_distribution"]
    ])

    imm = data["immediate_attention"]
    upcoming = data["upcoming"]
    totals = data["totals"]

    return f'''
import React from 'react';
import {{ BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell }} from 'recharts';

export default function ComplianceDashboard() {{
  const programData = {programs_data};
  const roleData = {roles_data};
  const COLORS = ['#4472C4', '#ED7D31', '#A5A5A5', '#FFC000', '#5B9BD5'];

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Compliance Dashboard</h1>

      {{/* Alert Cards */}}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className={{"p-4 rounded-lg " + ({imm['reviews_overdue']} > 0 ? "bg-red-100 border-2 border-red-400" : "bg-green-100")}}>
          <div className="text-3xl font-bold">{imm['reviews_overdue']}</div>
          <div className="text-sm text-gray-600">Reviews Overdue</div>
        </div>
        <div className={{"p-4 rounded-lg " + ({imm['terminated_violations']} > 0 ? "bg-red-100 border-2 border-red-400" : "bg-green-100")}}>
          <div className="text-3xl font-bold">{imm['terminated_violations']}</div>
          <div className="text-sm text-gray-600">Access Violations</div>
        </div>
        <div className={{"p-4 rounded-lg " + ({imm['training_expired']} > 0 ? "bg-red-100 border-2 border-red-400" : "bg-green-100")}}>
          <div className="text-3xl font-bold">{imm['training_expired']}</div>
          <div className="text-sm text-gray-600">Training Expired</div>
        </div>
        <div className="p-4 rounded-lg bg-yellow-100">
          <div className="text-3xl font-bold">{upcoming['reviews_due_soon']}</div>
          <div className="text-sm text-gray-600">Reviews Due (30 days)</div>
        </div>
      </div>

      {{/* Stats Row */}}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-white p-4 rounded-lg shadow">
          <div className="text-2xl font-bold text-blue-600">{totals['active_users']}</div>
          <div className="text-sm text-gray-500">Active Users</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow">
          <div className="text-2xl font-bold text-blue-600">{totals['total_programs']}</div>
          <div className="text-sm text-gray-500">Programs</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow">
          <div className="text-2xl font-bold text-blue-600">{totals['total_clinics']}</div>
          <div className="text-sm text-gray-500">Clinics</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow">
          <div className="text-2xl font-bold text-blue-600">{totals['recent_grants_count']}</div>
          <div className="text-sm text-gray-500">Grants (30 days)</div>
        </div>
      </div>

      {{/* Charts Row */}}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white p-4 rounded-lg shadow">
          <h3 className="font-semibold mb-4">Users by Program</h3>
          <ResponsiveContainer width="100%" height={{200}}>
            <BarChart data={{programData}}>
              <XAxis dataKey="name" tick={{{{fontSize: 12}}}} />
              <YAxis />
              <Tooltip />
              <Bar dataKey="users" fill="#4472C4" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white p-4 rounded-lg shadow">
          <h3 className="font-semibold mb-4">Role Distribution</h3>
          <ResponsiveContainer width="100%" height={{200}}>
            <PieChart>
              <Pie
                data={{roleData}}
                dataKey="count"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={{70}}
                label={{({{name, percentage}}) => `${{name}} (${{percentage}}%)`}}
              >
                {{roleData.map((entry, index) => (
                  <Cell key={{index}} fill={{COLORS[index % COLORS.length]}} />
                ))}}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}}
'''


@mcp.tool()
def get_compliance_dashboard() -> str:
    """
    Get compliance dashboard with text summary and visual artifact.

    Shows:
    - Immediate attention items (overdue reviews, violations, expired training)
    - Upcoming reviews (next 30 days)
    - Users by program and clinic
    - Role distribution
    - Recent activity

    Returns:
        Text summary followed by React artifact code for visual dashboard
    """
    manager = None
    try:
        manager = get_access_manager()
        data = manager.get_dashboard_data()

        # Build text summary
        output = "COMPLIANCE DASHBOARD\n"
        output += f"Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}\n"
        output += "=" * 50 + "\n\n"

        # Immediate attention
        imm = data['immediate_attention']
        has_issues = imm['reviews_overdue'] > 0 or imm['terminated_violations'] > 0 or imm['training_expired'] > 0

        if has_issues:
            output += "IMMEDIATE ATTENTION\n"
            if imm['reviews_overdue'] > 0:
                output += f"   - {imm['reviews_overdue']} access reviews OVERDUE\n"
            if imm['terminated_violations'] > 0:
                output += f"   - {imm['terminated_violations']} terminated user(s) with ACTIVE ACCESS\n"
            if imm['training_expired'] > 0:
                output += f"   - {imm['training_expired']} training record(s) EXPIRED\n"
            output += "\n"
        else:
            output += "NO IMMEDIATE ISSUES\n"
            output += "   All reviews current, no violations, training up to date\n\n"

        # Upcoming
        upcoming = data['upcoming']['reviews_due_soon']
        if upcoming > 0:
            output += f"UPCOMING (Next 30 Days)\n"
            output += f"   - {upcoming} review(s) due soon\n\n"

        # Totals
        totals = data['totals']
        output += "TOTALS\n"
        output += f"   - {totals['active_users']} active users\n"
        output += f"   - {totals['total_programs']} programs\n"
        output += f"   - {totals['total_clinics']} clinics\n"
        output += f"   - {totals['recent_grants_count']} access grants in last 30 days\n\n"

        # Users by program
        output += "USERS BY PROGRAM\n"
        for prog in data['users_by_program']:
            output += f"   - {prog['program_name']}: {prog['user_count']} users, {prog['clinic_count']} clinics\n"
        output += "\n"

        # Role distribution
        output += "ROLE DISTRIBUTION\n"
        for role in data['role_distribution']:
            output += f"   - {role['role']}: {role['count']} ({role['percentage']}%)\n"
        output += "\n"

        # Recent activity (top 5)
        if data['recent_activity']:
            output += "RECENT ACTIVITY (Last 30 Days)\n"
            for i, activity in enumerate(data['recent_activity'][:5]):
                output += f"   - {activity['granted_date']}: {activity['user_name']} -> {activity['program_name']}"
                if activity['clinic_name'] != '(Program-wide)':
                    output += f" / {activity['clinic_name']}"
                output += f" ({activity['role']})\n"
            if len(data['recent_activity']) > 5:
                output += f"   ... and {len(data['recent_activity']) - 5} more\n"

        # Add React artifact instructions
        output += "\n" + "=" * 50 + "\n"
        output += "VISUAL DASHBOARD\n"
        output += "Creating React artifact with charts...\n\n"

        # Generate React artifact code
        react_code = _generate_dashboard_react(data)
        output += "```jsx\n" + react_code + "\n```"

        return output

    except Exception as e:
        return f"Error generating dashboard: {str(e)}"
    finally:
        if manager:
            manager.close()


@mcp.tool()
def push_dashboard_to_notion() -> str:
    """
    Update the Notion compliance dashboard page with current data.

    Updates the page at: https://www.notion.so/2dab5d1d163181bb8eebc4f4397de747

    Returns:
        Confirmation of update with summary
    """
    manager = None
    try:
        manager = get_access_manager()
        data = manager.get_dashboard_data()

        # Build Notion-flavored markdown content
        now = datetime.now().strftime('%B %d, %Y at %I:%M %p')

        content = f"""# Client Access Compliance Dashboard

**Auto-Updated by Claude MCP**
This dashboard is automatically updated when you run "push compliance dashboard to Notion" in Claude.

**Last Updated:** {now}

---

## Immediate Attention

| Metric | Count | Status |
|--------|-------|--------|
| Access Reviews Overdue | {data['immediate_attention']['reviews_overdue']} | {'ACTION REQUIRED' if data['immediate_attention']['reviews_overdue'] > 0 else 'OK'} |
| Terminated with Active Access | {data['immediate_attention']['terminated_violations']} | {'VIOLATION' if data['immediate_attention']['terminated_violations'] > 0 else 'OK'} |
| Training Expired | {data['immediate_attention']['training_expired']} | {'ACTION REQUIRED' if data['immediate_attention']['training_expired'] > 0 else 'OK'} |

---

## Upcoming (Next 30 Days)

| Metric | Count |
|--------|-------|
| Reviews Due Soon | {data['upcoming']['reviews_due_soon']} |

---

## Program Summary

| Program | Active Users | Clinics |
|---------|--------------|---------|
"""
        for prog in data['users_by_program']:
            content += f"| {prog['program_name']} | {prog['user_count']} | {prog['clinic_count']} |\n"

        content += """
---

## Users by Clinic

| Clinic | Program | Users |
|--------|---------|-------|
"""
        for clinic in data['users_by_clinic'][:15]:  # Top 15
            content += f"| {clinic['clinic_name']} | {clinic['program_name']} | {clinic['user_count']} |\n"

        content += """
---

## Role Distribution

| Role | Count | % |
|------|-------|---|
"""
        for role in data['role_distribution']:
            content += f"| {role['role']} | {role['count']} | {role['percentage']}% |\n"

        content += """
---

## Recent Activity (Last 30 Days)

| Date | User | Program | Clinic | Role |
|------|------|---------|--------|------|
"""
        for activity in data['recent_activity'][:10]:  # Top 10
            content += f"| {activity['granted_date']} | {activity['user_name']} | {activity['program_name']} | {activity['clinic_name']} | {activity['role']} |\n"

        content += f"""
---

## Totals

| Metric | Value |
|--------|-------|
| Total Active Users | {data['totals']['active_users']} |
| Total Programs | {data['totals']['total_programs']} |
| Total Clinics | {data['totals']['total_clinics']} |
| Access Grants (Last 30 Days) | {data['totals']['recent_grants_count']} |
"""

        # Return the content for Notion update
        # The actual Notion update will be handled by the Notion MCP tools
        return f"""Dashboard data ready for Notion update.

**Page ID:** {NOTION_DASHBOARD_PAGE_ID}
**URL:** https://www.notion.so/{NOTION_DASHBOARD_PAGE_ID.replace('-', '')}
**Last Updated:** {now}

**Summary:**
- Reviews Overdue: {data['immediate_attention']['reviews_overdue']}
- Violations: {data['immediate_attention']['terminated_violations']}
- Training Expired: {data['immediate_attention']['training_expired']}
- Active Users: {data['totals']['active_users']}

To update Notion, I need to call the Notion update-page tool with this content.

---NOTION_CONTENT_START---
{content}
---NOTION_CONTENT_END---
"""

    except Exception as e:
        return f"Error preparing dashboard for Notion: {str(e)}"
    finally:
        if manager:
            manager.close()


@mcp.tool()
def export_compliance_dashboard(
    output_dir: Optional[str] = None
) -> str:
    """
    Export compliance dashboard to Excel for stakeholders.

    Creates a formatted Excel file with multiple sheets:
    - Summary (all metrics)
    - Reviews Overdue (detail)
    - Users by Program
    - Users by Clinic
    - Role Distribution
    - Recent Activity

    Args:
        output_dir: Directory to save file (default: ~/Downloads)

    Returns:
        Path to generated file
    """
    manager = None
    try:
        manager = get_access_manager()
        data = manager.get_dashboard_data()

        if output_dir:
            out_path = os.path.expanduser(output_dir)
        else:
            out_path = os.path.expanduser("~/Downloads")
        os.makedirs(out_path, exist_ok=True)

        today_str = datetime.now().strftime('%Y-%m-%d')
        filename = f"compliance_dashboard_{today_str}.xlsx"
        filepath = os.path.join(out_path, filename)

        wb = Workbook()

        # Styles
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        alert_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
        ok_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
        thin_border = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin')
        )

        # --- SUMMARY SHEET ---
        ws = wb.active
        ws.title = "Summary"

        ws['A1'] = "Compliance Dashboard Summary"
        ws['A1'].font = Font(bold=True, size=16)
        ws['A2'] = f"Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}"

        ws['A4'] = "IMMEDIATE ATTENTION"
        ws['A4'].font = Font(bold=True, size=12)

        metrics = [
            ('Access Reviews Overdue', data['immediate_attention']['reviews_overdue']),
            ('Terminated with Active Access', data['immediate_attention']['terminated_violations']),
            ('Training Expired', data['immediate_attention']['training_expired']),
        ]

        row = 5
        for metric, value in metrics:
            ws.cell(row=row, column=1, value=metric)
            cell = ws.cell(row=row, column=2, value=value)
            cell.fill = alert_fill if value > 0 else ok_fill
            row += 1

        row += 1
        ws.cell(row=row, column=1, value="UPCOMING (Next 30 Days)").font = Font(bold=True, size=12)
        row += 1
        ws.cell(row=row, column=1, value="Reviews Due Soon")
        ws.cell(row=row, column=2, value=data['upcoming']['reviews_due_soon'])

        row += 2
        ws.cell(row=row, column=1, value="TOTALS").font = Font(bold=True, size=12)
        row += 1
        ws.cell(row=row, column=1, value="Active Users")
        ws.cell(row=row, column=2, value=data['totals']['active_users'])
        row += 1
        ws.cell(row=row, column=1, value="Total Programs")
        ws.cell(row=row, column=2, value=data['totals']['total_programs'])
        row += 1
        ws.cell(row=row, column=1, value="Total Clinics")
        ws.cell(row=row, column=2, value=data['totals']['total_clinics'])
        row += 1
        ws.cell(row=row, column=1, value="Access Grants (Last 30 Days)")
        ws.cell(row=row, column=2, value=data['totals']['recent_grants_count'])

        ws.column_dimensions['A'].width = 35
        ws.column_dimensions['B'].width = 15

        # --- USERS BY PROGRAM SHEET ---
        ws2 = wb.create_sheet("Users by Program")
        headers = ['Program', 'Prefix', 'Active Users', 'Clinics']
        for col, header in enumerate(headers, 1):
            cell = ws2.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.border = thin_border

        for row_num, prog in enumerate(data['users_by_program'], 2):
            ws2.cell(row=row_num, column=1, value=prog['program_name']).border = thin_border
            ws2.cell(row=row_num, column=2, value=prog.get('program_prefix', '')).border = thin_border
            ws2.cell(row=row_num, column=3, value=prog['user_count']).border = thin_border
            ws2.cell(row=row_num, column=4, value=prog['clinic_count']).border = thin_border

        ws2.column_dimensions['A'].width = 25
        ws2.freeze_panes = 'A2'

        # --- USERS BY CLINIC SHEET ---
        ws3 = wb.create_sheet("Users by Clinic")
        headers = ['Clinic', 'Program', 'Active Users']
        for col, header in enumerate(headers, 1):
            cell = ws3.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.border = thin_border

        for row_num, clinic in enumerate(data['users_by_clinic'], 2):
            ws3.cell(row=row_num, column=1, value=clinic['clinic_name']).border = thin_border
            ws3.cell(row=row_num, column=2, value=clinic['program_name']).border = thin_border
            ws3.cell(row=row_num, column=3, value=clinic['user_count']).border = thin_border

        ws3.column_dimensions['A'].width = 30
        ws3.column_dimensions['B'].width = 25
        ws3.freeze_panes = 'A2'

        # --- ROLE DISTRIBUTION SHEET ---
        ws4 = wb.create_sheet("Role Distribution")
        headers = ['Role', 'Count', 'Percentage']
        for col, header in enumerate(headers, 1):
            cell = ws4.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.border = thin_border

        for row_num, role in enumerate(data['role_distribution'], 2):
            ws4.cell(row=row_num, column=1, value=role['role']).border = thin_border
            ws4.cell(row=row_num, column=2, value=role['count']).border = thin_border
            ws4.cell(row=row_num, column=3, value=f"{role['percentage']}%").border = thin_border

        ws4.column_dimensions['A'].width = 20
        ws4.freeze_panes = 'A2'

        # --- RECENT ACTIVITY SHEET ---
        ws5 = wb.create_sheet("Recent Activity")
        headers = ['Date', 'User', 'Email', 'Role', 'Program', 'Clinic', 'Granted By']
        for col, header in enumerate(headers, 1):
            cell = ws5.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.border = thin_border

        for row_num, activity in enumerate(data['recent_activity'], 2):
            ws5.cell(row=row_num, column=1, value=activity['granted_date']).border = thin_border
            ws5.cell(row=row_num, column=2, value=activity['user_name']).border = thin_border
            ws5.cell(row=row_num, column=3, value=activity['email']).border = thin_border
            ws5.cell(row=row_num, column=4, value=activity['role']).border = thin_border
            ws5.cell(row=row_num, column=5, value=activity['program_name']).border = thin_border
            ws5.cell(row=row_num, column=6, value=activity['clinic_name']).border = thin_border
            ws5.cell(row=row_num, column=7, value=activity['granted_by']).border = thin_border

        for col in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
            ws5.column_dimensions[col].width = 20
        ws5.freeze_panes = 'A2'

        wb.save(filepath)

        # Build summary
        output = f"Compliance Dashboard Export\n"
        output += f"{'=' * 50}\n\n"
        output += f"File: {filepath}\n"
        output += f"Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}\n\n"
        output += f"Sheets included:\n"
        output += f"  - Summary\n"
        output += f"  - Users by Program ({len(data['users_by_program'])} programs)\n"
        output += f"  - Users by Clinic ({len(data['users_by_clinic'])} clinics)\n"
        output += f"  - Role Distribution ({len(data['role_distribution'])} roles)\n"
        output += f"  - Recent Activity ({len(data['recent_activity'])} records)\n"

        return output

    except Exception as e:
        return f"Error exporting dashboard: {str(e)}"
    finally:
        if manager:
            manager.close()


# ============================================================
# CONFIGURATION VIEWING TOOLS
# ============================================================

@mcp.tool()
def get_program_overview(program: str) -> str:
    """
    Get comprehensive overview of a program including all clinics, locations, and config summary.

    Args:
        program: Program prefix (e.g., "P4M") or name

    Returns:
        Program hierarchy with config counts and override summary
    """
    cm = None
    try:
        cm = get_config_manager()

        # Resolve program
        program_id = cm.get_program_id(program)
        if not program_id:
            return f"Program not found: {program}"

        # Get program details
        cursor = cm.conn.cursor()
        cursor.execute("""
            SELECT p.*,
                   (SELECT COUNT(*) FROM clinics c WHERE c.program_id = p.program_id) as clinic_count,
                   (SELECT COUNT(*) FROM locations l
                    JOIN clinics c ON l.clinic_id = c.clinic_id
                    WHERE c.program_id = p.program_id) as location_count,
                   (SELECT COUNT(*) FROM config_values cv WHERE cv.program_id = p.program_id AND cv.clinic_id IS NULL) as program_config_count
            FROM programs p WHERE p.program_id = ?
        """, (program_id,))
        program_data = dict(cursor.fetchone())

        result = f"Program: {program_data['name']} [{program_data.get('prefix', '')}]\n"
        result += "=" * 50 + "\n\n"
        result += f"Type: {program_data.get('program_type', 'N/A')}\n"
        result += f"Status: {program_data.get('status', 'Active')}\n\n"

        result += f"Hierarchy:\n"
        result += f"  Clinics: {program_data['clinic_count']}\n"
        result += f"  Locations: {program_data['location_count']}\n"
        result += f"  Program-level configs: {program_data['program_config_count']}\n\n"

        # Get clinics with their locations
        cursor.execute("""
            SELECT c.clinic_id, c.name, c.code,
                   (SELECT COUNT(*) FROM locations l WHERE l.clinic_id = c.clinic_id) as location_count,
                   (SELECT COUNT(*) FROM config_values cv WHERE cv.clinic_id = c.clinic_id AND cv.location_id IS NULL) as clinic_config_count
            FROM clinics c
            WHERE c.program_id = ?
            ORDER BY c.name
        """, (program_id,))

        clinics = cursor.fetchall()

        if clinics:
            result += "Clinics:\n"
            for clinic in clinics:
                clinic_dict = dict(clinic)
                result += f"\n  [{clinic_dict.get('code', '')}] {clinic_dict['name']}\n"
                result += f"      Locations: {clinic_dict['location_count']} | Clinic-level configs: {clinic_dict['clinic_config_count']}\n"

                # Get locations for this clinic
                cursor.execute("""
                    SELECT l.name, l.code,
                           (SELECT COUNT(*) FROM config_values cv WHERE cv.location_id = l.location_id) as location_config_count
                    FROM locations l
                    WHERE l.clinic_id = ?
                    ORDER BY l.name
                """, (clinic_dict['clinic_id'],))

                locations = cursor.fetchall()
                for loc in locations:
                    loc_dict = dict(loc)
                    result += f"      +-- {loc_dict['name']}"
                    if loc_dict.get('code'):
                        result += f" [{loc_dict['code']}]"
                    result += f" ({loc_dict['location_config_count']} overrides)\n"

        return result

    except Exception as e:
        return f"Error getting program overview: {str(e)}"
    finally:
        if cm:
            cm.close()


@mcp.tool()
def get_clinic_config(
    program: str,
    clinic: str,
    category: Optional[str] = None
) -> str:
    """
    Get all configuration values for a specific clinic with inheritance info.

    Args:
        program: Program prefix (e.g., "P4M")
        clinic: Clinic name or code
        category: Optional category filter (e.g., "helpdesk", "operations", "lab_order")

    Returns:
        All configs for the clinic showing effective values and sources
    """
    cm = None
    try:
        cm = get_config_manager()
        im = InheritanceManager(cm)

        program_id = cm.get_program_id(program)
        if not program_id:
            return f"Program not found: {program}"

        clinic_id = cm.get_clinic_id(program_id, clinic)
        if not clinic_id:
            return f"Clinic not found: {clinic}"

        # Get clinic name
        cursor = cm.conn.cursor()
        cursor.execute("SELECT name FROM clinics WHERE clinic_id = ?", (clinic_id,))
        clinic_name = cursor.fetchone()['name']

        # Get all config definitions
        cursor.execute("""
            SELECT config_key, display_name, category, default_value
            FROM config_definitions
            ORDER BY category, display_name
        """)
        definitions = cursor.fetchall()

        result = f"Configuration: {clinic_name} ({program})\n"
        result += "=" * 50 + "\n\n"

        current_category = None
        for defn in definitions:
            defn_dict = dict(defn)

            # Filter by category if specified
            if category and category.lower() not in defn_dict['category'].lower():
                continue

            # Print category header
            if defn_dict['category'] != current_category:
                current_category = defn_dict['category']
                result += f"\n[{current_category.upper()}]\n"

            # Get effective value with inheritance
            config = im.resolve_with_inheritance(
                defn_dict['config_key'], program_id, clinic_id, None
            )

            effective_value = config.get('value') if config else defn_dict['default_value']
            effective_level = config.get('effective_level', 'default') if config else 'default'
            is_override = config.get('is_override', False) if config else False

            # Format display
            display = defn_dict.get('display_name') or defn_dict['config_key']
            override_marker = "*" if is_override else ""
            source_indicator = f" [{effective_level}]" if effective_level != 'clinic' else ""

            result += f"  {display}: {effective_value or '(not set)'}{override_marker}{source_indicator}\n"

        result += "\n* = overridden at this level\n"
        result += "[level] = inherited from that level\n"

        return result

    except Exception as e:
        return f"Error getting clinic config: {str(e)}"
    finally:
        if cm:
            cm.close()


@mcp.tool()
def compare_clinic_configs(
    program: str,
    clinic1: str,
    clinic2: str
) -> str:
    """
    Compare configuration values between two clinics.

    Args:
        program: Program prefix (e.g., "P4M")
        clinic1: First clinic name or code
        clinic2: Second clinic name or code

    Returns:
        Side-by-side comparison highlighting differences
    """
    cm = None
    try:
        cm = get_config_manager()
        im = InheritanceManager(cm)

        program_id = cm.get_program_id(program)
        if not program_id:
            return f"Program not found: {program}"

        clinic1_id = cm.get_clinic_id(program_id, clinic1)
        if not clinic1_id:
            return f"Clinic not found: {clinic1}"

        clinic2_id = cm.get_clinic_id(program_id, clinic2)
        if not clinic2_id:
            return f"Clinic not found: {clinic2}"

        # Get clinic names
        cursor = cm.conn.cursor()
        cursor.execute("SELECT name FROM clinics WHERE clinic_id = ?", (clinic1_id,))
        clinic1_name = cursor.fetchone()['name']
        cursor.execute("SELECT name FROM clinics WHERE clinic_id = ?", (clinic2_id,))
        clinic2_name = cursor.fetchone()['name']

        # Get all config definitions
        cursor.execute("""
            SELECT config_key, display_name, category
            FROM config_definitions
            ORDER BY category, display_name
        """)
        definitions = cursor.fetchall()

        result = f"Config Comparison: {clinic1_name} vs {clinic2_name}\n"
        result += "=" * 60 + "\n\n"

        differences = []
        same_count = 0

        current_category = None
        for defn in definitions:
            defn_dict = dict(defn)

            # Get values for both clinics
            config1 = im.resolve_with_inheritance(defn_dict['config_key'], program_id, clinic1_id, None)
            config2 = im.resolve_with_inheritance(defn_dict['config_key'], program_id, clinic2_id, None)

            value1 = config1.get('value') if config1 else None
            value2 = config2.get('value') if config2 else None

            if value1 != value2:
                differences.append({
                    'category': defn_dict['category'],
                    'key': defn_dict.get('display_name') or defn_dict['config_key'],
                    'value1': value1 or '(not set)',
                    'value2': value2 or '(not set)'
                })
            else:
                same_count += 1

        # Display differences grouped by category
        if differences:
            result += f"DIFFERENCES ({len(differences)}):\n"
            current_category = None
            for diff in differences:
                if diff['category'] != current_category:
                    current_category = diff['category']
                    result += f"\n[{current_category.upper()}]\n"
                result += f"  {diff['key']}:\n"
                result += f"    {clinic1_name}: {diff['value1']}\n"
                result += f"    {clinic2_name}: {diff['value2']}\n"
        else:
            result += "No differences found.\n"

        result += f"\n\nSummary: {len(differences)} differences, {same_count} same\n"

        return result

    except Exception as e:
        return f"Error comparing clinics: {str(e)}"
    finally:
        if cm:
            cm.close()


@mcp.tool()
def get_config_overrides(
    program: str,
    clinic: Optional[str] = None
) -> str:
    """
    Get all configuration overrides (non-inherited values) for a program or clinic.

    Args:
        program: Program prefix (e.g., "P4M")
        clinic: Optional clinic name to filter to specific clinic

    Returns:
        List of all overridden configs with their values
    """
    cm = None
    try:
        cm = get_config_manager()

        program_id = cm.get_program_id(program)
        if not program_id:
            return f"Program not found: {program}"

        cursor = cm.conn.cursor()

        # Get program name
        cursor.execute("SELECT name FROM programs WHERE program_id = ?", (program_id,))
        program_name = cursor.fetchone()['name']

        result = f"Configuration Overrides: {program_name}\n"
        result += "=" * 50 + "\n"

        # Build query based on scope
        if clinic:
            clinic_id = cm.get_clinic_id(program_id, clinic)
            if not clinic_id:
                return f"Clinic not found: {clinic}"

            cursor.execute("SELECT name FROM clinics WHERE clinic_id = ?", (clinic_id,))
            clinic_name = cursor.fetchone()['name']
            result += f"Clinic: {clinic_name}\n\n"

            # Get clinic and location overrides
            cursor.execute("""
                SELECT cv.config_key, cv.value, cv.source, cv.updated_date,
                       cd.display_name, cd.category,
                       c.name as clinic_name, l.name as location_name
                FROM config_values cv
                JOIN config_definitions cd ON cv.config_key = cd.config_key
                LEFT JOIN clinics c ON cv.clinic_id = c.clinic_id
                LEFT JOIN locations l ON cv.location_id = l.location_id
                WHERE cv.program_id = ? AND cv.clinic_id = ?
                ORDER BY cv.location_id IS NULL DESC, cd.category, cd.display_name
            """, (program_id, clinic_id))
        else:
            result += "\n"
            # Get all overrides for the program
            cursor.execute("""
                SELECT cv.config_key, cv.value, cv.source, cv.updated_date,
                       cd.display_name, cd.category,
                       c.name as clinic_name, l.name as location_name
                FROM config_values cv
                JOIN config_definitions cd ON cv.config_key = cd.config_key
                LEFT JOIN clinics c ON cv.clinic_id = c.clinic_id
                LEFT JOIN locations l ON cv.location_id = l.location_id
                WHERE cv.program_id = ?
                ORDER BY cv.clinic_id IS NULL DESC, cv.location_id IS NULL DESC,
                         c.name, l.name, cd.category, cd.display_name
            """, (program_id,))

        overrides = cursor.fetchall()

        if not overrides:
            result += "No overrides found. All values are inherited from defaults.\n"
            return result

        # Group and display
        current_scope = None
        for override in overrides:
            ov = dict(override)

            # Determine scope
            if ov['location_name']:
                scope = f"Location: {ov['clinic_name']} > {ov['location_name']}"
            elif ov['clinic_name']:
                scope = f"Clinic: {ov['clinic_name']}"
            else:
                scope = "Program-level"

            if scope != current_scope:
                current_scope = scope
                result += f"\n[{scope}]\n"

            display = ov.get('display_name') or ov['config_key']
            result += f"  {display}: {ov['value']}\n"
            result += f"    Source: {ov['source']} | Updated: {ov['updated_date']}\n"

        result += f"\nTotal overrides: {len(overrides)}\n"

        return result

    except Exception as e:
        return f"Error getting overrides: {str(e)}"
    finally:
        if cm:
            cm.close()


@mcp.tool()
def get_clinic_providers(
    program: str,
    clinic: str
) -> str:
    """
    Get all providers (healthcare staff) for a clinic with their NPIs.

    Args:
        program: Program prefix (e.g., "P4M")
        clinic: Clinic name or code

    Returns:
        List of providers with NPI, location, and specialty info
    """
    cm = None
    try:
        cm = get_config_manager()

        program_id = cm.get_program_id(program)
        if not program_id:
            return f"Program not found: {program}"

        clinic_id = cm.get_clinic_id(program_id, clinic)
        if not clinic_id:
            return f"Clinic not found: {clinic}"

        cursor = cm.conn.cursor()

        # Get clinic name
        cursor.execute("SELECT name FROM clinics WHERE clinic_id = ?", (clinic_id,))
        clinic_name = cursor.fetchone()['name']

        # Get providers
        cursor.execute("""
            SELECT p.name, p.npi, p.specialty, p.status,
                   l.name as location_name
            FROM providers p
            LEFT JOIN locations l ON p.location_id = l.location_id
            JOIN clinics c ON (p.location_id IN (SELECT location_id FROM locations WHERE clinic_id = c.clinic_id)
                              OR p.clinic_id = c.clinic_id)
            WHERE c.clinic_id = ?
            ORDER BY l.name, p.name
        """, (clinic_id,))

        providers = cursor.fetchall()

        result = f"Providers: {clinic_name} ({program})\n"
        result += "=" * 50 + "\n\n"

        if not providers:
            result += "No providers found for this clinic.\n"
            return result

        current_location = None
        active_count = 0
        for prov in providers:
            prov_dict = dict(prov)

            location = prov_dict.get('location_name') or '(Clinic-wide)'
            if location != current_location:
                current_location = location
                result += f"\n[{location}]\n"

            status = prov_dict.get('status', 'Active')
            status_marker = "" if status == 'Active' else f" ({status})"
            if status == 'Active':
                active_count += 1

            result += f"  {prov_dict['name']}{status_marker}\n"
            result += f"    NPI: {prov_dict.get('npi', 'Not set')}"
            if prov_dict.get('specialty'):
                result += f" | Specialty: {prov_dict['specialty']}"
            result += "\n"

        result += f"\nTotal: {len(providers)} providers ({active_count} active)\n"

        return result

    except Exception as e:
        return f"Error getting providers: {str(e)}"
    finally:
        if cm:
            cm.close()


@mcp.tool()
def get_clinic_appointment_types(
    program: str,
    clinic: str
) -> str:
    """
    Get appointment type filters for a clinic and its locations.

    Args:
        program: Program prefix (e.g., "P4M")
        clinic: Clinic name or code

    Returns:
        List of appointment types included/excluded for extract filtering
    """
    cm = None
    try:
        cm = get_config_manager()

        program_id = cm.get_program_id(program)
        if not program_id:
            return f"Program not found: {program}"

        clinic_id = cm.get_clinic_id(program_id, clinic)
        if not clinic_id:
            return f"Clinic not found: {clinic}"

        cursor = cm.conn.cursor()

        # Get clinic name
        cursor.execute("SELECT name FROM clinics WHERE clinic_id = ?", (clinic_id,))
        clinic_name = cursor.fetchone()['name']

        # Get appointment types
        cursor.execute("""
            SELECT at.name, at.code, at.include, at.exclude_reason,
                   l.name as location_name
            FROM appointment_types at
            LEFT JOIN locations l ON at.location_id = l.location_id
            WHERE at.clinic_id = ? OR at.location_id IN (
                SELECT location_id FROM locations WHERE clinic_id = ?
            )
            ORDER BY l.name NULLS FIRST, at.include DESC, at.name
        """, (clinic_id, clinic_id))

        appt_types = cursor.fetchall()

        result = f"Appointment Types: {clinic_name} ({program})\n"
        result += "=" * 50 + "\n\n"

        if not appt_types:
            result += "No appointment type filters configured.\n"
            result += "All appointment types will be included in extracts.\n"
            return result

        current_location = None
        included_count = 0
        excluded_count = 0

        for at in appt_types:
            at_dict = dict(at)

            location = at_dict.get('location_name') or '(Clinic-wide)'
            if location != current_location:
                current_location = location
                result += f"\n[{location}]\n"

            included = at_dict.get('include', True)
            if included:
                included_count += 1
                result += f"  [INCLUDE] {at_dict['name']}"
            else:
                excluded_count += 1
                result += f"  [EXCLUDE] {at_dict['name']}"

            if at_dict.get('code'):
                result += f" ({at_dict['code']})"
            result += "\n"

            if not included and at_dict.get('exclude_reason'):
                result += f"           Reason: {at_dict['exclude_reason']}\n"

        result += f"\nSummary: {included_count} included, {excluded_count} excluded\n"

        return result

    except Exception as e:
        return f"Error getting appointment types: {str(e)}"
    finally:
        if cm:
            cm.close()


@mcp.tool()
def export_program_configs(
    program: str,
    output_dir: Optional[str] = None,
    include_audit: bool = False
) -> str:
    """
    Export all configurations for a program to Excel (Configuration Matrix format).

    Args:
        program: Program prefix (e.g., "P4M")
        output_dir: Directory to save file (default: ~/Downloads)
        include_audit: If True, include audit history sheet

    Returns:
        Path to generated Excel file
    """
    cm = None
    try:
        cm = get_config_manager()

        program_id = cm.get_program_id(program)
        if not program_id:
            return f"Program not found: {program}"

        cursor = cm.conn.cursor()

        # Get program info
        cursor.execute("SELECT name, prefix FROM programs WHERE program_id = ?", (program_id,))
        program_data = dict(cursor.fetchone())
        program_name = program_data['name']
        program_prefix = program_data.get('prefix', '')

        if output_dir:
            out_path = os.path.expanduser(output_dir)
        else:
            out_path = os.path.expanduser("~/Downloads")
        os.makedirs(out_path, exist_ok=True)

        today_str = datetime.now().strftime('%Y-%m-%d')
        filename = f"{program_prefix}_configurations_{today_str}.xlsx"
        filepath = os.path.join(out_path, filename)

        wb = Workbook()

        # Styles
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        category_fill = PatternFill(start_color="D6DCE5", end_color="D6DCE5", fill_type="solid")
        override_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
        thin_border = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin')
        )

        # --- CONFIGURATION MATRIX SHEET ---
        ws = wb.active
        ws.title = "Configuration Matrix"

        # Get clinics and locations
        cursor.execute("""
            SELECT c.clinic_id, c.name as clinic_name
            FROM clinics c WHERE c.program_id = ?
            ORDER BY c.name
        """, (program_id,))
        clinics = [dict(row) for row in cursor.fetchall()]

        # Build location map
        location_columns = []
        for clinic in clinics:
            cursor.execute("""
                SELECT l.location_id, l.name
                FROM locations l WHERE l.clinic_id = ?
                ORDER BY l.name
            """, (clinic['clinic_id'],))
            locations = [dict(row) for row in cursor.fetchall()]

            if locations:
                for loc in locations:
                    location_columns.append({
                        'clinic_id': clinic['clinic_id'],
                        'clinic_name': clinic['clinic_name'],
                        'location_id': loc['location_id'],
                        'location_name': loc['name'],
                        'header': f"{clinic['clinic_name']}\n{loc['name']}"
                    })
            else:
                location_columns.append({
                    'clinic_id': clinic['clinic_id'],
                    'clinic_name': clinic['clinic_name'],
                    'location_id': None,
                    'location_name': None,
                    'header': clinic['clinic_name']
                })

        # Headers
        headers = ['Config Key', 'Display Name', 'Program Default'] + [lc['header'] for lc in location_columns]
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border = thin_border

        # Get config definitions
        cursor.execute("""
            SELECT config_key, display_name, category, default_value
            FROM config_definitions
            ORDER BY category, display_name
        """)
        definitions = [dict(row) for row in cursor.fetchall()]

        im = InheritanceManager(cm)

        row = 2
        current_category = None

        for defn in definitions:
            # Category header row
            if defn['category'] != current_category:
                current_category = defn['category']
                cell = ws.cell(row=row, column=1, value=current_category.upper())
                cell.fill = category_fill
                cell.font = Font(bold=True)
                for col in range(1, len(headers) + 1):
                    ws.cell(row=row, column=col).fill = category_fill
                    ws.cell(row=row, column=col).border = thin_border
                row += 1

            # Config key
            ws.cell(row=row, column=1, value=defn['config_key']).border = thin_border
            ws.cell(row=row, column=2, value=defn.get('display_name', '')).border = thin_border

            # Program default
            prog_config = im.resolve_with_inheritance(defn['config_key'], program_id, None, None)
            prog_value = prog_config.get('value') if prog_config else defn.get('default_value')
            cell = ws.cell(row=row, column=3, value=prog_value or "—")
            cell.border = thin_border
            if prog_config and prog_config.get('is_override'):
                cell.fill = override_fill

            # Location columns
            for col_idx, loc_col in enumerate(location_columns, 4):
                config = im.resolve_with_inheritance(
                    defn['config_key'],
                    program_id,
                    loc_col['clinic_id'],
                    loc_col['location_id']
                )

                effective_value = config.get('value') if config else None
                effective_level = config.get('effective_level') if config else None

                # Determine if this is inherited or set at this level
                if loc_col['location_id']:
                    is_set_here = effective_level == 'location'
                else:
                    is_set_here = effective_level == 'clinic'

                if is_set_here:
                    cell = ws.cell(row=row, column=col_idx, value=effective_value or "—")
                    cell.fill = override_fill
                else:
                    cell = ws.cell(row=row, column=col_idx, value="—")

                cell.border = thin_border

            row += 1

        # Adjust column widths
        ws.column_dimensions['A'].width = 25
        ws.column_dimensions['B'].width = 30
        ws.column_dimensions['C'].width = 20
        for col in range(4, len(headers) + 1):
            ws.column_dimensions[get_column_letter(col)].width = 18

        ws.freeze_panes = 'D2'

        # --- AUDIT HISTORY SHEET (if requested) ---
        if include_audit:
            ws2 = wb.create_sheet("Audit History")
            cursor.execute("""
                SELECT ch.config_key, ch.old_value, ch.new_value,
                       ch.changed_by, ch.changed_date, ch.change_reason,
                       c.name as clinic_name, l.name as location_name
                FROM config_history ch
                LEFT JOIN clinics c ON ch.clinic_id = c.clinic_id
                LEFT JOIN locations l ON ch.location_id = l.location_id
                WHERE ch.program_id = ?
                ORDER BY ch.changed_date DESC
                LIMIT 500
            """, (program_id,))

            audit_rows = cursor.fetchall()

            audit_headers = ['Date', 'Config Key', 'Clinic', 'Location', 'Old Value', 'New Value', 'Changed By', 'Reason']
            for col, header in enumerate(audit_headers, 1):
                cell = ws2.cell(row=1, column=col, value=header)
                cell.fill = header_fill
                cell.font = header_font
                cell.border = thin_border

            for row_num, audit in enumerate(audit_rows, 2):
                audit_dict = dict(audit)
                ws2.cell(row=row_num, column=1, value=audit_dict['changed_date']).border = thin_border
                ws2.cell(row=row_num, column=2, value=audit_dict['config_key']).border = thin_border
                ws2.cell(row=row_num, column=3, value=audit_dict.get('clinic_name', '')).border = thin_border
                ws2.cell(row=row_num, column=4, value=audit_dict.get('location_name', '')).border = thin_border
                ws2.cell(row=row_num, column=5, value=audit_dict.get('old_value', '')).border = thin_border
                ws2.cell(row=row_num, column=6, value=audit_dict.get('new_value', '')).border = thin_border
                ws2.cell(row=row_num, column=7, value=audit_dict.get('changed_by', '')).border = thin_border
                ws2.cell(row=row_num, column=8, value=audit_dict.get('change_reason', '')).border = thin_border

            ws2.freeze_panes = 'A2'

        wb.save(filepath)

        result = f"Configuration Export: {program_name}\n"
        result += "=" * 50 + "\n\n"
        result += f"File: {filepath}\n"
        result += f"Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}\n\n"
        result += f"Contents:\n"
        result += f"  - Configuration Matrix ({len(definitions)} configs x {len(location_columns)} columns)\n"
        if include_audit:
            result += f"  - Audit History (up to 500 recent changes)\n"
        result += f"\nNote: Yellow cells indicate overrides (non-inherited values)\n"

        return result

    except Exception as e:
        return f"Error exporting configs: {str(e)}"
    finally:
        if cm:
            cm.close()


# ============================================================
# AUDIT COMPLETION TOOLS
# ============================================================

@mcp.tool()
def update_clinic_manager(
    clinic: str,
    manager_name: str,
    manager_email: str,
    program: Optional[str] = None
) -> str:
    """
    Update the clinic manager contact information.

    Args:
        clinic: Clinic name or code
        manager_name: Manager's full name
        manager_email: Manager's email address
        program: Program name/prefix if clinic name is ambiguous

    Returns:
        Confirmation of update
    """
    manager = None
    try:
        import sqlite3
        db_path = os.path.expanduser("~/projects/data/client_product_database.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Find clinic
        query = """
            SELECT c.clinic_id, c.name, p.name as program_name
            FROM clinics c
            JOIN programs p ON c.program_id = p.program_id
            WHERE LOWER(c.name) LIKE LOWER(?) OR LOWER(c.code) = LOWER(?)
        """
        params = [f"%{clinic}%", clinic]

        if program:
            query += " AND (LOWER(p.name) LIKE LOWER(?) OR LOWER(p.prefix) = LOWER(?))"
            params.extend([f"%{program}%", program])

        cursor.execute(query, params)
        clinic_row = cursor.fetchone()

        if not clinic_row:
            conn.close()
            return f"Clinic not found: {clinic}"

        # Update manager info
        cursor.execute("""
            UPDATE clinics
            SET manager_name = ?, manager_email = ?, updated_date = CURRENT_TIMESTAMP
            WHERE clinic_id = ?
        """, (manager_name, manager_email, clinic_row['clinic_id']))

        conn.commit()
        conn.close()

        return f"""Clinic manager updated

Clinic: {clinic_row['name']}
Program: {clinic_row['program_name']}
Manager: {manager_name}
Email: {manager_email}
"""

    except Exception as e:
        return f"Error updating clinic manager: {str(e)}"


@mcp.tool()
def record_audit_completion(
    clinic: str,
    audit_year: int,
    date_initiated: Optional[str] = None,
    date_reviewed: Optional[str] = None,
    date_finalized: Optional[str] = None,
    date_tickets_submitted: Optional[str] = None,
    date_confirmed: Optional[str] = None,
    ticket_number: Optional[str] = None,
    audit_type: str = "Annual",
    document_version: str = "1.0",
    notes: Optional[str] = None,
    program: Optional[str] = None
) -> str:
    """
    Record or update audit completion milestone dates.

    All dates should be in YYYY-MM-DD format.
    You can update individual dates without affecting others.

    Args:
        clinic: Clinic name or code
        audit_year: Year of the audit (e.g., 2025)
        date_initiated: Date roster sent to clinic manager
        date_reviewed: Date client returned validation
        date_finalized: Date internal review finalized
        date_tickets_submitted: Date change tickets sent to dev
        date_confirmed: Date dev team confirmed complete
        ticket_number: Zendesk ticket number (without #)
        audit_type: 'Annual' or 'Quarterly' (default: Annual)
        document_version: Document version (default: 1.0)
        notes: Optional notes
        program: Program name/prefix if clinic name is ambiguous

    Returns:
        Confirmation of recorded data
    """
    try:
        import sqlite3
        db_path = os.path.expanduser("~/projects/data/client_product_database.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Find clinic
        query = """
            SELECT c.clinic_id, c.name, c.program_id, p.name as program_name
            FROM clinics c
            JOIN programs p ON c.program_id = p.program_id
            WHERE LOWER(c.name) LIKE LOWER(?) OR LOWER(c.code) = LOWER(?)
        """
        params = [f"%{clinic}%", clinic]

        if program:
            query += " AND (LOWER(p.name) LIKE LOWER(?) OR LOWER(p.prefix) = LOWER(?))"
            params.extend([f"%{program}%", program])

        cursor.execute(query, params)
        clinic_row = cursor.fetchone()

        if not clinic_row:
            conn.close()
            return f"Clinic not found: {clinic}"

        clinic_id = clinic_row['clinic_id']
        program_id = clinic_row['program_id']

        # Check if record exists
        cursor.execute("""
            SELECT completion_id FROM audit_completions
            WHERE clinic_id = ? AND audit_year = ? AND audit_type = ?
        """, (clinic_id, audit_year, audit_type))

        existing = cursor.fetchone()

        if existing:
            # Update existing
            cursor.execute("""
                UPDATE audit_completions SET
                    date_initiated = COALESCE(?, date_initiated),
                    date_reviewed = COALESCE(?, date_reviewed),
                    date_finalized = COALESCE(?, date_finalized),
                    date_tickets_submitted = COALESCE(?, date_tickets_submitted),
                    date_confirmed = COALESCE(?, date_confirmed),
                    ticket_number = COALESCE(?, ticket_number),
                    document_version = COALESCE(?, document_version),
                    notes = COALESCE(?, notes),
                    updated_date = CURRENT_TIMESTAMP
                WHERE completion_id = ?
            """, (
                date_initiated, date_reviewed, date_finalized,
                date_tickets_submitted, date_confirmed, ticket_number,
                document_version, notes, existing['completion_id']
            ))
            action = "Updated"
        else:
            # Insert new
            cursor.execute("""
                INSERT INTO audit_completions (
                    clinic_id, program_id, audit_year, audit_type,
                    date_initiated, date_reviewed, date_finalized,
                    date_tickets_submitted, date_confirmed,
                    ticket_number, document_version, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                clinic_id, program_id, audit_year, audit_type,
                date_initiated, date_reviewed, date_finalized,
                date_tickets_submitted, date_confirmed,
                ticket_number, document_version, notes
            ))
            action = "Created"

        conn.commit()

        # Fetch the current state
        cursor.execute("""
            SELECT * FROM audit_completions
            WHERE clinic_id = ? AND audit_year = ? AND audit_type = ?
        """, (clinic_id, audit_year, audit_type))
        record = cursor.fetchone()

        conn.close()

        output = f"""{action} audit completion record

Clinic: {clinic_row['name']}
Program: {clinic_row['program_name']}
Audit: {audit_year} {audit_type}

TIMELINE
---------
Initiated:          {record['date_initiated'] or '(not set)'}
Reviewed by Client: {record['date_reviewed'] or '(not set)'}
Finalized:          {record['date_finalized'] or '(not set)'}
Tickets Submitted:  {record['date_tickets_submitted'] or '(not set)'}
Confirmed:          {record['date_confirmed'] or '(not set)'}

DETAILS
-------
Ticket #: {record['ticket_number'] or '(not set)'}
Version:  {record['document_version']}
Notes:    {record['notes'] or '(none)'}
"""
        return output

    except Exception as e:
        return f"Error recording audit completion: {str(e)}"


@mcp.tool()
def generate_audit_memo(
    clinic: str,
    audit_year: int,
    audit_type: str = "Annual",
    program: Optional[str] = None,
    output_dir: Optional[str] = None
) -> str:
    """
    Generate a filled audit completion memo Word document.

    Pulls data from the audit_completions table and calculates
    metrics from access_reviews. Outputs a ready-to-sign document.

    Args:
        clinic: Clinic name or code
        audit_year: Year of the audit (e.g., 2025)
        audit_type: 'Annual' or 'Quarterly' (default: Annual)
        program: Program name/prefix if clinic name is ambiguous
        output_dir: Directory to save file (default: ~/Downloads)

    Returns:
        Path to generated document and summary
    """
    try:
        from docxtpl import DocxTemplate
        from datetime import datetime
        import sqlite3

        db_path = os.path.expanduser("~/projects/data/client_product_database.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Find clinic
        query = """
            SELECT c.clinic_id, c.name, c.manager_name, c.manager_email,
                   c.program_id, p.name as program_name
            FROM clinics c
            JOIN programs p ON c.program_id = p.program_id
            WHERE LOWER(c.name) LIKE LOWER(?) OR LOWER(c.code) = LOWER(?)
        """
        params = [f"%{clinic}%", clinic]

        if program:
            query += " AND (LOWER(p.name) LIKE LOWER(?) OR LOWER(p.prefix) = LOWER(?))"
            params.extend([f"%{program}%", program])

        cursor.execute(query, params)
        clinic_row = cursor.fetchone()

        if not clinic_row:
            conn.close()
            return f"Clinic not found: {clinic}"

        clinic_id = clinic_row['clinic_id']

        # Get audit completion record
        cursor.execute("""
            SELECT * FROM audit_completions
            WHERE clinic_id = ? AND audit_year = ? AND audit_type = ?
        """, (clinic_id, audit_year, audit_type))

        record = cursor.fetchone()
        if not record:
            conn.close()
            return f"No audit completion record found for {clinic_row['name']} {audit_year} {audit_type}. Use record_audit_completion first."

        # Calculate metrics
        cursor.execute("""
            SELECT
                COUNT(*) as total_reviewed,
                SUM(CASE WHEN status = 'Revoked' THEN 1 ELSE 0 END) as revocations,
                SUM(CASE WHEN status = 'Modified' THEN 1 ELSE 0 END) as modifications
            FROM access_reviews ar
            JOIN user_access ua ON ar.access_id = ua.access_id
            WHERE ua.clinic_id = ?
            AND strftime('%Y', ar.review_date) = ?
        """, (clinic_id, str(audit_year)))
        metrics = cursor.fetchone()

        cursor.execute("""
            SELECT COUNT(*) as new_requests
            FROM user_access
            WHERE clinic_id = ? AND strftime('%Y', granted_date) = ?
        """, (clinic_id, str(audit_year)))
        new_grants = cursor.fetchone()

        conn.close()

        # Format dates
        def format_date(date_str):
            if not date_str:
                return '(Not Set)'
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                return dt.strftime('%B %d, %Y')
            except:
                return date_str

        # Prepare context
        context = {
            'clinic_name': clinic_row['name'],
            'audit_year': audit_year,
            'audit_type': audit_type,
            'document_version': record['document_version'] or '1.0',
            'date_initiated': format_date(record['date_initiated']),
            'date_reviewed': format_date(record['date_reviewed']),
            'date_finalized': format_date(record['date_finalized']),
            'date_tickets_submitted': format_date(record['date_tickets_submitted']),
            'date_confirmed': format_date(record['date_confirmed']),
            'ticket_number': record['ticket_number'] or '(Not Set)',
            'manager_name': clinic_row['manager_name'] or '(Not Set)',
            'manager_email': clinic_row['manager_email'] or '(Not Set)',
            'total_reviewed': metrics['total_reviewed'] if metrics else 0,
            'revocations': metrics['revocations'] if metrics else 0,
            'modifications': metrics['modifications'] if metrics else 0,
            'new_requests': new_grants['new_requests'] if new_grants else 0
        }

        # Load and render template
        template_path = os.path.expanduser(
            '~/projects/configurations_toolkit/templates/audit_completion_memo.docx'
        )

        if not os.path.exists(template_path):
            return f"Template not found: {template_path}\nRun the template creation script first."

        doc = DocxTemplate(template_path)
        doc.render(context)

        # Save output
        if output_dir:
            out_path = os.path.expanduser(output_dir)
        else:
            out_path = os.path.expanduser('~/Downloads')
        os.makedirs(out_path, exist_ok=True)

        safe_clinic = clinic_row['name'].replace(' ', '_').replace('/', '-')
        filename = f"{safe_clinic}_Audit_Memo_{audit_year}_{audit_type}.docx"
        filepath = os.path.join(out_path, filename)

        doc.save(filepath)

        return f"""Audit memo generated

File: {filepath}

DOCUMENT CONTENTS
-----------------
Clinic: {clinic_row['name']}
Audit: {audit_year} {audit_type}
Manager: {context['manager_name']} ({context['manager_email']})

Metrics:
- Total Reviewed: {context['total_reviewed']}
- Revocations: {context['revocations']}
- Modifications: {context['modifications']}
- New Requests: {context['new_requests']}

Timeline:
- Initiated: {context['date_initiated']}
- Reviewed: {context['date_reviewed']}
- Finalized: {context['date_finalized']}
- Tickets: {context['date_tickets_submitted']}
- Confirmed: {context['date_confirmed']}

Ticket #: {context['ticket_number']}
"""

    except ImportError:
        return "Error: docxtpl not installed. Run: pip install docxtpl --break-system-packages"
    except Exception as e:
        return f"Error generating audit memo: {str(e)}"


# ============================================================
# RUN SERVER
# ============================================================
if __name__ == "__main__":
    mcp.run()
