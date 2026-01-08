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
- Client/Program: list_clients, get_client_programs, get_program_by_prefix, create_program, create_requirement, link_requirement_to_story
- User Stories: list_stories, get_story, create_story, update_story, get_approval_pipeline
- Test Cases: list_test_cases, get_test_summary, create_test_case, update_test_result
- Reporting: get_program_health, get_client_tree, search_stories, get_coverage_gaps

ONBOARDING FORM TOOLKIT:
- Question Management: list_form_questions, add_form_question, update_form_question, remove_form_question, reorder_form_questions

DASHBOARD DATA GENERATION:
- generate_dashboard_data: Generate JSON for clinic configuration dashboard (GitHub Pages)
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


def validate_choice(value: str, valid_options: list, field_name: str, descriptions: dict = None) -> Optional[str]:
    """
    Validate that a value is one of the valid options.

    Args:
        value: The value to validate
        valid_options: List of valid option values
        field_name: Name of the field for error message
        descriptions: Optional dict mapping option values to descriptions

    Returns:
        Error message string if invalid, None if valid
    """
    if value not in valid_options:
        error = f"Invalid {field_name}: '{value}'\n\nValid {field_name}s:\n"
        for opt in valid_options:
            desc = descriptions.get(opt, "") if descriptions else ""
            if desc:
                error += f"  • {opt} - {desc}\n"
            else:
                error += f"  • {opt}\n"
        return error.rstrip()
    return None


def validate_optional_choice(value: Optional[str], valid_options: list, field_name: str,
                             descriptions: dict = None) -> Optional[str]:
    """
    Validate an optional field - only validates if value is not None.

    Returns:
        Error message string if invalid, None if valid or not provided
    """
    if value is None:
        return None
    return validate_choice(value, valid_options, field_name, descriptions)


def log_audit(cursor, record_type: str, record_id: str, action: str,
              field_changed: str, old_value, new_value, changed_by: str,
              changed_date: str, change_reason: str) -> None:
    """
    Insert an audit history record.

    Args:
        cursor: Database cursor
        record_type: Type of record (client, story, test, etc.)
        record_id: ID of the record being audited
        action: Action performed (Created, Updated, Deleted)
        field_changed: Name of field changed or record type for creates
        old_value: Previous value (None for creates)
        new_value: New value (usually JSON for creates/deletes)
        changed_by: Who made the change (e.g., 'MCP:tool_name')
        changed_date: Timestamp of the change
        change_reason: Description of why the change was made
    """
    cursor.execute(
        """
        INSERT INTO audit_history (
            record_type, record_id, action, field_changed,
            old_value, new_value, changed_by, changed_date, change_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (record_type, record_id, action, field_changed, old_value,
         new_value, changed_by, changed_date, change_reason)
    )


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


@mcp.tool()
def create_client(
    client_name: str,
    status: str = "Active",
    short_name: Optional[str] = None,
    client_type: Optional[str] = None,
    description: Optional[str] = None,
    primary_contact_name: Optional[str] = None,
    primary_contact_email: Optional[str] = None,
    primary_contact_phone: Optional[str] = None,
    contract_reference: Optional[str] = None,
    contract_start_date: Optional[str] = None,
    contract_end_date: Optional[str] = None,
    source_document: Optional[str] = None
) -> str:
    """
    Create a new client organization in the requirements database.

    PURPOSE:
        Creates a top-level client record. Clients are the root of the hierarchy:
        Client → Program → Story → Test Case. Each client can have multiple
        programs, and all requirements traceability flows from the client.

    R EQUIVALENT:
        Like adding a row to a clients data.frame, with auto-generated UUID
        and schema validation. Similar to tibble::add_row() with constraints.

    Args:
        client_name: Full client name (e.g., "Providence Health & Services", "Propel Health")
        status: "Active" or "Inactive" (default: "Active")
        short_name: Abbreviated name for display (e.g., "Providence", "Propel")
        client_type: "External" (customer) or "Internal" (Propel Health internal)
        description: Description of the client or relationship
        primary_contact_name: Main point of contact
        primary_contact_email: Contact email
        primary_contact_phone: Contact phone
        contract_reference: Contract or agreement reference (e.g., "Providence PSA 2026")
        contract_start_date: Contract start date (YYYY-MM-DD format)
        contract_end_date: Contract end date (YYYY-MM-DD format)
        source_document: Source document for requirements (e.g., "Exhibit E - KPIs")

    Returns:
        Confirmation with client_id, name, and next steps

    WHY THIS APPROACH:
        - Case-insensitive uniqueness check prevents duplicate clients
        - UUID generation ensures globally unique identifiers
        - Self-healing schema: adds missing columns if they don't exist
        - Comprehensive audit logging for Part 11 compliance
        - Stores all metadata needed for contract and contact tracking

    Example (minimal - internal):
        create_client(
            client_name="Propel Health",
            client_type="Internal",
            description="Platform-wide features and internal capabilities"
        )

    Example (full - external customer):
        create_client(
            client_name="Providence Health & Services",
            short_name="Providence",
            client_type="External",
            description="Health system partner - breast cancer prevention programs",
            primary_contact_name="Kim Smith",
            primary_contact_email="kim.smith@providence.org",
            contract_reference="Providence PSA 2026",
            contract_start_date="2026-01-01",
            contract_end_date="2026-12-31",
            source_document="Exhibit E - Key Performance Indicators"
        )
    """
    import sqlite3
    import uuid
    import json
    import re

    conn = None
    try:
        # ----------------------------------------------------------------
        # STEP 1: Validate status
        # ----------------------------------------------------------------
        status_descriptions = {
            "Active": "Client is currently active",
            "Inactive": "Client relationship is paused or ended"
        }
        if error := validate_choice(status, list(status_descriptions.keys()), "status", status_descriptions):
            return error

        # ----------------------------------------------------------------
        # STEP 2: Validate client_type if provided
        # ----------------------------------------------------------------
        client_type_descriptions = {
            "External": "Customer organization",
            "Internal": "Propel Health internal project"
        }
        if error := validate_optional_choice(client_type, list(client_type_descriptions.keys()),
                                              "client_type", client_type_descriptions):
            return error

        # ----------------------------------------------------------------
        # STEP 3: Validate date formats if provided
        # ----------------------------------------------------------------
        date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')

        if contract_start_date is not None:
            if not date_pattern.match(contract_start_date):
                return (
                    f"Invalid contract_start_date format: '{contract_start_date}'\n\n"
                    f"Please use YYYY-MM-DD format (e.g., '2026-01-01')"
                )

        if contract_end_date is not None:
            if not date_pattern.match(contract_end_date):
                return (
                    f"Invalid contract_end_date format: '{contract_end_date}'\n\n"
                    f"Please use YYYY-MM-DD format (e.g., '2026-12-31')"
                )

        # ----------------------------------------------------------------
        # STEP 4: Validate email format if provided
        # ----------------------------------------------------------------
        if primary_contact_email is not None:
            email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
            if not email_pattern.match(primary_contact_email):
                return (
                    f"Invalid email format: '{primary_contact_email}'\n\n"
                    f"Please provide a valid email address."
                )

        # ----------------------------------------------------------------
        # STEP 5: Connect to database
        # ----------------------------------------------------------------
        conn = sqlite3.connect(REQ_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # ----------------------------------------------------------------
        # STEP 6: Self-healing schema - add missing columns if needed
        # This ensures the tool works even if the schema hasn't been updated
        # ----------------------------------------------------------------
        additional_columns = [
            ("short_name", "TEXT"),
            ("client_type", "TEXT"),
            ("primary_contact_name", "TEXT"),
            ("primary_contact_email", "TEXT"),
            ("primary_contact_phone", "TEXT"),
            ("contract_reference", "TEXT"),
            ("contract_start_date", "TEXT"),
            ("contract_end_date", "TEXT"),
            ("source_document", "TEXT")
        ]

        # Get existing columns
        cursor.execute("PRAGMA table_info(clients)")
        existing_columns = {row['name'] for row in cursor.fetchall()}

        # Add missing columns
        for col_name, col_type in additional_columns:
            if col_name not in existing_columns:
                cursor.execute(f"ALTER TABLE clients ADD COLUMN {col_name} {col_type}")

        # ----------------------------------------------------------------
        # STEP 7: Check for duplicate client name (case-insensitive)
        # ----------------------------------------------------------------
        cursor.execute(
            "SELECT client_id, name FROM clients WHERE LOWER(name) = LOWER(?)",
            (client_name,)
        )
        existing = cursor.fetchone()

        if existing:
            return (
                f"Client already exists: '{existing['name']}'\n\n"
                f"Client ID: {existing['client_id']}\n\n"
                f"If you need to update this client, use update_client() instead.\n"
                f"If this is a different client, please use a unique name."
            )

        # ----------------------------------------------------------------
        # STEP 8: Generate client_id and prepare data
        # ----------------------------------------------------------------
        client_id = str(uuid.uuid4())
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # ----------------------------------------------------------------
        # STEP 9: Insert the client record
        # ----------------------------------------------------------------
        cursor.execute(
            """
            INSERT INTO clients (
                client_id, name, short_name, client_type, description, status,
                primary_contact_name, primary_contact_email, primary_contact_phone,
                contract_reference, contract_start_date, contract_end_date,
                source_document, created_date, updated_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                client_name,
                short_name,
                client_type,
                description,
                status,
                primary_contact_name,
                primary_contact_email,
                primary_contact_phone,
                contract_reference,
                contract_start_date,
                contract_end_date,
                source_document,
                now,
                now
            )
        )

        # ----------------------------------------------------------------
        # STEP 10: Log to audit_history for Part 11 compliance
        # ----------------------------------------------------------------
        # Create a JSON snapshot of all provided values for the audit trail
        audit_data = {
            'client_id': client_id,
            'name': client_name,
            'short_name': short_name,
            'client_type': client_type,
            'description': description,
            'status': status,
            'primary_contact_name': primary_contact_name,
            'primary_contact_email': primary_contact_email,
            'primary_contact_phone': primary_contact_phone,
            'contract_reference': contract_reference,
            'contract_start_date': contract_start_date,
            'contract_end_date': contract_end_date,
            'source_document': source_document
        }
        # Remove None values for cleaner audit log
        audit_data = {k: v for k, v in audit_data.items() if v is not None}

        log_audit(
            cursor,
            record_type='client',
            record_id=client_id,
            action='Created',
            field_changed='client',
            old_value=None,
            new_value=json.dumps(audit_data),
            changed_by='MCP:create_client',
            changed_date=now,
            change_reason=f'New client created: {client_name}'
        )

        conn.commit()

        # ----------------------------------------------------------------
        # STEP 11: Build success response
        # ----------------------------------------------------------------
        display_name = short_name or client_name
        result = f"""Client created successfully!

Client Details:
  Client ID: {client_id}
  Name: {client_name}
"""
        if short_name:
            result += f"  Short Name: {short_name}\n"
        if client_type:
            result += f"  Type: {client_type}\n"
        result += f"  Status: {status}\n"
        if description:
            result += f"  Description: {description[:80]}{'...' if len(description) > 80 else ''}\n"

        if primary_contact_name or primary_contact_email:
            result += "\nContact Information:\n"
            if primary_contact_name:
                result += f"  Contact: {primary_contact_name}\n"
            if primary_contact_email:
                result += f"  Email: {primary_contact_email}\n"
            if primary_contact_phone:
                result += f"  Phone: {primary_contact_phone}\n"

        if contract_reference or contract_start_date:
            result += "\nContract Information:\n"
            if contract_reference:
                result += f"  Reference: {contract_reference}\n"
            if contract_start_date:
                result += f"  Start Date: {contract_start_date}\n"
            if contract_end_date:
                result += f"  End Date: {contract_end_date}\n"
            if source_document:
                result += f"  Source Document: {source_document}\n"

        result += f"""
Created At: {now}

Next Steps:
  • create_program(client_name="{display_name}", prefix="XXX", program_name="...") - Add a program
  • get_client_tree() - View client/program hierarchy
"""
        return result

    except Exception as e:
        return f"Error creating client: {str(e)}"

    finally:
        if conn:
            conn.close()


