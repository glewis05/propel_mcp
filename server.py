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
from datetime import datetime
from typing import Optional

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
            result += f"Total Business Associates: {data['summary']['total']}\n"
            result += f"Active: {data['summary']['active']}\n\n"

            for ba in data.get('associates', []):
                result += f"• {ba.get('name')} ({ba.get('organization')})\n"
                result += f"  Email: {ba.get('email')} | Status: {ba.get('status')}\n\n"

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
# RUN SERVER
# ============================================================
if __name__ == "__main__":
    mcp.run()
