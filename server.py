"""
Propel Health MCP Server
========================
Connects Claude to the Propel Health toolkits.

Available Tool Categories:
- User Management: list_users, get_user, add_user
- Access Management: list_access, get_reviews_due
- Training: get_training_status, get_expired_training
- Compliance: get_compliance_report
- Configuration: list_programs, get_config
"""

# ============================================================
# IMPORTS
# ============================================================
import os
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
# HELPER FUNCTIONS
# ============================================================

def get_access_manager() -> AccessManager:
    """Create AccessManager instance with configured DB path."""
    return AccessManager(db_path=DB_PATH)


def get_config_manager() -> ConfigurationManager:
    """Create ConfigurationManager instance with configured DB path."""
    return ConfigurationManager(db_path=DB_PATH)


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
    organization: Optional[str] = None
) -> str:
    """
    List users from the Propel Health database.

    Args:
        program: Filter by program name (e.g., "Prevention4ME")
        status: Filter by status ("Active", "Inactive", "Terminated")
        organization: Filter by organization name

    Returns:
        Formatted list of users with their status and access count
    """
    try:
        manager = get_access_manager()
        users = manager.list_users(
            program_filter=program,
            status_filter=status,
            organization_filter=organization,
            include_access_count=True
        )
        manager.close()

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


@mcp.tool()
def get_user(email: str) -> str:
    """
    Get detailed information about a specific user.

    Args:
        email: User's email address

    Returns:
        User details including status, organization, and access grants
    """
    try:
        manager = get_access_manager()
        user = manager.get_user(email=email)

        if not user:
            manager.close()
            return f"User not found: {email}"

        # Get user's access grants
        access_list = manager.list_access(user_id=user['user_id'])

        # Get user's training status
        training = manager.get_user_training(user['user_id'])

        manager.close()

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
    try:
        manager = get_access_manager()

        # Check if user already exists
        existing = manager.get_user(email=email)
        if existing:
            manager.close()
            return f"User already exists with email: {email}"

        user_id = manager.create_user(
            name=name,
            email=email,
            organization=organization,
            is_business_associate=is_business_associate
        )
        manager.close()

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
    try:
        manager = get_access_manager()

        user_id = None
        if user_email:
            user = manager.get_user(email=user_email)
            if not user:
                manager.close()
                return f"User not found: {user_email}"
            user_id = user['user_id']

        program_id = None
        if program:
            try:
                program_id = manager._resolve_program_id(program)
            except ValueError:
                manager.close()
                return f"Program not found: {program}"

        access_list = manager.list_access(user_id=user_id, program_id=program_id)
        manager.close()

        if not access_list:
            return "No access grants found matching the criteria."

        # Group by user
        result = f"Found {len(access_list)} access grant(s):\n\n"
        for access in access_list:
            status = "Active" if access.get('is_active') else "Revoked"
            result += f"• {access.get('user_name', 'Unknown')} ({access.get('user_email')})\n"
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


@mcp.tool()
def get_reviews_due(program: Optional[str] = None) -> str:
    """
    Get access reviews that are overdue or due soon.

    Args:
        program: Filter by program name (optional)

    Returns:
        List of access grants needing review
    """
    try:
        manager = get_access_manager()

        program_id = None
        if program:
            try:
                program_id = manager._resolve_program_id(program)
            except ValueError:
                manager.close()
                return f"Program not found: {program}"

        reviews = manager.get_reviews_due(program_id=program_id)
        manager.close()

        if not reviews:
            return "No reviews are currently due. All access reviews are up to date!"

        overdue = [r for r in reviews if r.get('is_overdue')]
        due_soon = [r for r in reviews if not r.get('is_overdue')]

        result = f"Access Reviews Due: {len(reviews)} total\n\n"

        if overdue:
            result += f"⚠️  OVERDUE ({len(overdue)}):\n"
            for r in overdue:
                result += f"  • {r.get('user_name')} - {r.get('program_name')} ({r.get('role')})\n"
                result += f"    Due: {r.get('next_review_due')} | Days overdue: {r.get('days_overdue')}\n"
            result += "\n"

        if due_soon:
            result += f"📅 Due Soon ({len(due_soon)}):\n"
            for r in due_soon:
                result += f"  • {r.get('user_name')} - {r.get('program_name')} ({r.get('role')})\n"
                result += f"    Due: {r.get('next_review_due')}\n"

        return result

    except Exception as e:
        return f"Error getting reviews: {str(e)}"


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
    try:
        manager = get_access_manager()

        user = manager.get_user(email=user_email)
        if not user:
            manager.close()
            return f"User not found: {user_email}"

        training = manager.get_user_training(user['user_id'])
        manager.close()

        if not training:
            return f"No training records found for {user['name']}."

        result = f"Training Status for {user['name']}:\n\n"

        # Group by status
        current = [t for t in training if t.get('status') == 'Current']
        pending = [t for t in training if t.get('status') == 'Pending']
        expired = [t for t in training if t.get('status') == 'Expired']

        if current:
            result += f"✅ Current ({len(current)}):\n"
            for t in current:
                result += f"  • {t.get('training_type')}"
                if t.get('expires_date'):
                    result += f" (expires: {t.get('expires_date')})"
                result += "\n"
            result += "\n"

        if pending:
            result += f"⏳ Pending ({len(pending)}):\n"
            for t in pending:
                result += f"  • {t.get('training_type')} (assigned: {t.get('assigned_date')})\n"
            result += "\n"

        if expired:
            result += f"❌ Expired ({len(expired)}):\n"
            for t in expired:
                result += f"  • {t.get('training_type')} (expired: {t.get('expires_date')})\n"

        return result

    except Exception as e:
        return f"Error getting training status: {str(e)}"