@mcp.tool()
def create_program(
    client_name: str,
    prefix: str,
    program_name: str,
    description: Optional[str] = None,
    status: str = "Active"
) -> str:
    """
    Create a new program for tracking user stories, acceptance criteria, and test cases.

    PURPOSE:
        Creates a program under an existing client. Programs group related user stories
        and test cases. Each program has a unique prefix used to generate story IDs
        (e.g., prefix "P4M" creates stories like P4M-AUTH-001).

    R EQUIVALENT:
        Like creating a new project folder in RStudio, but with database tracking
        and unique ID generation.

    Args:
        client_name: Parent client name (must exist, case-insensitive match)
        prefix: Short prefix for story IDs (2-6 alphanumeric chars, auto-converted to uppercase)
        program_name: Full program name (e.g., "Prevention4ME")
        description: Optional program description
        status: Program status (default: "Active")

    Returns:
        Confirmation with program ID and example story IDs, or helpful error message

    WHY THIS APPROACH:
        - Validates inputs thoroughly to prevent data integrity issues
        - Case-insensitive client lookup for user convenience
        - Prefix uniqueness across ALL programs prevents story ID collisions
        - Audit logging for FDA 21 CFR Part 11 compliance
    """
    # Import here to keep dependency local (matches pattern in other tools)
    import sqlite3
    import uuid
    import re

    conn = None
    try:
        # ----------------------------------------------------------------
        # STEP 1: Validate prefix format
        # Prefix must be 2-6 alphanumeric characters (letters and numbers only)
        # Auto-convert to uppercase for consistency
        # ----------------------------------------------------------------
        prefix_upper = prefix.upper().strip()

        # Check length
        if len(prefix_upper) < 2 or len(prefix_upper) > 6:
            return (
                f"Invalid prefix length: '{prefix}'\n\n"
                f"Prefix must be 2-6 characters. Examples:\n"
                f"  • P4M (3 chars) - good\n"
                f"  • DISCOVER (8 chars) - too long, try 'DISC'\n"
                f"  • X (1 char) - too short, try 'XX' or longer"
            )

        # Check alphanumeric only (no special characters, spaces, or dashes)
        if not re.match(r'^[A-Z0-9]+$', prefix_upper):
            return (
                f"Invalid prefix format: '{prefix}'\n\n"
                f"Prefix must contain only letters and numbers (no spaces, dashes, or special characters).\n"
                f"Examples:\n"
                f"  • P4M - good\n"
                f"  • P-4M - bad (contains dash)\n"
                f"  • P 4M - bad (contains space)"
            )

        # ----------------------------------------------------------------
        # STEP 2: Connect to requirements database
        # Using direct sqlite3 connection (not the db manager class) for
        # more control over the transaction and audit logging
        # ----------------------------------------------------------------
        conn = sqlite3.connect(REQ_DB_PATH)
        conn.row_factory = sqlite3.Row  # Allows dict-style access to rows
        cursor = conn.cursor()

        # ----------------------------------------------------------------
        # STEP 3: Validate client exists (case-insensitive search)
        # Show available clients if not found to help the user
        # ----------------------------------------------------------------
        cursor.execute(
            "SELECT client_id, name FROM clients WHERE LOWER(name) = LOWER(?)",
            (client_name,)
        )
        client_row = cursor.fetchone()

        if not client_row:
            # Client not found - show available clients to help user
            cursor.execute("SELECT name FROM clients WHERE status = 'Active' ORDER BY name")
            available = cursor.fetchall()

            if available:
                client_list = "\n".join(f"  • {row['name']}" for row in available)
                return (
                    f"Client not found: '{client_name}'\n\n"
                    f"Available clients:\n{client_list}\n\n"
                    f"Hint: Client names are matched case-insensitively."
                )
            else:
                return (
                    f"Client not found: '{client_name}'\n\n"
                    f"No active clients exist in the database. "
                    f"Please create a client first."
                )

        client_id = client_row['client_id']
        client_name_actual = client_row['name']  # Use actual casing from database

        # ----------------------------------------------------------------
        # STEP 4: Check prefix uniqueness across ALL programs
        # This is critical - prevents story ID collisions like P4M-AUTH-001
        # appearing in multiple programs
        # ----------------------------------------------------------------
        cursor.execute(
            "SELECT name, prefix FROM programs WHERE UPPER(prefix) = ?",
            (prefix_upper,)
        )
        existing_prefix = cursor.fetchone()

        if existing_prefix:
            return (
                f"Prefix already in use: '{prefix_upper}'\n\n"
                f"The prefix '{existing_prefix['prefix']}' is already assigned to "
                f"program '{existing_prefix['name']}'.\n\n"
                f"Each prefix must be unique across ALL programs to prevent story ID collisions.\n"
                f"Suggestion: Try a variation like '{prefix_upper}2' or choose a different abbreviation."
            )

        # ----------------------------------------------------------------
        # STEP 5: Check program name uniqueness within the client
        # Same client can't have two programs with identical names
        # ----------------------------------------------------------------
        cursor.execute(
            "SELECT name FROM programs WHERE client_id = ? AND LOWER(name) = LOWER(?)",
            (client_id, program_name)
        )
        existing_name = cursor.fetchone()

        if existing_name:
            return (
                f"Program name already exists for this client: '{existing_name['name']}'\n\n"
                f"Client '{client_name_actual}' already has a program with this name.\n"
                f"Please choose a different program name."
            )

        # ----------------------------------------------------------------
        # STEP 6: Generate program_id and insert
        # Using UUID4 for globally unique identifier
        # ----------------------------------------------------------------
        program_id = str(uuid.uuid4())
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute(
            """
            INSERT INTO programs (
                program_id, client_id, name, prefix, description, status,
                created_date, updated_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (program_id, client_id, program_name, prefix_upper, description, status, now, now)
        )

        # ----------------------------------------------------------------
        # STEP 7: Log to audit_history for Part 11 compliance
        # This creates a permanent record of who created what and when
        # ----------------------------------------------------------------
        cursor.execute(
            """
            INSERT INTO audit_history (
                record_type, record_id, action, field_changed,
                old_value, new_value, changed_by, changed_date, change_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                'program',                          # record_type
                program_id,                         # record_id
                'Created',                          # action
                'program',                          # field_changed
                None,                               # old_value (none for create)
                f'{program_name} [{prefix_upper}]', # new_value
                'MCP:create_program',               # changed_by - identifies the tool
                now,                                # changed_date
                f'New program created under client {client_name_actual}'  # change_reason
            )
        )

        # Commit both inserts together (atomic transaction)
        conn.commit()

        # ----------------------------------------------------------------
        # STEP 8: Build success response with next steps
        # Show example story IDs so user understands the prefix usage
        # ----------------------------------------------------------------
        result = f"""Program created successfully!

Program Details:
  Name: {program_name}
  Prefix: {prefix_upper}
  Client: {client_name_actual}
  Status: {status}
  Program ID: {program_id}
"""
        if description:
            result += f"  Description: {description}\n"

        result += f"""
Next Steps - Example Story IDs:
  When you create user stories for this program, they'll be named like:
  • {prefix_upper}-AUTH-001 (Authentication story)
  • {prefix_upper}-DASH-001 (Dashboard story)
  • {prefix_upper}-DATA-001 (Data management story)

Use these commands to add content:
  • list_stories(program_prefix="{prefix_upper}") - View all stories
  • get_program_by_prefix(prefix="{prefix_upper}") - View program stats
"""
        return result

    except Exception as e:
        return f"Error creating program: {str(e)}"

    finally:
        # Always close the connection, even if an error occurred
        if conn:
            conn.close()


@mcp.tool()
def create_requirement(
    program_prefix: str,
    title: str,
    description: str,
    source_file: Optional[str] = None,
    priority: str = "Medium",
    requirement_type: str = "Technical"
) -> str:
    """
    Create a raw requirement entry that can later be converted to user stories.

    PURPOSE:
        Captures raw requirements from various sources (meetings, documents,
        stakeholder requests) before they're refined into user stories.
        This preserves the original requirement for traceability.

    R EQUIVALENT:
        Like adding a row to a requirements data.frame, with auto-generated
        IDs and source tracking.

    REQUIREMENT ID FORMAT:
        Auto-generated as {PREFIX}-REQ-{NNN}
        Example: P4M-REQ-001, P4M-REQ-002

    Args:
        program_prefix: Program prefix (e.g., "P4M", "PROP")
        title: Short requirement title
        description: Full requirement description
        source_file: Where this came from (e.g., "Client Meeting 2025-01-06", "SRS v1.2")
        priority: "High", "Medium", "Low" (default: "Medium")
        requirement_type: "Technical", "Workflow", "Process", "Integration" (default: "Technical")

    Returns:
        Confirmation with generated requirement_id

    WHY THIS APPROACH:
        - Preserves raw requirements before story conversion
        - Tracks source for traceability
        - Auto-increments requirement number within program
        - Audit logging for Part 11 compliance
    """
    import sqlite3
    import uuid
    import re

    conn = None
    try:
        # ----------------------------------------------------------------
        # STEP 1: Validate priority
        # ----------------------------------------------------------------
        valid_priorities = ["High", "Medium", "Low"]
        if priority not in valid_priorities:
            return (
                f"Invalid priority: '{priority}'\n\n"
                f"Valid priorities:\n"
                f"  • High - Critical, must be addressed first\n"
                f"  • Medium - Important, normal priority\n"
                f"  • Low - Nice to have, can be deferred"
            )

        # ----------------------------------------------------------------
        # STEP 2: Validate requirement_type
        # ----------------------------------------------------------------
        valid_types = ["Technical", "Workflow", "Process", "Integration"]
        if requirement_type not in valid_types:
            type_list = "\n".join(f"  • {t}" for t in valid_types)
            return (
                f"Invalid requirement_type: '{requirement_type}'\n\n"
                f"Valid types:\n{type_list}\n\n"
                f"Descriptions:\n"
                f"  • Technical - System/software functionality\n"
                f"  • Workflow - Business process steps\n"
                f"  • Process - Operational procedures\n"
                f"  • Integration - External system connections"
            )

        # ----------------------------------------------------------------
        # STEP 3: Connect to database and validate program exists
        # ----------------------------------------------------------------
        conn = sqlite3.connect(REQ_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT program_id, name, prefix FROM programs WHERE UPPER(prefix) = ?",
            (program_prefix.upper(),)
        )
        program_row = cursor.fetchone()

        if not program_row:
            # Program not found - show available programs
            cursor.execute(
                "SELECT prefix, name FROM programs WHERE status = 'Active' ORDER BY prefix"
            )
            available = cursor.fetchall()

            if available:
                prog_list = "\n".join(f"  • [{row['prefix']}] {row['name']}" for row in available)
                return (
                    f"Program not found with prefix: '{program_prefix}'\n\n"
                    f"Available programs:\n{prog_list}\n\n"
                    f"Hint: Use the prefix (e.g., 'P4M'), not the full name."
                )
            else:
                return (
                    f"Program not found: '{program_prefix}'\n\n"
                    f"No active programs exist. Create a program first with create_program()."
                )

        program_id = program_row['program_id']
        program_name = program_row['name']
        prefix = program_row['prefix']

        # ----------------------------------------------------------------
        # STEP 4: Generate requirement_id by finding max existing number
        # Format: {PREFIX}-REQ-{NNN}
        # ----------------------------------------------------------------
        cursor.execute(
            """
            SELECT requirement_id FROM requirements
            WHERE requirement_id LIKE ?
            ORDER BY requirement_id DESC
            LIMIT 1
            """,
            (f"{prefix}-REQ-%",)
        )
        last_req = cursor.fetchone()

        if last_req:
            # Extract the number from the last requirement ID
            last_id = last_req['requirement_id']
            match = re.search(r'-REQ-(\d+)$', last_id)
            if match:
                next_num = int(match.group(1)) + 1
            else:
                next_num = 1
        else:
            next_num = 1

        # Format with leading zeros (3 digits)
        requirement_id = f"{prefix}-REQ-{next_num:03d}"

        # ----------------------------------------------------------------
        # STEP 5: Insert the requirement
        # ----------------------------------------------------------------
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute(
            """
            INSERT INTO requirements (
                requirement_id, program_id, title, description, raw_text,
                source_file, priority, requirement_type,
                created_date, updated_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                requirement_id,
                program_id,
                title,
                description,
                description,  # raw_text = original description
                source_file,
                priority,
                requirement_type,
                now,
                now
            )
        )

        # ----------------------------------------------------------------
        # STEP 6: Log to audit_history for Part 11 compliance
        # ----------------------------------------------------------------
        cursor.execute(
            """
            INSERT INTO audit_history (
                record_type, record_id, action, field_changed,
                old_value, new_value, changed_by, changed_date, change_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                'requirement',                      # record_type
                requirement_id,                     # record_id
                'Created',                          # action
                'requirement',                      # field_changed
                None,                               # old_value (none for create)
                title,                              # new_value
                'MCP:create_requirement',           # changed_by
                now,                                # changed_date
                f'New requirement created in {program_name} [{prefix}]'  # change_reason
            )
        )

        conn.commit()

        # ----------------------------------------------------------------
        # STEP 7: Build success response
        # ----------------------------------------------------------------
        result = f"""Requirement created successfully!

Requirement Details:
  Requirement ID: {requirement_id}
  Title: {title}
  Program: {program_name} [{prefix}]
  Priority: {priority}
  Type: {requirement_type}
"""
        if source_file:
            result += f"  Source: {source_file}\n"

        result += f"""
Description:
  {description[:200]}{'...' if len(description) > 200 else ''}

Next Steps:
  • Convert to user story: create_story(program_prefix="{prefix}", ...)
  • View program requirements (use search_stories with program filter)
  • Link stories to this requirement using requirement_id

Traceability:
  This requirement ID ({requirement_id}) can be linked to user stories
  for full requirements traceability in compliance reporting.
"""
        return result

    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint" in str(e):
            return (
                f"Requirement ID conflict: '{requirement_id}' already exists.\n\n"
                f"This shouldn't happen with auto-increment. Please report this bug."
            )
        return f"Database integrity error: {str(e)}"

    except Exception as e:
        return f"Error creating requirement: {str(e)}"

    finally:
        if conn:
            conn.close()