@mcp.tool()
def get_expired_training() -> str:
    """
    Get all users with expired training that needs renewal.

    Returns:
        List of users and their expired training records
    """
    try:
        manager = get_access_manager()
        expired = manager.get_expired_training()
        manager.close()

        if not expired:
            return "No expired training found. All training is current!"

        result = f"⚠️  Expired Training: {len(expired)} record(s)\n\n"

        for record in expired:
            result += f"• {record.get('user_name')} ({record.get('user_email')})\n"
            result += f"  Training: {record.get('training_type')}\n"
            result += f"  Expired: {record.get('expires_date')}\n\n"

        return result

    except Exception as e:
        return f"Error getting expired training: {str(e)}"


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

    try:
        manager = get_access_manager()
        reports = ComplianceReports(manager)

        program_id = None
        if program:
            try:
                program_id = manager._resolve_program_id(program)
            except ValueError:
                manager.close()
                return f"Program not found: {program}"

        result = ""

        if report_type == 'access_list':
            data = reports.access_list_report(program_id=program_id)
            result = f"Access List Report\n"
            result += f"==================\n\n"
            result += f"Total Users: {data['summary']['total_users']}\n"
            result += f"Total Access Grants: {data['summary']['total_grants']}\n\n"

            for user in data.get('users', [])[:20]:  # Limit to 20
                result += f"• {user.get('name')} ({user.get('email')})\n"
                for grant in user.get('access', []):
                    result += f"  - {grant.get('program')}: {grant.get('role')}\n"
                result += "\n"

            if len(data.get('users', [])) > 20:
                result += f"... and {len(data['users']) - 20} more users\n"

        elif report_type == 'review_status':
            data = reports.review_status_report(program_id=program_id)
            result = f"Access Review Status\n"
            result += f"====================\n\n"
            result += f"Current: {data['summary']['current']}\n"
            result += f"Due Soon: {data['summary']['due_soon']}\n"
            result += f"Overdue: {data['summary']['overdue']}\n"

            if data['summary']['overdue'] > 0:
                result += f"\n⚠️  Action Required: {data['summary']['overdue']} overdue reviews\n"

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
                result += "✅ No issues found. All terminated users have had access revoked.\n"
            else:
                result += f"⚠️  VIOLATIONS FOUND: {len(data['violations'])}\n\n"
                for v in data['violations']:
                    result += f"• {v.get('user_name')} - still has {v.get('active_grants')} active grant(s)\n"

        elif report_type == 'business_associates':
            data = reports.business_associates_report()
            result = f"Business Associates Report\n"
            result += f"==========================\n\n"
            result += f"Total Business Associates: {data['summary']['total']}\n"
            result += f"Active: {data['summary']['active']}\n\n"

            for ba in data.get('associates', []):
                result += f"• {ba.get('name')} ({ba.get('organization')})\n"
                result += f"  Email: {ba.get('email')} | Status: {ba.get('status')}\n\n"

        manager.close()
        return result

    except Exception as e:
        return f"Error generating report: {str(e)}"


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
    try:
        cm = get_config_manager()
        programs = cm.list_programs()
        cm.close()

        if not programs:
            return "No programs found in the database."

        result = "Programs:\n"
        result += "=========\n\n"

        for program in programs:
            result += f"📁 {program.get('name')} ({program.get('prefix')})\n"
            result += f"   Type: {program.get('program_type')} | Status: {program.get('status')}\n"

            clinics = program.get('clinics', [])
            if clinics:
                for clinic in clinics:
                    result += f"   └── 🏥 {clinic.get('name')}"
                    if clinic.get('code'):
                        result += f" [{clinic.get('code')}]"
                    result += "\n"

                    locations = clinic.get('locations', [])
                    for loc in locations:
                        result += f"       └── 📍 {loc.get('name')}"
                        if loc.get('code'):
                            result += f" [{loc.get('code')}]"
                        result += "\n"

            result += "\n"

        return result

    except Exception as e:
        return f"Error listing programs: {str(e)}"


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
    try:
        cm = get_config_manager()
        im = InheritanceManager(cm)

        # Resolve IDs
        program_id = cm.get_program_id(program)
        if not program_id:
            cm.close()
            return f"Program not found: {program}"

        clinic_id = None
        if clinic:
            clinic_id = cm.get_clinic_id(program_id, clinic)
            if not clinic_id:
                cm.close()
                return f"Clinic not found: {clinic}"

        location_id = None
        if location:
            if not clinic_id:
                cm.close()
                return "Location requires clinic to be specified"
            location_id = cm.get_location_id(clinic_id, location)
            if not location_id:
                cm.close()
                return f"Location not found: {location}"

        # Get config with inheritance
        config = im.resolve_with_inheritance(
            config_key, program_id, clinic_id, location_id
        )
        cm.close()

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
                marker = "→" if level.get('is_effective') else " "
                override = "*" if level.get('is_override') else ""
                result += f"  {marker} {level.get('level')}: {level.get('value', '(inherited)')}{override}\n"

        return result

    except Exception as e:
        return f"Error getting config: {str(e)}"


# ============================================================
# RUN SERVER
# ============================================================
if __name__ == "__main__":
    mcp.run()