@mcp.tool()
def link_requirement_to_story(
    requirement_id: str,
    story_id: str,
    coverage_status: str = "Full",
    gap_notes: Optional[str] = None
) -> str:
    """
    Create traceability link between a requirement and a user story.

    PURPOSE:
        Establishes formal traceability between raw requirements and user stories.
        Essential for compliance reporting and gap analysis.

    R EQUIVALENT:
        Like creating a join table row that links two data.frames by foreign key,
        with metadata about the relationship quality.

    Args:
        requirement_id: Requirement ID (e.g., "P4M-REQ-001")
        story_id: Story ID (e.g., "P4M-AUTH-001")
        coverage_status: How well the story covers the requirement
                        "Full" - Story completely addresses requirement
                        "Partial" - Story partially addresses requirement
                        "None" - Placeholder link, no coverage yet
        gap_notes: Notes explaining gaps if coverage is Partial or None

    Returns:
        Confirmation with traceability link details

    WHY THIS APPROACH:
        - Creates formal audit trail between requirements and implementation
        - Supports compliance gap analysis reporting
        - Validates both entities exist and belong to same program
        - Audit logging for Part 11 compliance
    """
    import sqlite3

    conn = None
    try:
        # ----------------------------------------------------------------
        # STEP 1: Validate coverage_status
        # ----------------------------------------------------------------
        valid_coverage = ["Full", "Partial", "None"]
        if coverage_status not in valid_coverage:
            return (
                f"Invalid coverage_status: '{coverage_status}'\n\n"
                f"Valid values:\n"
                f"  • Full - Story completely addresses the requirement\n"
                f"  • Partial - Story partially addresses the requirement\n"
                f"  • None - Placeholder link, requirement not yet covered"
            )

        # Warn if Partial/None without gap_notes
        if coverage_status in ["Partial", "None"] and not gap_notes:
            missing_notes_warning = True
        else:
            missing_notes_warning = False

        # ----------------------------------------------------------------
        # STEP 2: Connect to database
        # ----------------------------------------------------------------
        conn = sqlite3.connect(REQ_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # ----------------------------------------------------------------
        # STEP 3: Validate requirement exists and get its program_id
        # ----------------------------------------------------------------
        cursor.execute(
            """
            SELECT r.requirement_id, r.title as req_title, r.program_id,
                   p.name as program_name, p.prefix
            FROM requirements r
            JOIN programs p ON r.program_id = p.program_id
            WHERE r.requirement_id = ?
            """,
            (requirement_id,)
        )
        req_row = cursor.fetchone()

        if not req_row:
            # Requirement not found - provide helpful suggestions
            parts = requirement_id.split('-')
            if len(parts) >= 2:
                prefix = parts[0]
                cursor.execute(
                    "SELECT requirement_id, title FROM requirements WHERE requirement_id LIKE ? ORDER BY requirement_id LIMIT 5",
                    (f"{prefix}-REQ-%",)
                )
                similar = cursor.fetchall()
                if similar:
                    similar_list = "\n".join(f"  • {r['requirement_id']}: {r['title'][:40]}" for r in similar)
                    return (
                        f"Requirement not found: '{requirement_id}'\n\n"
                        f"Requirements in {prefix}:\n{similar_list}"
                    )

            return f"Requirement not found: '{requirement_id}'"

        req_program_id = req_row['program_id']
        req_title = req_row['req_title']
        program_name = req_row['program_name']
        prefix = req_row['prefix']

        # ----------------------------------------------------------------
        # STEP 4: Validate story exists and get its program_id
        # ----------------------------------------------------------------
        cursor.execute(
            """
            SELECT s.story_id, s.title as story_title, s.program_id
            FROM user_stories s
            WHERE s.story_id = ?
            """,
            (story_id,)
        )
        story_row = cursor.fetchone()

        if not story_row:
            # Story not found - provide helpful suggestions
            parts = story_id.split('-')
            if len(parts) >= 2:
                prefix_part = parts[0]
                cursor.execute(
                    "SELECT story_id, title FROM user_stories WHERE story_id LIKE ? ORDER BY story_id LIMIT 5",
                    (f"{prefix_part}-%",)
                )
                similar = cursor.fetchall()
                if similar:
                    similar_list = "\n".join(f"  • {s['story_id']}: {s['title'][:40]}" for s in similar)
                    return (
                        f"Story not found: '{story_id}'\n\n"
                        f"Stories in {prefix_part}:\n{similar_list}"
                    )

            return f"Story not found: '{story_id}'"

        story_program_id = story_row['program_id']
        story_title = story_row['story_title']

        # ----------------------------------------------------------------
        # STEP 5: Validate both belong to the same program
        # ----------------------------------------------------------------
        if req_program_id != story_program_id:
            return (
                f"Program mismatch!\n\n"
                f"Requirement '{requirement_id}' belongs to program: {program_name}\n"
                f"Story '{story_id}' belongs to a different program.\n\n"
                f"Both must belong to the same program for traceability."
            )

        # ----------------------------------------------------------------
        # STEP 6: Check if link already exists
        # ----------------------------------------------------------------
        cursor.execute(
            """
            SELECT trace_id, coverage_status FROM traceability
            WHERE requirement_id = ? AND story_id = ?
            """,
            (requirement_id, story_id)
        )
        existing_link = cursor.fetchone()

        if existing_link:
            return (
                f"Link already exists!\n\n"
                f"Requirement '{requirement_id}' is already linked to story '{story_id}'\n"
                f"Current coverage: {existing_link['coverage_status']}\n"
                f"Trace ID: {existing_link['trace_id']}\n\n"
                f"To update coverage, use a direct database update or create a new tool."
            )

        # ----------------------------------------------------------------
        # STEP 7: Insert the traceability link
        # ----------------------------------------------------------------
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute(
            """
            INSERT INTO traceability (
                program_id, requirement_id, story_id,
                coverage_status, gap_notes,
                created_date, updated_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req_program_id,
                requirement_id,
                story_id,
                coverage_status,
                gap_notes,
                now,
                now
            )
        )

        trace_id = cursor.lastrowid

        # ----------------------------------------------------------------
        # STEP 8: Log to audit_history for Part 11 compliance
        # ----------------------------------------------------------------
        cursor.execute(
            """
            INSERT INTO audit_history (
                record_type, record_id, action, field_changed,
                old_value, new_value, changed_by, changed_date, change_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                'traceability',                     # record_type
                str(trace_id),                      # record_id
                'Created',                          # action
                'link',                             # field_changed
                None,                               # old_value
                f'{requirement_id} -> {story_id}', # new_value
                'MCP:link_requirement_to_story',    # changed_by
                now,                                # changed_date
                f'Traceability link created with {coverage_status} coverage'
            )
        )

        conn.commit()

        # ----------------------------------------------------------------
        # STEP 9: Build success response
        # ----------------------------------------------------------------
        # Coverage indicator
        coverage_indicators = {
            "Full": "✓",
            "Partial": "◐",
            "None": "○"
        }
        indicator = coverage_indicators.get(coverage_status, "?")

        result = f"""Traceability link created!

{indicator} {requirement_id} → {story_id}

Link Details:
  Trace ID: {trace_id}
  Program: {program_name} [{prefix}]
  Coverage: {coverage_status}

Requirement:
  {requirement_id}: {req_title[:50]}{'...' if len(req_title) > 50 else ''}

Story:
  {story_id}: {story_title[:50]}{'...' if len(story_title) > 50 else ''}
"""
        if gap_notes:
            result += f"""
Gap Notes:
  {gap_notes}
"""

        if missing_notes_warning:
            result += f"""
⚠ Warning: Coverage is '{coverage_status}' but no gap_notes provided.
  Consider adding notes explaining what's missing or why coverage is incomplete.
"""

        result += f"""
Next Steps:
  • get_coverage_gaps(program_prefix="{prefix}") - View all coverage gaps
  • Create additional links for other requirements/stories
  • Add test cases to the story for full traceability
"""
        return result

    except Exception as e:
        return f"Error creating traceability link: {str(e)}"

    finally:
        if conn:
            conn.close()


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
def create_story(
    program_prefix: str,
    category: str,
    title: str,
    user_story: str,
    acceptance_criteria: str,
    priority: str = "Should Have",
    status: str = "Draft",
    role: Optional[str] = None,
    internal_notes: Optional[str] = None
) -> str:
    """
    Create a new user story for tracking requirements, acceptance criteria, and test coverage.

    PURPOSE:
        Creates a user story under an existing program. Stories track requirements
        in a structured format with clear acceptance criteria for testing.

    R EQUIVALENT:
        Like creating a row in a data.frame, but with auto-generated IDs
        and database persistence.

    STORY ID FORMAT:
        Auto-generated as {PREFIX}-{CATEGORY}-{NNN}
        Example: P4M-AUTH-001, P4M-AUTH-002, P4M-DASH-001

    Args:
        program_prefix: Program prefix (e.g., "P4M", "PROP")
        category: Story category (e.g., "AUTH", "DASH", "RECRUIT", "MSG")
        title: Short descriptive title for the story
        user_story: Full story in "As a [role], I want [feature], so that [benefit]" format
        acceptance_criteria: Acceptance criteria (can be multi-line, use \\n for line breaks)
        priority: MoSCoW priority - "Must Have", "Should Have", "Could Have", "Won't Have"
        status: Workflow status (default: "Draft")
        role: User role if not extractable from user_story
        internal_notes: Internal team notes (not shared with client)

    Returns:
        Confirmation with generated story_id and link to view it

    WHY THIS APPROACH:
        - Auto-increments story number within prefix+category for unique IDs
        - Validates program exists before creating
        - Parses user_story to extract role if not provided
        - Audit logging for FDA 21 CFR Part 11 compliance
    """
    # Import here to keep dependency local (matches pattern in other tools)
    import sqlite3
    import re

    conn = None
    try:
        # ----------------------------------------------------------------
        # STEP 1: Validate and normalize category
        # Category should be uppercase for consistency in story IDs
        # ----------------------------------------------------------------
        category_upper = category.upper().strip()

        # Validate category format (letters only, 2-10 chars)
        if not re.match(r'^[A-Z]{2,10}$', category_upper):
            return (
                f"Invalid category format: '{category}'\n\n"
                f"Category must be 2-10 letters (no numbers, spaces, or special characters).\n"
                f"Common categories:\n"
                f"  • AUTH - Authentication/Authorization\n"
                f"  • DASH - Dashboard\n"
                f"  • RECRUIT - Recruitment/Enrollment\n"
                f"  • MSG - Messaging/Communications\n"
                f"  • DATA - Data Management\n"
                f"  • REPORT - Reporting\n"
                f"  • ADMIN - Administration"
            )

        # ----------------------------------------------------------------
        # STEP 2: Validate priority is a valid MoSCoW value
        # ----------------------------------------------------------------
        priority_descriptions = {
            "Must Have": "Critical requirement",
            "Should Have": "Important but not critical",
            "Could Have": "Nice to have",
            "Won't Have": "Out of scope for now"
        }
        if error := validate_choice(priority, list(priority_descriptions.keys()), "priority", priority_descriptions):
            return error

        # ----------------------------------------------------------------
        # STEP 3: Connect to requirements database
        # ----------------------------------------------------------------
        conn = sqlite3.connect(REQ_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # ----------------------------------------------------------------
        # STEP 4: Validate program exists (lookup by prefix)
        # ----------------------------------------------------------------
        cursor.execute(
            "SELECT program_id, name, prefix FROM programs WHERE UPPER(prefix) = ?",
            (program_prefix.upper(),)
        )
        program_row = cursor.fetchone()

        if not program_row:
            # Program not found - show available programs to help user
            cursor.execute(
                "SELECT prefix, name FROM programs WHERE status = 'Active' ORDER BY prefix"
            )
            available = cursor.fetchall()

            if available:
                prog_list = "\n".join(f"  • [{row['prefix']}] {row['name']}" for row in available)
                return (
                    f"Program not found with prefix: '{program_prefix}'\n\n"
                    f"Available programs:\n{prog_list}\n\n"
                    f"Hint: Use the prefix (e.g., 'P4M'), not the full name."
                )
            else:
                return (
                    f"Program not found: '{program_prefix}'\n\n"
                    f"No active programs exist. Create a program first with create_program()."
                )

        program_id = program_row['program_id']
        program_name = program_row['name']
        prefix = program_row['prefix']  # Use stored prefix for consistent casing

        # ----------------------------------------------------------------
        # STEP 5: Generate story_id by finding max existing number
        # Format: {PREFIX}-{CATEGORY}-{NNN}
        # Query: Find highest NNN for this prefix+category, add 1
        # ----------------------------------------------------------------
        cursor.execute(
            """
            SELECT story_id FROM user_stories
            WHERE story_id LIKE ?
            ORDER BY story_id DESC
            LIMIT 1
            """,
            (f"{prefix}-{category_upper}-%",)
        )
        last_story = cursor.fetchone()

        if last_story:
            # Extract the number from the last story ID (e.g., "P4M-AUTH-005" -> 5)
            last_id = last_story['story_id']
            match = re.search(r'-(\d+)$', last_id)
            if match:
                next_num = int(match.group(1)) + 1
            else:
                next_num = 1
        else:
            next_num = 1

        # Format with leading zeros (3 digits)
        story_id = f"{prefix}-{category_upper}-{next_num:03d}"

        # ----------------------------------------------------------------
        # STEP 6: Try to extract role from user_story if not provided
        # Looks for "As a [role]," pattern
        # ----------------------------------------------------------------
        extracted_role = role
        if not extracted_role and user_story:
            role_match = re.search(r'[Aa]s\s+(?:a|an)\s+([^,]+),', user_story)
            if role_match:
                extracted_role = role_match.group(1).strip()

        # ----------------------------------------------------------------
        # STEP 7: Insert the user story
        # ----------------------------------------------------------------
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute(
            """
            INSERT INTO user_stories (
                story_id, program_id, title, user_story, role,
                acceptance_criteria, priority, category, status,
                internal_notes, version, created_date, updated_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                story_id,
                program_id,
                title,
                user_story,
                extracted_role,
                acceptance_criteria,
                priority,
                category_upper,
                status,
                internal_notes,
                1,  # version starts at 1
                now,
                now
            )
        )

        # ----------------------------------------------------------------
        # STEP 8: Log to audit_history for Part 11 compliance
        # ----------------------------------------------------------------
        cursor.execute(
            """
            INSERT INTO audit_history (
                record_type, record_id, action, field_changed,
                old_value, new_value, changed_by, changed_date, change_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                'user_story',                       # record_type
                story_id,                           # record_id
                'Created',                          # action
                'user_story',                       # field_changed
                None,                               # old_value (none for create)
                title,                              # new_value
                'MCP:create_story',                 # changed_by
                now,                                # changed_date
                f'New story created in {program_name} [{prefix}]'  # change_reason
            )
        )

        # Commit both inserts together
        conn.commit()

        # ----------------------------------------------------------------
        # STEP 9: Build success response
        # ----------------------------------------------------------------
        result = f"""Story created successfully!

Story Details:
  Story ID: {story_id}
  Title: {title}
  Program: {program_name} [{prefix}]
  Category: {category_upper}
  Priority: {priority}
  Status: {status}
"""
        if extracted_role:
            result += f"  Role: {extracted_role}\n"

        result += f"""
User Story:
  {user_story}

Acceptance Criteria:
"""
        # Format acceptance criteria with line numbers
        for i, line in enumerate(acceptance_criteria.split('\n'), 1):
            if line.strip():
                result += f"  {i}. {line.strip()}\n"

        result += f"""
Next Steps:
  • get_story(story_id="{story_id}") - View full story details
  • list_stories(program_prefix="{prefix}") - View all stories in program
  • Create test cases linked to this story
"""
        return result

    except sqlite3.IntegrityError as e:
        # Handle unique constraint violations
        if "UNIQUE constraint" in str(e):
            return (
                f"Story ID conflict: '{story_id}' already exists.\n\n"
                f"This shouldn't happen with auto-increment. Please report this bug."
            )
        return f"Database integrity error: {str(e)}"

    except Exception as e:
        return f"Error creating story: {str(e)}"

    finally:
        if conn:
            conn.close()


@mcp.tool()
def update_story(
    story_id: str,
    title: Optional[str] = None,
    user_story: Optional[str] = None,
    acceptance_criteria: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    client_feedback: Optional[str] = None,
    internal_notes: Optional[str] = None,
    change_reason: Optional[str] = None
) -> str:
    """
    Update an existing user story's content, status, or add feedback.

    PURPOSE:
        Modifies an existing user story. Only fields that are provided (not None)
        will be updated. Each change is logged to the audit trail for compliance.

    R EQUIVALENT:
        Like dplyr::mutate() on a single row, but with version tracking
        and audit logging.

    Args:
        story_id: Story ID to update (e.g., "P4M-AUTH-001")
        title: Updated title (optional)
        user_story: Updated story text (optional)
        acceptance_criteria: Updated acceptance criteria (optional)
        status: Workflow status - "Draft", "Internal Review", "Pending Client Review",
                "Approved", "Needs Discussion", "Out of Scope"
        priority: MoSCoW priority - "Must Have", "Should Have", "Could Have", "Won't Have"
        client_feedback: Feedback from client review (optional)
        internal_notes: Internal team notes (optional)
        change_reason: Why this change was made - recorded in audit trail (optional)

    Returns:
        Confirmation with updated fields and new version number

    WHY THIS APPROACH:
        - Only updates provided fields (sparse update pattern)
        - Auto-increments version on any change for tracking
        - Special handling for "Approved" status (sets approved_date/approved_by)
        - Per-field audit logging for regulatory compliance
    """
    import sqlite3

    conn = None
    try:
        # ----------------------------------------------------------------
        # STEP 1: Validate status if provided
        # ----------------------------------------------------------------
        valid_statuses = [
            "Draft",
            "Internal Review",
            "Pending Client Review",
            "Approved",
            "Needs Discussion",
            "Out of Scope"
        ]
        if status is not None and status not in valid_statuses:
            status_list = "\n".join(f"  • {s}" for s in valid_statuses)
            return (
                f"Invalid status: '{status}'\n\n"
                f"Valid statuses:\n{status_list}"
            )

        # ----------------------------------------------------------------
        # STEP 2: Validate priority if provided
        # ----------------------------------------------------------------
        valid_priorities = ["Must Have", "Should Have", "Could Have", "Won't Have"]
        if priority is not None and priority not in valid_priorities:
            return (
                f"Invalid priority: '{priority}'\n\n"
                f"Priority must be one of (MoSCoW):\n"
                f"  • Must Have - Critical requirement\n"
                f"  • Should Have - Important but not critical\n"
                f"  • Could Have - Nice to have\n"
                f"  • Won't Have - Out of scope for now"
            )

        # ----------------------------------------------------------------
        # STEP 3: Connect to database and fetch existing story
        # ----------------------------------------------------------------
        conn = sqlite3.connect(REQ_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT s.*, p.name as program_name, p.prefix
            FROM user_stories s
            JOIN programs p ON s.program_id = p.program_id
            WHERE s.story_id = ?
            """,
            (story_id,)
        )
        existing = cursor.fetchone()

        if not existing:
            # Story not found - provide helpful error
            # Try to extract prefix to suggest similar stories
            parts = story_id.split('-')
            if len(parts) >= 2:
                prefix = parts[0]
                cursor.execute(
                    "SELECT story_id, title FROM user_stories WHERE story_id LIKE ? LIMIT 5",
                    (f"{prefix}-%",)
                )
                similar = cursor.fetchall()
                if similar:
                    similar_list = "\n".join(f"  • {s['story_id']}: {s['title'][:40]}" for s in similar)
                    return (
                        f"Story not found: '{story_id}'\n\n"
                        f"Similar stories in {prefix}:\n{similar_list}"
                    )

            return f"Story not found: '{story_id}'"

        # Convert to dict for easier access
        old_story = dict(existing)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # ----------------------------------------------------------------
        # STEP 4: Build update fields and track changes
        # Only include fields that were provided (not None)
        # ----------------------------------------------------------------
        updates = {}
        changes = []  # List of (field_name, old_value, new_value) for audit

        # Check each optional field
        if title is not None and title != old_story.get('title'):
            updates['title'] = title
            changes.append(('title', old_story.get('title'), title))

        if user_story is not None and user_story != old_story.get('user_story'):
            updates['user_story'] = user_story
            changes.append(('user_story', old_story.get('user_story'), user_story))

        if acceptance_criteria is not None and acceptance_criteria != old_story.get('acceptance_criteria'):
            updates['acceptance_criteria'] = acceptance_criteria
            changes.append(('acceptance_criteria', old_story.get('acceptance_criteria'), acceptance_criteria))

        if status is not None and status != old_story.get('status'):
            updates['status'] = status
            changes.append(('status', old_story.get('status'), status))

            # Special handling for Approved status
            if status == "Approved":
                updates['approved_date'] = now
                updates['approved_by'] = 'MCP:update_story'
                changes.append(('approved_date', old_story.get('approved_date'), now))

        if priority is not None and priority != old_story.get('priority'):
            updates['priority'] = priority
            changes.append(('priority', old_story.get('priority'), priority))

        if client_feedback is not None:
            # For feedback, we append rather than replace (if existing)
            old_feedback = old_story.get('client_feedback') or ''
            if old_feedback:
                new_feedback = f"{old_feedback}\n\n[{now}]\n{client_feedback}"
            else:
                new_feedback = f"[{now}]\n{client_feedback}"
            updates['client_feedback'] = new_feedback
            changes.append(('client_feedback', old_feedback, new_feedback))

        if internal_notes is not None:
            # For notes, we append rather than replace (if existing)
            old_notes = old_story.get('internal_notes') or ''
            if old_notes:
                new_notes = f"{old_notes}\n\n[{now}]\n{internal_notes}"
            else:
                new_notes = f"[{now}]\n{internal_notes}"
            updates['internal_notes'] = new_notes
            changes.append(('internal_notes', old_notes, new_notes))

        # ----------------------------------------------------------------
        # STEP 5: Check if there are any changes to make
        # ----------------------------------------------------------------
        if not updates:
            return (
                f"No changes to make for {story_id}\n\n"
                f"All provided values match the current values, or no update fields were provided.\n"
                f"Current story:\n"
                f"  Title: {old_story.get('title')}\n"
                f"  Status: {old_story.get('status')}\n"
                f"  Priority: {old_story.get('priority')}\n"
                f"  Version: {old_story.get('version', 1)}"
            )

        # ----------------------------------------------------------------
        # STEP 6: Always update version and updated_date when changes occur
        # ----------------------------------------------------------------
        new_version = (old_story.get('version') or 1) + 1
        updates['version'] = new_version
        updates['updated_date'] = now

        # ----------------------------------------------------------------
        # STEP 7: Build and execute UPDATE statement
        # ----------------------------------------------------------------
        set_clause = ", ".join(f"{field} = ?" for field in updates.keys())
        values = list(updates.values()) + [story_id]

        cursor.execute(
            f"UPDATE user_stories SET {set_clause} WHERE story_id = ?",
            values
        )

        # ----------------------------------------------------------------
        # STEP 8: Log each change to audit_history
        # ----------------------------------------------------------------
        audit_reason = change_reason or "Story updated via MCP"

        for field_name, old_value, new_value in changes:
            # Truncate long values for audit log readability
            old_display = str(old_value)[:200] if old_value else None
            new_display = str(new_value)[:200] if new_value else None

            cursor.execute(
                """
                INSERT INTO audit_history (
                    record_type, record_id, action, field_changed,
                    old_value, new_value, changed_by, changed_date, change_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    'user_story',
                    story_id,
                    'Updated',
                    field_name,
                    old_display,
                    new_display,
                    'MCP:update_story',
                    now,
                    audit_reason
                )
            )

        conn.commit()

        # ----------------------------------------------------------------
        # STEP 9: Build success response
        # ----------------------------------------------------------------
        result = f"""Story updated successfully!

Story: {story_id}
Program: {old_story['program_name']} [{old_story['prefix']}]
Version: {old_story.get('version', 1)} → {new_version}

Changes made ({len(changes)} field(s)):
"""
        for field_name, old_val, new_val in changes:
            # Format display based on field type
            if field_name in ('client_feedback', 'internal_notes', 'user_story', 'acceptance_criteria'):
                # For long text fields, just show that it was updated
                result += f"  • {field_name}: (updated)\n"
            else:
                result += f"  • {field_name}: '{old_val}' → '{new_val}'\n"

        if status == "Approved":
            result += f"\n✓ Story marked as APPROVED at {now}\n"

        result += f"""
Next Steps:
  • get_story(story_id="{story_id}") - View updated story
  • get_approval_pipeline(program_prefix="{old_story['prefix']}") - View workflow status
"""
        return result

    except Exception as e:
        return f"Error updating story: {str(e)}"

    finally:
        if conn:
            conn.close()


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


@mcp.tool()
def create_test_case(
    story_id: str,
    title: str,
    test_type: str,
    test_steps: str,
    expected_result: str,
    preconditions: Optional[str] = None,
    priority: str = "Should Have",
    compliance_framework: Optional[str] = None
) -> str:
    """
    Create a UAT test case linked to a user story.

    PURPOSE:
        Creates a test case that validates a user story's acceptance criteria.
        Test cases track execution status and can be linked to compliance frameworks.

    R EQUIVALENT:
        Like adding a row to a test plan data.frame, with automatic ID generation
        and linkage to the parent story.

    TEST ID FORMAT:
        Auto-generated as {STORY_ID}-TC{NN}
        Example: P4M-AUTH-001-TC01, P4M-AUTH-001-TC02

    Args:
        story_id: Parent story ID (e.g., "P4M-AUTH-001")
        title: Test case title (short description)
        test_type: Type of test - "happy_path", "negative", "validation", "edge_case"
        test_steps: Numbered test steps (can be multi-line)
        expected_result: Expected outcome when test passes
        preconditions: Setup required before running test (optional)
        priority: MoSCoW priority (default: "Should Have")
        compliance_framework: "Part11", "HIPAA", "SOC2", or None

    Returns:
        Confirmation with generated test_id

    WHY THIS APPROACH:
        - Links test to parent story for traceability
        - Auto-increments test number within the story
        - Supports compliance framework tagging
        - Audit logging for Part 11 compliance
    """
    import sqlite3
    import re

    conn = None
    try:
        # ----------------------------------------------------------------
        # STEP 1: Validate test_type
        # ----------------------------------------------------------------
        valid_test_types = ["happy_path", "negative", "validation", "edge_case"]
        test_type_lower = test_type.lower().strip()

        if test_type_lower not in valid_test_types:
            type_list = "\n".join(f"  • {t}" for t in valid_test_types)
            return (
                f"Invalid test_type: '{test_type}'\n\n"
                f"Valid test types:\n{type_list}\n\n"
                f"Descriptions:\n"
                f"  • happy_path - Normal successful scenario\n"
                f"  • negative - Error handling, invalid inputs\n"
                f"  • validation - Input/data validation rules\n"
                f"  • edge_case - Boundary conditions, unusual scenarios"
            )

        # ----------------------------------------------------------------
        # STEP 2: Validate priority
        # ----------------------------------------------------------------
        valid_priorities = ["Must Have", "Should Have", "Could Have", "Won't Have"]
        if priority not in valid_priorities:
            return (
                f"Invalid priority: '{priority}'\n\n"
                f"Priority must be one of (MoSCoW):\n"
                f"  • Must Have - Critical test\n"
                f"  • Should Have - Important but not critical\n"
                f"  • Could Have - Nice to have\n"
                f"  • Won't Have - Out of scope for now"
            )

        # ----------------------------------------------------------------
        # STEP 3: Validate compliance_framework if provided
        # ----------------------------------------------------------------
        valid_frameworks = ["Part11", "HIPAA", "SOC2"]
        if compliance_framework is not None:
            # Normalize common variations
            framework_normalized = compliance_framework.strip()
            framework_upper = framework_normalized.upper().replace(" ", "").replace("-", "")

            # Map common variations to standard names
            framework_map = {
                "PART11": "Part11",
                "21CFRPART11": "Part11",
                "CFR11": "Part11",
                "HIPAA": "HIPAA",
                "SOC2": "SOC2",
                "SOCII": "SOC2",
                "SOC": "SOC2"
            }

            if framework_upper in framework_map:
                compliance_framework = framework_map[framework_upper]
            elif framework_normalized not in valid_frameworks:
                return (
                    f"Invalid compliance_framework: '{compliance_framework}'\n\n"
                    f"Valid frameworks:\n"
                    f"  • Part11 - FDA 21 CFR Part 11\n"
                    f"  • HIPAA - Health Insurance Portability and Accountability\n"
                    f"  • SOC2 - Service Organization Control 2\n"
                    f"  • None - No compliance requirement"
                )

        # ----------------------------------------------------------------
        # STEP 4: Connect to database and validate parent story exists
        # ----------------------------------------------------------------
        conn = sqlite3.connect(REQ_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT s.story_id, s.title as story_title, s.program_id,
                   p.name as program_name, p.prefix
            FROM user_stories s
            JOIN programs p ON s.program_id = p.program_id
            WHERE s.story_id = ?
            """,
            (story_id,)
        )
        parent_story = cursor.fetchone()

        if not parent_story:
            # Story not found - provide helpful suggestions
            parts = story_id.split('-')
            if len(parts) >= 2:
                prefix = parts[0]
                cursor.execute(
                    "SELECT story_id, title FROM user_stories WHERE story_id LIKE ? ORDER BY story_id LIMIT 5",
                    (f"{prefix}-%",)
                )
                similar = cursor.fetchall()
                if similar:
                    similar_list = "\n".join(f"  • {s['story_id']}: {s['title'][:40]}" for s in similar)
                    return (
                        f"Parent story not found: '{story_id}'\n\n"
                        f"Similar stories in {prefix}:\n{similar_list}\n\n"
                        f"Hint: Use get_story() to verify the story exists."
                    )

            return f"Parent story not found: '{story_id}'"

        program_id = parent_story['program_id']
        program_name = parent_story['program_name']
        prefix = parent_story['prefix']

        # ----------------------------------------------------------------
        # STEP 5: Generate test_id by finding max existing number
        # Format: {STORY_ID}-TC{NN}
        # Query: Find highest NN for this story, add 1
        # ----------------------------------------------------------------
        cursor.execute(
            """
            SELECT test_id FROM uat_test_cases
            WHERE test_id LIKE ?
            ORDER BY test_id DESC
            LIMIT 1
            """,
            (f"{story_id}-TC%",)
        )
        last_test = cursor.fetchone()

        if last_test:
            # Extract the number from the last test ID (e.g., "P4M-AUTH-001-TC05" -> 5)
            last_id = last_test['test_id']
            match = re.search(r'-TC(\d+)$', last_id)
            if match:
                next_num = int(match.group(1)) + 1
            else:
                next_num = 1
        else:
            next_num = 1

        # Format with leading zeros (2 digits)
        test_id = f"{story_id}-TC{next_num:02d}"

        # ----------------------------------------------------------------
        # STEP 6: Insert the test case
        # ----------------------------------------------------------------
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute(
            """
            INSERT INTO uat_test_cases (
                test_id, story_id, program_id, title, test_type,
                prerequisites, test_steps, expected_results,
                priority, compliance_framework, test_status,
                created_date, updated_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                test_id,
                story_id,
                program_id,
                title,
                test_type_lower,
                preconditions,
                test_steps,
                expected_result,
                priority,
                compliance_framework,
                "Not Run",  # Initial status
                now,
                now
            )
        )

        # ----------------------------------------------------------------
        # STEP 7: Log to audit_history for Part 11 compliance
        # ----------------------------------------------------------------
        cursor.execute(
            """
            INSERT INTO audit_history (
                record_type, record_id, action, field_changed,
                old_value, new_value, changed_by, changed_date, change_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                'test_case',                        # record_type
                test_id,                            # record_id
                'Created',                          # action
                'test_case',                        # field_changed
                None,                               # old_value (none for create)
                title,                              # new_value
                'MCP:create_test_case',             # changed_by
                now,                                # changed_date
                f'New test case for story {story_id}'  # change_reason
            )
        )

        conn.commit()

        # ----------------------------------------------------------------
        # STEP 8: Build success response
        # ----------------------------------------------------------------
        result = f"""Test case created successfully!

Test Case Details:
  Test ID: {test_id}
  Title: {title}
  Parent Story: {story_id} - {parent_story['story_title'][:40]}
  Program: {program_name} [{prefix}]
  Test Type: {test_type_lower}
  Priority: {priority}
  Status: Not Run
"""
        if compliance_framework:
            result += f"  Compliance: {compliance_framework}\n"

        if preconditions:
            result += f"""
Preconditions:
  {preconditions}
"""

        result += f"""
Test Steps:
"""
        for line in test_steps.split('\n'):
            if line.strip():
                result += f"  {line.strip()}\n"

        result += f"""
Expected Result:
  {expected_result}

Next Steps:
  • list_test_cases(program_prefix="{prefix}") - View all test cases
  • get_test_summary(program_prefix="{prefix}") - View test execution stats
  • Create more test cases for this story with different test_types
"""
        return result

    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint" in str(e):
            return (
                f"Test ID conflict: '{test_id}' already exists.\n\n"
                f"This shouldn't happen with auto-increment. Please report this bug."
            )
        return f"Database integrity error: {str(e)}"

    except Exception as e:
        return f"Error creating test case: {str(e)}"

    finally:
        if conn:
            conn.close()


@mcp.tool()
def update_test_result(
    test_id: str,
    status: str,
    tested_by: str,
    notes: Optional[str] = None,
    defect_id: Optional[str] = None
) -> str:
    """
    Record the result of executing a test case.

    PURPOSE:
        Records test execution results including pass/fail status, who ran
        the test, and any defects found. Essential for test coverage tracking
        and compliance reporting.

    R EQUIVALENT:
        Like updating a row in a test results data.frame with execution data
        and timestamp.

    Args:
        test_id: Test case ID (e.g., "P4M-AUTH-001-TC01")
        status: Execution result - "Pass", "Fail", "Blocked", "Skipped"
        tested_by: Name or ID of person who executed the test
        notes: Execution notes or observations (optional)
        defect_id: Link to defect/bug ticket if test failed (optional)

    Returns:
        Confirmation with updated test status and summary

    WHY THIS APPROACH:
        - Captures who ran the test and when for audit trail
        - Links failed tests to defect tracking
        - Per-field audit logging for Part 11 compliance
    """
    import sqlite3

    conn = None
    try:
        # ----------------------------------------------------------------
        # STEP 1: Validate status
        # ----------------------------------------------------------------
        valid_statuses = ["Pass", "Fail", "Blocked", "Skipped"]
        if status not in valid_statuses:
            status_list = "\n".join(f"  • {s}" for s in valid_statuses)
            return (
                f"Invalid status: '{status}'\n\n"
                f"Valid statuses:\n{status_list}\n\n"
                f"Descriptions:\n"
                f"  • Pass - Test completed successfully\n"
                f"  • Fail - Test found a defect\n"
                f"  • Blocked - Cannot run due to environment/dependency issue\n"
                f"  • Skipped - Intentionally not run (with justification)"
            )

        # Warn if Fail status without defect_id
        if status == "Fail" and not defect_id:
            # Don't block, just note it in the response later
            missing_defect_warning = True
        else:
            missing_defect_warning = False

        # ----------------------------------------------------------------
        # STEP 2: Connect to database and fetch existing test case
        # ----------------------------------------------------------------
        conn = sqlite3.connect(REQ_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT t.*, s.title as story_title, p.name as program_name, p.prefix
            FROM uat_test_cases t
            JOIN user_stories s ON t.story_id = s.story_id
            JOIN programs p ON t.program_id = p.program_id
            WHERE t.test_id = ?
            """,
            (test_id,)
        )
        existing = cursor.fetchone()

        if not existing:
            # Test not found - provide helpful suggestions
            parts = test_id.split('-')
            if len(parts) >= 3:
                # Try to find the parent story's tests
                story_prefix = '-'.join(parts[:-1])  # e.g., "P4M-AUTH-001" from "P4M-AUTH-001-TC01"
                cursor.execute(
                    "SELECT test_id, title FROM uat_test_cases WHERE test_id LIKE ? ORDER BY test_id LIMIT 5",
                    (f"{story_prefix}-%",)
                )
                similar = cursor.fetchall()
                if similar:
                    similar_list = "\n".join(f"  • {t['test_id']}: {t['title'][:40]}" for t in similar)
                    return (
                        f"Test case not found: '{test_id}'\n\n"
                        f"Test cases for {story_prefix}:\n{similar_list}"
                    )

            return f"Test case not found: '{test_id}'"

        # Convert to dict for easier access
        old_test = dict(existing)
        old_status = old_test.get('test_status', 'Not Run')
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # ----------------------------------------------------------------
        # STEP 3: Build update fields
        # ----------------------------------------------------------------
        updates = {
            'test_status': status,
            'tested_by': tested_by,
            'tested_date': now,
            'updated_date': now
        }

        # Track changes for audit
        changes = [('test_status', old_status, status)]

        if notes is not None:
            updates['execution_notes'] = notes
            changes.append(('execution_notes', old_test.get('execution_notes'), notes))

        if defect_id is not None:
            updates['defect_id'] = defect_id
            changes.append(('defect_id', old_test.get('defect_id'), defect_id))

        # ----------------------------------------------------------------
        # STEP 4: Execute UPDATE
        # ----------------------------------------------------------------
        set_clause = ", ".join(f"{field} = ?" for field in updates.keys())
        values = list(updates.values()) + [test_id]

        cursor.execute(
            f"UPDATE uat_test_cases SET {set_clause} WHERE test_id = ?",
            values
        )

        # ----------------------------------------------------------------
        # STEP 5: Log to audit_history
        # ----------------------------------------------------------------
        for field_name, old_value, new_value in changes:
            cursor.execute(
                """
                INSERT INTO audit_history (
                    record_type, record_id, action, field_changed,
                    old_value, new_value, changed_by, changed_date, change_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    'test_case',
                    test_id,
                    'Executed',
                    field_name,
                    str(old_value) if old_value else None,
                    str(new_value) if new_value else None,
                    f'MCP:update_test_result ({tested_by})',
                    now,
                    f'Test executed with result: {status}'
                )
            )

        conn.commit()

        # ----------------------------------------------------------------
        # STEP 6: Build success response
        # ----------------------------------------------------------------
        # Determine status emoji/indicator
        status_indicators = {
            "Pass": "✓",
            "Fail": "✗",
            "Blocked": "⊘",
            "Skipped": "—"
        }
        indicator = status_indicators.get(status, "?")

        result = f"""Test result recorded!

{indicator} {test_id}: {status}

Test Details:
  Title: {old_test['title']}
  Parent Story: {old_test['story_id']} - {old_test['story_title'][:40]}
  Program: {old_test['program_name']} [{old_test['prefix']}]
  Test Type: {old_test.get('test_type', 'N/A')}

Execution:
  Previous Status: {old_status}
  New Status: {status}
  Tested By: {tested_by}
  Tested Date: {now}
"""
        if notes:
            result += f"  Notes: {notes[:100]}{'...' if len(notes) > 100 else ''}\n"

        if defect_id:
            result += f"  Defect ID: {defect_id}\n"

        if missing_defect_warning:
            result += f"""
⚠ Warning: Test failed but no defect_id provided.
  Consider linking to a defect ticket for tracking.
"""

        result += f"""
Next Steps:
  • get_test_summary(program_prefix="{old_test['prefix']}") - View overall test stats
  • list_test_cases(program_prefix="{old_test['prefix']}", status="{status}") - View all {status} tests
"""
        return result

    except Exception as e:
        return f"Error updating test result: {str(e)}"

    finally:
        if conn:
            conn.close()


@mcp.tool()
def delete_test_case(
    test_id: str,
    reason: str
) -> str:
    """
    Delete a test case from the database with full audit trail.

    PURPOSE:
        Permanently removes a test case that is no longer needed (out of scope,
        duplicate, or superseded). The full test case data is captured in the
        audit trail before deletion for compliance.

    R EQUIVALENT:
        Like dplyr::filter(!test_id == id) but with audit logging and
        validation. The deleted record is preserved in audit_history.

    Args:
        test_id: Test case ID to delete (e.g., "P4M-CONFIG-001-TC02")
        reason: Reason for deletion - recorded in audit trail for compliance

    Returns:
        Confirmation with deleted test_id, parent story, and timestamp

    WHY THIS APPROACH:
        - Hard delete (not soft delete) since test cases can be recreated if needed
        - Full record snapshot captured in audit_history before deletion
        - Reason field ensures audit trail explains why the deletion occurred
        - Part 11 compliant audit trail

    Example:
        delete_test_case(
            test_id="P4M-CONFIG-001-TC02",
            reason="Out of scope - patient assessment moved to future story"
        )
    """
    import sqlite3
    import json

    conn = None
    try:
        # ----------------------------------------------------------------
        # STEP 1: Connect to database and fetch existing test case
        # ----------------------------------------------------------------
        conn = sqlite3.connect(REQ_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT t.*, s.title as story_title, p.name as program_name, p.prefix
            FROM uat_test_cases t
            JOIN user_stories s ON t.story_id = s.story_id
            JOIN programs p ON t.program_id = p.program_id
            WHERE t.test_id = ?
            """,
            (test_id,)
        )
        existing = cursor.fetchone()

        if not existing:
            # Test not found - provide helpful suggestions
            parts = test_id.split('-')
            if len(parts) >= 3:
                # Try to find similar test cases
                story_prefix = '-'.join(parts[:-1])  # e.g., "P4M-CONFIG-001" from "P4M-CONFIG-001-TC02"
                cursor.execute(
                    "SELECT test_id, title FROM uat_test_cases WHERE test_id LIKE ? ORDER BY test_id LIMIT 5",
                    (f"{story_prefix}-%",)
                )
                similar = cursor.fetchall()
                if similar:
                    similar_list = "\n".join(f"  • {t['test_id']}: {t['title'][:40]}" for t in similar)
                    return (
                        f"Test case not found: '{test_id}'\n\n"
                        f"Test cases for {story_prefix}:\n{similar_list}"
                    )

            return f"Test case not found: '{test_id}'"

        # Convert to dict for easier access and JSON serialization
        test_data = dict(existing)
        story_id = test_data['story_id']
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # ----------------------------------------------------------------
        # STEP 2: Prepare audit record with full test case data
        # Remove non-serializable or redundant joined fields
        # ----------------------------------------------------------------
        audit_record = {
            'test_id': test_data.get('test_id'),
            'story_id': test_data.get('story_id'),
            'program_id': test_data.get('program_id'),
            'title': test_data.get('title'),
            'test_type': test_data.get('test_type'),
            'prerequisites': test_data.get('prerequisites'),
            'test_steps': test_data.get('test_steps'),
            'expected_results': test_data.get('expected_results'),
            'priority': test_data.get('priority'),
            'compliance_framework': test_data.get('compliance_framework'),
            'test_status': test_data.get('test_status'),
            'tested_by': test_data.get('tested_by'),
            'tested_date': test_data.get('tested_date'),
            'execution_notes': test_data.get('execution_notes'),
            'defect_id': test_data.get('defect_id'),
            'created_date': test_data.get('created_date'),
            'updated_date': test_data.get('updated_date')
        }

        # ----------------------------------------------------------------
        # STEP 3: Log deletion to audit_history BEFORE deleting
        # ----------------------------------------------------------------
        cursor.execute(
            """
            INSERT INTO audit_history (
                record_type, record_id, action, field_changed,
                old_value, new_value, changed_by, changed_date, change_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                'test_case',                    # record_type
                test_id,                        # record_id
                'Deleted',                      # action
                'record',                       # field_changed
                json.dumps(audit_record),       # old_value (full record)
                None,                           # new_value (null for delete)
                'MCP:delete_test_case',         # changed_by
                now,                            # changed_date
                reason                          # change_reason
            )
        )

        # ----------------------------------------------------------------
        # STEP 4: Delete the test case
        # ----------------------------------------------------------------
        cursor.execute(
            "DELETE FROM uat_test_cases WHERE test_id = ?",
            (test_id,)
        )

        conn.commit()

        # ----------------------------------------------------------------
        # STEP 5: Build success response
        # ----------------------------------------------------------------
        result = f"""Test case deleted successfully!

Deleted Test Case:
  Test ID: {test_id}
  Title: {test_data['title']}
  Parent Story: {story_id} - {test_data['story_title'][:40]}
  Program: {test_data['program_name']} [{test_data['prefix']}]
  Previous Status: {test_data.get('test_status', 'Not Run')}

Deletion Details:
  Reason: {reason}
  Deleted At: {now}
  Deleted By: MCP:delete_test_case

Audit Trail:
  Full test case record has been preserved in audit_history.
  The deletion is traceable for compliance purposes.

Next Steps:
  • list_test_cases(story_id="{story_id}") - View remaining test cases
  • create_test_case(...) - Create a replacement test case if needed
"""
        return result

    except Exception as e:
        return f"Error deleting test case: {str(e)}"

    finally:
        if conn:
            conn.close()


@mcp.tool()
def update_test_case(
    test_id: str,
    title: Optional[str] = None,
    test_type: Optional[str] = None,
    test_steps: Optional[str] = None,
    expected_result: Optional[str] = None,
    preconditions: Optional[str] = None,
    priority: Optional[str] = None,
    compliance_framework: Optional[str] = None,
    story_id: Optional[str] = None,
    change_reason: Optional[str] = None
) -> str:
    """
    Update test case content (NOT execution results — use update_test_result for that).

    PURPOSE:
        Modifies test case definition: title, steps, expected results, etc.
        Only provided fields are updated (sparse update pattern).
        Each change is logged to the audit trail for compliance.

    R EQUIVALENT:
        Like dplyr::mutate() on a single row with coalesce() for optional fields.
        Only non-NULL parameters trigger updates.

    Args:
        test_id: Test case ID to update (e.g., "P4M-CONFIG-001-TC05")
        title: Updated test case title (optional)
        test_type: Type of test - "happy_path", "negative", "validation", "edge_case" (optional)
        test_steps: Updated test steps (optional)
        expected_result: Updated expected result (optional)
        preconditions: Updated preconditions/prerequisites (optional)
        priority: MoSCoW priority - "Must Have", "Should Have", "Could Have", "Won't Have" (optional)
        compliance_framework: "Part11", "HIPAA", "SOC2", or None (optional)
        story_id: Reassign to different parent story (must be same program) (optional)
        change_reason: Why this change was made - recorded in audit trail (optional)

    Returns:
        Confirmation with list of updated fields showing old → new values

    WHY THIS APPROACH:
        - Sparse update: Only updates fields that are explicitly provided
        - Distinguishes from update_test_result which records EXECUTION outcomes
        - This tool is for changing WHAT the test does, not HOW it performed
        - Cross-program reassignment is blocked to maintain data integrity
        - Per-field audit logging for Part 11 compliance

    Example:
        update_test_case(
            test_id="P4M-CONFIG-001-TC05",
            title="TC Enabled Clinic Clinical Summary Functions Correctly",
            expected_result="Clinical summary generates with TC score, lifetime risk %, TC recommendations",
            change_reason="Narrowed scope to clinical summary only per story update"
        )
    """
    import sqlite3

    conn = None
    try:
        # ----------------------------------------------------------------
        # STEP 1: Validate test_type if provided
        # ----------------------------------------------------------------
        valid_test_types = ["happy_path", "negative", "validation", "edge_case"]
        if test_type is not None:
            test_type_lower = test_type.lower().strip()
            if test_type_lower not in valid_test_types:
                type_list = "\n".join(f"  • {t}" for t in valid_test_types)
                return (
                    f"Invalid test_type: '{test_type}'\n\n"
                    f"Valid test types:\n{type_list}\n\n"
                    f"Descriptions:\n"
                    f"  • happy_path - Normal successful scenario\n"
                    f"  • negative - Error handling, invalid inputs\n"
                    f"  • validation - Input/data validation rules\n"
                    f"  • edge_case - Boundary conditions, unusual scenarios"
                )
            test_type = test_type_lower  # Normalize to lowercase

        # ----------------------------------------------------------------
        # STEP 2: Validate priority if provided
        # ----------------------------------------------------------------
        valid_priorities = ["Must Have", "Should Have", "Could Have", "Won't Have"]
        if priority is not None and priority not in valid_priorities:
            return (
                f"Invalid priority: '{priority}'\n\n"
                f"Priority must be one of (MoSCoW):\n"
                f"  • Must Have - Critical test\n"
                f"  • Should Have - Important but not critical\n"
                f"  • Could Have - Nice to have\n"
                f"  • Won't Have - Out of scope for now"
            )

        # ----------------------------------------------------------------
        # STEP 3: Validate compliance_framework if provided
        # ----------------------------------------------------------------
        valid_frameworks = ["Part11", "HIPAA", "SOC2"]
        if compliance_framework is not None:
            # Normalize common variations
            framework_normalized = compliance_framework.strip()
            framework_upper = framework_normalized.upper().replace(" ", "").replace("-", "")

            # Map common variations to standard names
            framework_map = {
                "PART11": "Part11",
                "21CFRPART11": "Part11",
                "CFR11": "Part11",
                "HIPAA": "HIPAA",
                "SOC2": "SOC2",
                "SOCII": "SOC2",
                "SOC": "SOC2",
                "NONE": None  # Allow clearing the framework
            }

            if framework_upper in framework_map:
                compliance_framework = framework_map[framework_upper]
            elif framework_normalized not in valid_frameworks:
                return (
                    f"Invalid compliance_framework: '{compliance_framework}'\n\n"
                    f"Valid frameworks:\n"
                    f"  • Part11 - FDA 21 CFR Part 11\n"
                    f"  • HIPAA - Health Insurance Portability and Accountability\n"
                    f"  • SOC2 - Service Organization Control 2\n"
                    f"  • None - No compliance requirement (or use 'NONE' to clear)"
                )

        # ----------------------------------------------------------------
        # STEP 4: Connect to database and fetch existing test case
        # ----------------------------------------------------------------
        conn = sqlite3.connect(REQ_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT t.*, s.title as story_title, p.name as program_name, p.prefix, p.program_id as parent_program_id
            FROM uat_test_cases t
            JOIN user_stories s ON t.story_id = s.story_id
            JOIN programs p ON t.program_id = p.program_id
            WHERE t.test_id = ?
            """,
            (test_id,)
        )
        existing = cursor.fetchone()

        if not existing:
            # Test not found - provide helpful suggestions
            parts = test_id.split('-')
            if len(parts) >= 3:
                story_prefix = '-'.join(parts[:-1])
                cursor.execute(
                    "SELECT test_id, title FROM uat_test_cases WHERE test_id LIKE ? ORDER BY test_id LIMIT 5",
                    (f"{story_prefix}-%",)
                )
                similar = cursor.fetchall()
                if similar:
                    similar_list = "\n".join(f"  • {t['test_id']}: {t['title'][:40]}" for t in similar)
                    return (
                        f"Test case not found: '{test_id}'\n\n"
                        f"Test cases for {story_prefix}:\n{similar_list}"
                    )

            return f"Test case not found: '{test_id}'"

        # Convert to dict for easier access
        old_test = dict(existing)
        current_program_id = old_test['program_id']
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # ----------------------------------------------------------------
        # STEP 5: Validate story_id reassignment if provided
        # ----------------------------------------------------------------
        new_program_id = None
        if story_id is not None:
            # Validate new story exists
            cursor.execute(
                """
                SELECT s.story_id, s.title, s.program_id, p.prefix
                FROM user_stories s
                JOIN programs p ON s.program_id = p.program_id
                WHERE s.story_id = ?
                """,
                (story_id,)
            )
            new_story = cursor.fetchone()

            if not new_story:
                return (
                    f"New parent story not found: '{story_id}'\n\n"
                    f"Please verify the story_id exists before reassigning."
                )

            new_program_id = new_story['program_id']

            # Cross-program check: parse program prefix from test_id
            # Test ID format: {STORY_ID}-TC{NN} where STORY_ID = {PREFIX}-{CATEGORY}-{NUM}
            # e.g., "P4M-CONFIG-001-TC02" -> program prefix is "P4M"
            test_parts = test_id.split('-')
            if len(test_parts) >= 1:
                test_program_prefix = test_parts[0]
                new_story_prefix = new_story['prefix']

                if test_program_prefix.upper() != new_story_prefix.upper():
                    return (
                        f"Cross-program reassignment not allowed!\n\n"
                        f"Test case {test_id} belongs to program '{test_program_prefix}'\n"
                        f"but the new story {story_id} belongs to program '{new_story_prefix}'.\n\n"
                        f"Test cases cannot be moved between programs.\n"
                        f"If needed, delete this test case and create a new one in the target program."
                    )

        # ----------------------------------------------------------------
        # STEP 6: Build update fields and track changes
        # Only include fields that were provided (not None)
        # ----------------------------------------------------------------
        updates = {}
        changes = []  # List of (field_name, old_value, new_value) for audit

        # Check each optional field
        if title is not None and title != old_test.get('title'):
            updates['title'] = title
            changes.append(('title', old_test.get('title'), title))

        if test_type is not None and test_type != old_test.get('test_type'):
            updates['test_type'] = test_type
            changes.append(('test_type', old_test.get('test_type'), test_type))

        if test_steps is not None and test_steps != old_test.get('test_steps'):
            updates['test_steps'] = test_steps
            changes.append(('test_steps', old_test.get('test_steps'), test_steps))

        if expected_result is not None and expected_result != old_test.get('expected_results'):
            updates['expected_results'] = expected_result
            changes.append(('expected_results', old_test.get('expected_results'), expected_result))

        if preconditions is not None and preconditions != old_test.get('prerequisites'):
            updates['prerequisites'] = preconditions
            changes.append(('prerequisites', old_test.get('prerequisites'), preconditions))

        if priority is not None and priority != old_test.get('priority'):
            updates['priority'] = priority
            changes.append(('priority', old_test.get('priority'), priority))

        if compliance_framework is not None:
            # Handle clearing framework (set to None) vs updating
            old_framework = old_test.get('compliance_framework')
            if compliance_framework != old_framework:
                updates['compliance_framework'] = compliance_framework
                changes.append(('compliance_framework', old_framework, compliance_framework))

        if story_id is not None and story_id != old_test.get('story_id'):
            updates['story_id'] = story_id
            if new_program_id:
                updates['program_id'] = new_program_id
            changes.append(('story_id', old_test.get('story_id'), story_id))

        # ----------------------------------------------------------------
        # STEP 7: Check if there are any changes to make
        # ----------------------------------------------------------------
        if not updates:
            return (
                f"No changes to make for {test_id}\n\n"
                f"All provided values match the current values, or no update fields were provided.\n"
                f"Current test case:\n"
                f"  Title: {old_test.get('title')}\n"
                f"  Test Type: {old_test.get('test_type')}\n"
                f"  Priority: {old_test.get('priority')}\n"
                f"  Parent Story: {old_test.get('story_id')}"
            )

        # ----------------------------------------------------------------
        # STEP 8: Always update updated_date when changes occur
        # ----------------------------------------------------------------
        updates['updated_date'] = now

        # ----------------------------------------------------------------
        # STEP 9: Build and execute UPDATE statement
        # ----------------------------------------------------------------
        set_clause = ", ".join(f"{field} = ?" for field in updates.keys())
        values = list(updates.values()) + [test_id]

        cursor.execute(
            f"UPDATE uat_test_cases SET {set_clause} WHERE test_id = ?",
            values
        )

        # ----------------------------------------------------------------
        # STEP 10: Log each change to audit_history
        # ----------------------------------------------------------------
        audit_reason = change_reason or "Test case updated via MCP"

        for field_name, old_value, new_value in changes:
            # Truncate long values for audit log readability
            old_display = str(old_value)[:500] if old_value else None
            new_display = str(new_value)[:500] if new_value else None

            cursor.execute(
                """
                INSERT INTO audit_history (
                    record_type, record_id, action, field_changed,
                    old_value, new_value, changed_by, changed_date, change_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    'test_case',
                    test_id,
                    'Updated',
                    field_name,
                    old_display,
                    new_display,
                    'MCP:update_test_case',
                    now,
                    audit_reason
                )
            )

        conn.commit()

        # ----------------------------------------------------------------
        # STEP 11: Build success response
        # ----------------------------------------------------------------
        result = f"""Test case updated successfully!

Test Case: {test_id}
Parent Story: {old_test['story_id']} - {old_test['story_title'][:40]}
Program: {old_test['program_name']} [{old_test['prefix']}]

Changes made ({len(changes)} field(s)):
"""
        for field_name, old_val, new_val in changes:
            # Format display based on field type
            if field_name in ('test_steps', 'expected_results', 'prerequisites'):
                # For long text fields, just show that it was updated
                result += f"  • {field_name}: (updated)\n"
            else:
                old_str = str(old_val)[:40] if old_val else '(none)'
                new_str = str(new_val)[:40] if new_val else '(none)'
                result += f"  • {field_name}: '{old_str}' → '{new_str}'\n"

        if change_reason:
            result += f"\nChange Reason: {change_reason}\n"

        result += f"""
Updated At: {now}

Next Steps:
  • list_test_cases(story_id="{updates.get('story_id', old_test['story_id'])}") - View test cases
  • update_test_result(test_id="{test_id}", ...) - Record execution results
"""
        return result

    except Exception as e:
        return f"Error updating test case: {str(e)}"

    finally:
        if conn:
            conn.close()


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
# FORM DEFINITION MANAGEMENT TOOLS
# ============================================================
# Tools for managing the onboarding form questions in form-definition.json

# Path to form definition file
FORM_DEF_PATH = os.path.expanduser("~/projects/propel-onboarding-form/src/data/form-definition.json")


def _log_form_audit(
    action: str,
    entity_type: str,
    entity_id: str,
    details: str,
    old_value: str = None,
    new_value: str = None
):
    """Log form definition changes to audit_history table."""
    import sqlite3

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO audit_history (
                timestamp, action, entity_type, entity_id,
                field_name, old_value, new_value, changed_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            action,
            entity_type,
            entity_id,
            details,
            old_value,
            new_value,
            "MCP:form_admin"
        ))

        conn.commit()
    except Exception as e:
        print(f"Audit log warning: {e}")
    finally:
        conn.close()


@mcp.tool()
def list_form_questions(
    step_id: str = None,
    show_details: bool = False
) -> str:
    """
    List questions in the onboarding form.

    Args:
        step_id: Optional step ID to filter (e.g., "clinic_info"). If None, shows all steps.
        show_details: If True, show full question properties. If False, show summary only.

    Returns:
        Formatted list of questions organized by step

    Example:
        list_form_questions()  # All steps, summary view
        list_form_questions(step_id="lab_config", show_details=True)  # One step, full details
    """
    import json

    try:
        with open(FORM_DEF_PATH, 'r') as f:
            form_def = json.load(f)
    except FileNotFoundError:
        return "Error: form-definition.json not found. Is the repo cloned?"
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in form-definition.json: {e}"

    output = []
    output.append(f"Form: {form_def.get('title', 'Unknown')}")
    output.append(f"Version: {form_def.get('version', 'Unknown')}")
    output.append("=" * 60)

    for step in form_def.get('steps', []):
        # Filter by step_id if provided
        if step_id and step.get('step_id') != step_id:
            continue

        output.append(f"\nStep {step.get('order', '?')}: {step.get('title', 'Unknown')}")
        output.append(f"   ID: {step.get('step_id', 'Unknown')}")

        if step.get('repeatable'):
            output.append(f"   Repeatable (min: {step.get('repeatable_config', {}).get('min_items', 0)}, max: {step.get('repeatable_config', {}).get('max_items', 'unlimited')})")

        if step.get('is_review_step'):
            output.append("   Review/Download step (no questions)")
            continue

        questions = step.get('questions', [])
        output.append(f"   Questions: {len(questions)}")

        for q in questions:
            req = "*" if q.get('required') else ""
            q_type = q.get('type', 'unknown')

            if show_details:
                output.append(f"\n   [{q.get('question_id')}] {q.get('label', 'No label')}{req}")
                output.append(f"      Type: {q_type}")
                if q.get('options_ref'):
                    output.append(f"      Options: ref:{q.get('options_ref')}")
                if q.get('show_when'):
                    sw = q.get('show_when')
                    output.append(f"      Conditional: {sw.get('question_id')} {sw.get('operator')} {sw.get('value')}")
                if q.get('help_text'):
                    help_preview = q.get('help_text')[:50] + "..." if len(q.get('help_text', '')) > 50 else q.get('help_text')
                    output.append(f"      Help: {help_preview}")
                if q.get('placeholder'):
                    output.append(f"      Placeholder: {q.get('placeholder')}")
                if q.get('pattern'):
                    output.append(f"      Pattern: {q.get('pattern')}")
            else:
                output.append(f"   - {q.get('question_id')}: {q.get('label', 'No label')}{req} ({q_type})")

    if step_id and not any(s.get('step_id') == step_id for s in form_def.get('steps', [])):
        return f"Error: Step '{step_id}' not found. Use list_form_questions() to see available steps."

    return "\n".join(output)


@mcp.tool()
def add_form_question(
    step_id: str,
    question_id: str,
    question_type: str,
    label: str,
    required: bool = False,
    options_ref: str = None,
    help_text: str = None,
    placeholder: str = None,
    pattern: str = None,
    max_length: int = None,
    show_when_question: str = None,
    show_when_operator: str = None,
    show_when_value: str = None,
    insert_after: str = None
) -> str:
    """
    Add a new question to a step in the onboarding form.

    Args:
        step_id: Step to add question to (e.g., "clinic_info", "lab_config")
        question_id: Unique ID for the question (e.g., "clinic_fax")
        question_type: Type of question: text, textarea, select, radio, checkbox,
                       address, contact_group, stakeholder_group, select_with_alternates
        label: Display label for the question
        required: Whether the field is required (default: False)
        options_ref: Reference to options in reference-data.json (for select/radio types)
        help_text: Help text displayed below the field
        placeholder: Placeholder text for text inputs
        pattern: Regex pattern for validation (e.g., "^[0-9]{10}$" for NPI)
        max_length: Maximum character length for text fields
        show_when_question: Question ID that controls visibility (conditional field)
        show_when_operator: Operator for condition: "equals", "in", "not_equals"
        show_when_value: Value(s) that trigger showing this field
        insert_after: Question ID to insert after. If None, adds to end of step.

    Returns:
        Confirmation message with the added question details

    Example:
        add_form_question(
            step_id="clinic_info",
            question_id="clinic_fax",
            question_type="text",
            label="Clinic Fax Number",
            required=False,
            placeholder="406-555-1234",
            insert_after="clinic_phone"
        )
    """
    import json

    # Load current form definition
    try:
        with open(FORM_DEF_PATH, 'r') as f:
            form_def = json.load(f)
    except FileNotFoundError:
        return "Error: form-definition.json not found."
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON: {e}"

    # Find the step
    step = None
    for s in form_def.get('steps', []):
        if s.get('step_id') == step_id:
            step = s
            break

    if not step:
        available = [s.get('step_id') for s in form_def.get('steps', [])]
        return f"Error: Step '{step_id}' not found. Available steps: {', '.join(available)}"

    # Check for duplicate question_id across ALL steps
    for s in form_def.get('steps', []):
        for q in s.get('questions', []):
            if q.get('question_id') == question_id:
                return f"Error: question_id '{question_id}' already exists in step '{s.get('step_id')}'"

    # Build the question object
    new_question = {
        "question_id": question_id,
        "type": question_type,
        "label": label,
        "required": required
    }

    # Add optional fields
    if options_ref:
        new_question["options_ref"] = options_ref
    if help_text:
        new_question["help_text"] = help_text
    if placeholder:
        new_question["placeholder"] = placeholder
    if pattern:
        new_question["pattern"] = pattern
    if max_length:
        new_question["max_length"] = max_length

    # Add conditional visibility
    if show_when_question and show_when_operator and show_when_value:
        # Parse value - could be a list for "in" operator
        value = show_when_value
        if show_when_operator == "in" and "," in show_when_value:
            value = [v.strip() for v in show_when_value.split(",")]

        new_question["show_when"] = {
            "question_id": show_when_question,
            "operator": show_when_operator,
            "value": value
        }

    # Ensure questions list exists
    if 'questions' not in step:
        step['questions'] = []

    # Insert at position
    if insert_after:
        # Find the index of insert_after question
        insert_idx = None
        for idx, q in enumerate(step['questions']):
            if q.get('question_id') == insert_after:
                insert_idx = idx + 1
                break

        if insert_idx is None:
            return f"Error: insert_after question '{insert_after}' not found in step '{step_id}'"

        step['questions'].insert(insert_idx, new_question)
        position_msg = f"after '{insert_after}'"
    else:
        step['questions'].append(new_question)
        position_msg = "at end of step"

    # Save the updated form definition
    with open(FORM_DEF_PATH, 'w') as f:
        json.dump(form_def, f, indent=2)

    # Audit log
    _log_form_audit(
        action="ADD_QUESTION",
        entity_type="form_question",
        entity_id=question_id,
        details=f"Added to step '{step_id}' {position_msg}",
        new_value=json.dumps(new_question)
    )

    return f"""Question added successfully!

Step: {step_id}
Question ID: {question_id}
Label: {label}
Type: {question_type}
Required: {required}
Position: {position_msg}

Next steps:
  - Run list_form_questions(step_id="{step_id}") to verify
  - Push changes: cd ~/projects/propel-onboarding-form && git add . && git commit -m "Add {question_id} question" && git push
"""


@mcp.tool()
def update_form_question(
    question_id: str,
    label: str = None,
    required: bool = None,
    help_text: str = None,
    placeholder: str = None,
    pattern: str = None,
    max_length: int = None,
    options_ref: str = None,
    show_when_question: str = None,
    show_when_operator: str = None,
    show_when_value: str = None,
    clear_show_when: bool = False
) -> str:
    """
    Update an existing question's properties. Only provided fields are updated.

    Args:
        question_id: ID of question to update
        label: New display label
        required: Change required status
        help_text: New help text (use empty string "" to clear)
        placeholder: New placeholder text
        pattern: New regex validation pattern
        max_length: New max length
        options_ref: New options reference
        show_when_question: Question ID for conditional visibility
        show_when_operator: Operator for condition
        show_when_value: Value(s) for condition
        clear_show_when: If True, removes conditional visibility

    Returns:
        Confirmation with old and new values

    Example:
        update_form_question(
            question_id="clinic_name",
            label="Primary Clinic Name",
            help_text="Enter the official clinic name as it appears on your license"
        )
    """
    import json

    with open(FORM_DEF_PATH, 'r') as f:
        form_def = json.load(f)

    # Find the question
    found_step = None
    found_question = None
    for step in form_def.get('steps', []):
        for q in step.get('questions', []):
            if q.get('question_id') == question_id:
                found_step = step
                found_question = q
                break
        if found_question:
            break

    if not found_question:
        return f"Error: Question '{question_id}' not found in any step."

    # Track changes
    changes = []
    old_values = {}

    # Update provided fields
    if label is not None:
        old_values['label'] = found_question.get('label')
        found_question['label'] = label
        changes.append(f"label: '{old_values['label']}' -> '{label}'")

    if required is not None:
        old_values['required'] = found_question.get('required')
        found_question['required'] = required
        changes.append(f"required: {old_values['required']} -> {required}")

    if help_text is not None:
        old_values['help_text'] = found_question.get('help_text')
        if help_text == "":
            found_question.pop('help_text', None)
            changes.append("help_text: removed")
        else:
            found_question['help_text'] = help_text
            changes.append("help_text: updated")

    if placeholder is not None:
        old_values['placeholder'] = found_question.get('placeholder')
        found_question['placeholder'] = placeholder
        changes.append(f"placeholder: '{old_values['placeholder']}' -> '{placeholder}'")

    if pattern is not None:
        old_values['pattern'] = found_question.get('pattern')
        found_question['pattern'] = pattern
        changes.append(f"pattern: '{old_values['pattern']}' -> '{pattern}'")

    if max_length is not None:
        old_values['max_length'] = found_question.get('max_length')
        found_question['max_length'] = max_length
        changes.append(f"max_length: {old_values['max_length']} -> {max_length}")

    if options_ref is not None:
        old_values['options_ref'] = found_question.get('options_ref')
        found_question['options_ref'] = options_ref
        changes.append(f"options_ref: '{old_values['options_ref']}' -> '{options_ref}'")

    if clear_show_when:
        if 'show_when' in found_question:
            old_values['show_when'] = found_question.pop('show_when')
            changes.append("show_when: removed (question now always visible)")
    elif show_when_question and show_when_operator and show_when_value:
        old_values['show_when'] = found_question.get('show_when')
        value = show_when_value
        if show_when_operator == "in" and "," in show_when_value:
            value = [v.strip() for v in show_when_value.split(",")]
        found_question['show_when'] = {
            "question_id": show_when_question,
            "operator": show_when_operator,
            "value": value
        }
        changes.append(f"show_when: updated to depend on '{show_when_question}'")

    if not changes:
        return "No changes provided. Specify at least one field to update."

    # Save
    with open(FORM_DEF_PATH, 'w') as f:
        json.dump(form_def, f, indent=2)

    # Audit log
    _log_form_audit(
        action="UPDATE_QUESTION",
        entity_type="form_question",
        entity_id=question_id,
        details=f"Updated in step '{found_step.get('step_id')}'",
        old_value=json.dumps(old_values),
        new_value=json.dumps({k: found_question.get(k) for k in old_values.keys()})
    )

    changes_formatted = "\n  - ".join(changes)
    return f"""Question updated successfully!

Question ID: {question_id}
Step: {found_step.get('step_id')}

Changes:
  - {changes_formatted}

Next steps:
  - Run list_form_questions(step_id="{found_step.get('step_id')}", show_details=True) to verify
  - Push changes to GitHub
"""


@mcp.tool()
def remove_form_question(
    question_id: str,
    reason: str
) -> str:
    """
    Remove a question from the onboarding form.

    Args:
        question_id: ID of question to remove
        reason: Reason for removal (required for audit trail)

    Returns:
        Confirmation with removed question details

    Example:
        remove_form_question(
            question_id="clinic_fax",
            reason="Fax numbers no longer collected - moved to optional notes"
        )
    """
    import json

    with open(FORM_DEF_PATH, 'r') as f:
        form_def = json.load(f)

    # Find and remove the question
    found_step = None
    removed_question = None
    for step in form_def.get('steps', []):
        for idx, q in enumerate(step.get('questions', [])):
            if q.get('question_id') == question_id:
                found_step = step
                removed_question = step['questions'].pop(idx)
                break
        if removed_question:
            break

    if not removed_question:
        return f"Error: Question '{question_id}' not found in any step."

    # Check if any other questions depend on this one (show_when)
    dependencies = []
    for step in form_def.get('steps', []):
        for q in step.get('questions', []):
            show_when = q.get('show_when', {})
            if show_when.get('question_id') == question_id:
                dependencies.append(f"{q.get('question_id')} (in {step.get('step_id')})")

    if dependencies:
        # Re-add the question since we can't remove it
        found_step['questions'].append(removed_question)
        deps_formatted = "\n  - ".join(dependencies)
        return f"""Error: Cannot remove '{question_id}' - other questions depend on it:

Dependent questions:
  - {deps_formatted}

Remove or update the dependent questions first, then try again."""

    # Save
    with open(FORM_DEF_PATH, 'w') as f:
        json.dump(form_def, f, indent=2)

    # Audit log
    _log_form_audit(
        action="REMOVE_QUESTION",
        entity_type="form_question",
        entity_id=question_id,
        details=f"Removed from step '{found_step.get('step_id')}'. Reason: {reason}",
        old_value=json.dumps(removed_question)
    )

    return f"""Question removed successfully!

Question ID: {question_id}
Label: {removed_question.get('label')}
Step: {found_step.get('step_id')}
Reason: {reason}

The full question definition has been saved to the audit log.

Next steps:
  - Push changes to GitHub
"""


@mcp.tool()
def reorder_form_questions(
    step_id: str,
    question_id: str,
    move_to: str,
    target_question_id: str = None
) -> str:
    """
    Reorder questions within a step.

    Args:
        step_id: Step containing the question
        question_id: Question to move
        move_to: Where to move: "first", "last", "before", "after"
        target_question_id: Required if move_to is "before" or "after"

    Returns:
        Confirmation with new question order

    Example:
        reorder_form_questions(
            step_id="clinic_info",
            question_id="clinic_phone",
            move_to="after",
            target_question_id="clinic_name"
        )
    """
    import json

    with open(FORM_DEF_PATH, 'r') as f:
        form_def = json.load(f)

    # Find the step
    step = None
    for s in form_def.get('steps', []):
        if s.get('step_id') == step_id:
            step = s
            break

    if not step:
        return f"Error: Step '{step_id}' not found."

    questions = step.get('questions', [])

    # Find the question to move
    move_idx = None
    for idx, q in enumerate(questions):
        if q.get('question_id') == question_id:
            move_idx = idx
            break

    if move_idx is None:
        return f"Error: Question '{question_id}' not found in step '{step_id}'."

    # Remove the question from current position
    question_to_move = questions.pop(move_idx)

    # Determine new position
    if move_to == "first":
        new_idx = 0
    elif move_to == "last":
        new_idx = len(questions)
    elif move_to in ("before", "after"):
        if not target_question_id:
            questions.insert(move_idx, question_to_move)  # restore
            return f"Error: target_question_id required when move_to is '{move_to}'"

        target_idx = None
        for idx, q in enumerate(questions):
            if q.get('question_id') == target_question_id:
                target_idx = idx
                break

        if target_idx is None:
            questions.insert(move_idx, question_to_move)  # restore
            return f"Error: Target question '{target_question_id}' not found in step '{step_id}'."

        new_idx = target_idx if move_to == "before" else target_idx + 1
    else:
        questions.insert(move_idx, question_to_move)  # restore
        return f"Error: Invalid move_to value '{move_to}'. Use: first, last, before, after"

    # Insert at new position
    questions.insert(new_idx, question_to_move)

    # Save
    with open(FORM_DEF_PATH, 'w') as f:
        json.dump(form_def, f, indent=2)

    # Build new order display
    new_order = [q.get('question_id') for q in questions]
    order_formatted = "\n  ".join([f"{i+1}. {qid}" for i, qid in enumerate(new_order)])

    # Audit log
    _log_form_audit(
        action="REORDER_QUESTION",
        entity_type="form_question",
        entity_id=question_id,
        details=f"Moved to position {new_idx + 1} in step '{step_id}'"
    )

    target_msg = f" {target_question_id}" if target_question_id else ""
    return f"""Question reordered successfully!

Step: {step_id}
Moved: {question_id}
Position: {move_to}{target_msg}

New order:
  {order_formatted}

Next steps:
  - Push changes to GitHub
"""


# ============================================================
# DASHBOARD DATA GENERATION TOOLS
# ============================================================
# Tools for generating static JSON data files for the clinic dashboard
# Dashboard location: ~/projects/propel-clinic-dashboard/

# Default output path for dashboard data
DASHBOARD_DATA_PATH = os.path.expanduser(
    "~/projects/propel-clinic-dashboard/src/data/dashboard-data.json"
)


@mcp.tool()
def generate_dashboard_data(
    show_audit_trail: bool = False,
    output_path: str = None,
    days_of_audit: int = 30
) -> str:
    """
    Generate dashboard JSON data for the clinic configuration dashboard.

    This tool queries the client_product_database and generates a JSON file
    containing users, training records, configurations, providers, and
    optionally audit history. The output is designed for the static GitHub
    Pages dashboard at propel-clinic-dashboard.

    Args:
        show_audit_trail: If True, includes audit_trail in output (default: False)
        output_path: Where to write JSON file (default: ~/projects/propel-clinic-dashboard/src/data/dashboard-data.json)
        days_of_audit: How many days of audit history to include (default: 30)

    Returns:
        Confirmation message with file path and summary stats
    """
    import json
    import sqlite3

    # =========================================================================
    # SETUP
    # =========================================================================
    # Use default path if not specified
    if output_path is None:
        output_path = DASHBOARD_DATA_PATH
    else:
        output_path = os.path.expanduser(output_path)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Connect to database with Row factory for dict-like access
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.cursor()

        # =====================================================================
        # QUERY 1: PROGRAMS LIST
        # =====================================================================
        # Get all active programs with their prefix (used as ID in dashboard)
        # and display name
        cursor.execute("""
            SELECT DISTINCT
                prefix as id,
                name as name
            FROM programs
            WHERE status = 'Active'
              AND prefix IS NOT NULL
            ORDER BY name
        """)
        programs = [dict(row) for row in cursor.fetchall()]

        # =====================================================================
        # QUERY 2: USERS WITH ACCESS
        # =====================================================================
        # Join users with their access records to get program, clinic, role
        # Note: user_access doesn't have last_access_date, so we use granted_date
        # as a proxy. In production, you'd want to track actual login times.
        cursor.execute("""
            SELECT DISTINCT
                u.name,
                u.email,
                p.prefix as program,
                c.name as clinic,
                ua.role,
                u.status,
                ua.granted_date as last_access
            FROM users u
            JOIN user_access ua ON u.user_id = ua.user_id
            JOIN clinics c ON ua.clinic_id = c.clinic_id
            JOIN programs p ON ua.program_id = p.program_id
            WHERE ua.is_active = 1
            ORDER BY u.name
        """)
        users = [dict(row) for row in cursor.fetchall()]

        # =====================================================================
        # QUERY 3: TRAINING RECORDS
        # =====================================================================
        # Get training status for each user. Calculate status based on
        # expiration date:
        # - Expired: expires_date < today
        # - Due Soon: expires_date within 30 days
        # - Current: expires_date > 30 days away
        cursor.execute("""
            SELECT DISTINCT
                u.name,
                u.email,
                p.prefix as program,
                ut.training_type,
                ut.completed_date as completion_date,
                ut.expires_date as expiration_date,
                CASE
                    WHEN ut.expires_date < date('now') THEN 'Expired'
                    WHEN ut.expires_date < date('now', '+30 days') THEN 'Due Soon'
                    ELSE 'Current'
                END as status
            FROM user_training ut
            JOIN users u ON ut.user_id = u.user_id
            JOIN user_access ua ON u.user_id = ua.user_id AND ua.is_active = 1
            JOIN programs p ON ua.program_id = p.program_id
            WHERE ut.completed_date IS NOT NULL
            ORDER BY u.name, ut.training_type
        """)
        training = [dict(row) for row in cursor.fetchall()]

        # =====================================================================
        # QUERY 4: CONFIGURATIONS WITH INHERITANCE SOURCE
        # =====================================================================
        # Get all configuration values showing where they come from in the
        # inheritance chain: Program Default → Clinic Override → Location Override
        # The source is determined by which level has the config set:
        # - Location Override: location_id is set
        # - Clinic Override: clinic_id is set but not location_id
        # - Program Default: only program_id is set
        cursor.execute("""
            SELECT
                p.prefix as program,
                c.name as clinic,
                l.name as location,
                cv.config_key,
                cv.value as config_value,
                CASE
                    WHEN cv.location_id IS NOT NULL THEN 'Location Override'
                    WHEN cv.clinic_id IS NOT NULL THEN 'Clinic Override'
                    ELSE 'Program Default'
                END as source
            FROM config_values cv
            JOIN programs p ON cv.program_id = p.program_id
            LEFT JOIN clinics c ON cv.clinic_id = c.clinic_id
            LEFT JOIN locations l ON cv.location_id = l.location_id
            WHERE p.status = 'Active'
            ORDER BY p.prefix, c.name, l.name, cv.config_key
        """)
        configurations = [dict(row) for row in cursor.fetchall()]

        # =====================================================================
        # QUERY 5: PROVIDERS
        # =====================================================================
        # Get all active providers. Providers are linked to locations, so we
        # need to join through locations to get clinic and program info.
        cursor.execute("""
            SELECT
                prov.name as name,
                prov.npi,
                p.prefix as program,
                c.name as clinic,
                l.name as location,
                prov.specialty
            FROM providers prov
            JOIN locations l ON prov.location_id = l.location_id
            JOIN clinics c ON l.clinic_id = c.clinic_id
            JOIN programs p ON c.program_id = p.program_id
            WHERE prov.is_active = 1
              AND p.status = 'Active'
            ORDER BY prov.name
        """)
        providers = [dict(row) for row in cursor.fetchall()]

        # =====================================================================
        # QUERY 6: AUDIT TRAIL (CONDITIONAL)
        # =====================================================================
        # Only query audit history if show_audit_trail is True.
        # Limits to the specified number of days and max 500 records.
        audit_trail = []
        if show_audit_trail:
            cursor.execute("""
                SELECT
                    changed_date as timestamp,
                    action,
                    record_type as entity_type,
                    record_id as entity_id,
                    changed_by,
                    change_reason as details
                FROM audit_history
                WHERE changed_date >= date('now', '-' || ? || ' days')
                ORDER BY changed_date DESC
                LIMIT 500
            """, (days_of_audit,))
            audit_trail = [dict(row) for row in cursor.fetchall()]

        # =====================================================================
        # CALCULATE SUMMARY STATISTICS
        # =====================================================================
        # Aggregate metrics for the dashboard summary cards
        total_users = len(users)
        active_users = len([u for u in users if u.get('status') == 'Active'])

        # Training compliance: count users with at least one 'Current' training
        # and divide by total users
        users_with_current_training = set()
        for t in training:
            if t.get('status') == 'Current':
                users_with_current_training.add(t.get('email'))
        training_compliant = len(users_with_current_training)
        training_compliance_pct = round(
            (training_compliant / total_users * 100) if total_users > 0 else 0,
            1
        )

        # Count unique clinics and total providers
        total_clinics = len(set(u.get('clinic') for u in users if u.get('clinic')))
        total_providers = len(providers)

        summary = {
            "total_users": total_users,
            "active_users": active_users,
            "training_compliant": training_compliant,
            "training_compliance_pct": training_compliance_pct,
            "total_clinics": total_clinics,
            "total_providers": total_providers
        }

        # =====================================================================
        # BUILD OUTPUT STRUCTURE
        # =====================================================================
        # Assemble the final JSON structure matching the dashboard's expected format
        generated_at = datetime.now().isoformat() + "Z"

        output = {
            "generated_at": generated_at,
            "show_audit_trail": show_audit_trail,
            "summary": summary,
            "programs": programs,
            "users": users,
            "training": training,
            "configurations": configurations,
            "providers": providers,
            "audit_trail": audit_trail
        }

        # =====================================================================
        # WRITE JSON FILE
        # =====================================================================
        # Write with indent=2 for human-readable output
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2, default=str)

        # =====================================================================
        # LOG AUDIT ENTRY
        # =====================================================================
        # Record that dashboard data was generated
        cursor.execute("""
            INSERT INTO audit_history (
                record_type, record_id, action,
                old_value, new_value, changed_by, changed_date, change_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "dashboard_data",
            "dashboard-data.json",
            "Generated",
            None,
            json.dumps(summary),
            "MCP:generate_dashboard_data",
            generated_at,
            f"Users: {total_users}, Clinics: {total_clinics}, Providers: {total_providers}"
        ))
        conn.commit()

        # =====================================================================
        # BUILD RETURN MESSAGE
        # =====================================================================
        audit_status = f"Included ({len(audit_trail)} entries, last {days_of_audit} days)" if show_audit_trail else "Excluded (set show_audit_trail=True to include)"

        return f"""Dashboard data generated successfully!

File: {output_path}
Generated: {generated_at}

Summary:
  Users: {total_users} ({active_users} active)
  Training Compliance: {training_compliance_pct}%
  Clinics: {total_clinics}
  Providers: {total_providers}
  Audit Trail: {audit_status}

Data sections:
  - programs: {len(programs)} programs
  - users: {len(users)} user access records
  - training: {len(training)} training records
  - configurations: {len(configurations)} config values
  - providers: {len(providers)} providers
  - audit_trail: {len(audit_trail)} entries

Next steps:
  1. Review the generated JSON file
  2. Push to GitHub Pages: cd ~/projects/propel-clinic-dashboard && git add -A && git commit -m "Update dashboard data" && git push
  3. Dashboard will update automatically at your GitHub Pages URL
"""

    except sqlite3.Error as e:
        return f"Database error: {str(e)}\n\nMake sure the database exists at: {DB_PATH}"

    except Exception as e:
        return f"Error generating dashboard data: {str(e)}"

    finally:
        # Always close the database connection
        conn.close()


# ============================================================
# RUN SERVER
# ============================================================
if __name__ == "__main__":
    mcp.run()
