"""Multi-tenant: tenants table, tenant_id on all business tables, tenant-scoped uniques.

Revision ID: 002_multi_tenant
Revises: 001_initial
Create Date: 2025-02-18

"""
from alembic import op
import sqlalchemy as sa
import uuid

# revision identifiers, used by Alembic.
revision = "002_multi_tenant"
down_revision = "001_initial"
branch_labels = None
depends_on = None

# Default tenant UUID for backfilling existing rows (single-tenant becomes this tenant)
DEFAULT_TENANT_ID = str(uuid.uuid4())


def upgrade():
    # 1. Create tenants table
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("subdomain", sa.String(63), nullable=False),
        sa.Column("contact_email", sa.String(120), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("plan_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tenants_status"), "tenants", ["status"], unique=False)
    op.create_index(op.f("ix_tenants_subdomain"), "tenants", ["subdomain"], unique=True)

    # 2. Insert default tenant for existing data
    op.execute(
        sa.text(
            """
            INSERT INTO tenants (id, name, subdomain, status, created_at, updated_at)
            VALUES (:id, :name, :subdomain, :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        ).bindparams(
            id=DEFAULT_TENANT_ID,
            name="Default School",
            subdomain="default",
            status="active",
        )
    )

    # 3. Add tenant_id (nullable first) to all business tables, then backfill, then NOT NULL + FK

    # --- users ---
    op.add_column("users", sa.Column("tenant_id", sa.String(36), nullable=True))
    op.execute(sa.text("UPDATE users SET tenant_id = :tid").bindparams(tid=DEFAULT_TENANT_ID))
    op.alter_column("users", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_users_tenant_id", "users", "tenants",
        ["tenant_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(op.f("ix_users_tenant_id"), "users", ["tenant_id"], unique=False)
    op.drop_index("ix_users_email", table_name="users")
    op.create_index(
        "uq_users_email_tenant",
        "users",
        ["email", "tenant_id"],
        unique=True,
    )

    # --- sessions ---
    op.add_column("sessions", sa.Column("tenant_id", sa.String(36), nullable=True))
    op.execute(sa.text("UPDATE sessions SET tenant_id = :tid").bindparams(tid=DEFAULT_TENANT_ID))
    op.alter_column("sessions", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_sessions_tenant_id", "sessions", "tenants",
        ["tenant_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(op.f("ix_sessions_tenant_id"), "sessions", ["tenant_id"], unique=False)

    # --- roles ---
    op.add_column("roles", sa.Column("tenant_id", sa.String(36), nullable=True))
    op.execute(sa.text("UPDATE roles SET tenant_id = :tid").bindparams(tid=DEFAULT_TENANT_ID))
    op.alter_column("roles", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_roles_tenant_id", "roles", "tenants",
        ["tenant_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(op.f("ix_roles_tenant_id"), "roles", ["tenant_id"], unique=False)
    op.drop_index("ix_roles_name", table_name="roles")
    op.create_index(
        "uq_roles_name_tenant",
        "roles",
        ["name", "tenant_id"],
        unique=True,
    )

    # --- role_permissions ---
    op.add_column("role_permissions", sa.Column("tenant_id", sa.String(36), nullable=True))
    op.execute(
        sa.text("UPDATE role_permissions rp SET tenant_id = (SELECT tenant_id FROM roles r WHERE r.id = rp.role_id)")
    )
    op.alter_column("role_permissions", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_role_permissions_tenant_id", "role_permissions", "tenants",
        ["tenant_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(
        op.f("ix_role_permissions_tenant_id"),
        "role_permissions",
        ["tenant_id"],
        unique=False,
    )
    op.drop_constraint("uq_role_permission", "role_permissions", type_="unique")
    op.create_unique_constraint(
        "uq_role_permission_tenant",
        "role_permissions",
        ["role_id", "permission_id", "tenant_id"],
    )

    # --- user_roles ---
    op.add_column("user_roles", sa.Column("tenant_id", sa.String(36), nullable=True))
    op.execute(
        sa.text("UPDATE user_roles ur SET tenant_id = (SELECT tenant_id FROM users u WHERE u.id = ur.user_id)")
    )
    op.alter_column("user_roles", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_user_roles_tenant_id", "user_roles", "tenants",
        ["tenant_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(
        op.f("ix_user_roles_tenant_id"),
        "user_roles",
        ["tenant_id"],
        unique=False,
    )
    op.drop_constraint("uq_user_role", "user_roles", type_="unique")
    op.create_unique_constraint(
        "uq_user_role_tenant",
        "user_roles",
        ["user_id", "role_id", "tenant_id"],
    )

    # --- classes ---
    op.add_column("classes", sa.Column("tenant_id", sa.String(36), nullable=True))
    op.execute(sa.text("UPDATE classes SET tenant_id = :tid").bindparams(tid=DEFAULT_TENANT_ID))
    op.alter_column("classes", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_classes_tenant_id", "classes", "tenants",
        ["tenant_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(op.f("ix_classes_tenant_id"), "classes", ["tenant_id"], unique=False)
    op.drop_constraint("uq_class_section_year", "classes", type_="unique")
    op.create_unique_constraint(
        "uq_class_section_year_tenant",
        "classes",
        ["name", "section", "academic_year", "tenant_id"],
    )

    # --- teachers ---
    op.add_column("teachers", sa.Column("tenant_id", sa.String(36), nullable=True))
    op.execute(
        sa.text("UPDATE teachers t SET tenant_id = (SELECT tenant_id FROM users u WHERE u.id = t.user_id)")
    )
    op.alter_column("teachers", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_teachers_tenant_id", "teachers", "tenants",
        ["tenant_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(op.f("ix_teachers_tenant_id"), "teachers", ["tenant_id"], unique=False)
    op.drop_index("ix_teachers_employee_id", table_name="teachers")
    op.drop_constraint("teachers_user_id_key", "teachers", type_="unique")
    op.create_unique_constraint(
        "uq_teachers_employee_id_tenant",
        "teachers",
        ["employee_id", "tenant_id"],
    )
    op.create_unique_constraint(
        "uq_teachers_user_id_tenant",
        "teachers",
        ["user_id", "tenant_id"],
    )

    # --- students ---
    op.add_column("students", sa.Column("tenant_id", sa.String(36), nullable=True))
    op.execute(
        sa.text("UPDATE students s SET tenant_id = (SELECT tenant_id FROM users u WHERE u.id = s.user_id)")
    )
    op.alter_column("students", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_students_tenant_id", "students", "tenants",
        ["tenant_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(op.f("ix_students_tenant_id"), "students", ["tenant_id"], unique=False)
    op.drop_index("ix_students_admission_number", table_name="students")
    op.drop_constraint("students_user_id_key", "students", type_="unique")
    op.create_unique_constraint(
        "uq_students_admission_number_tenant",
        "students",
        ["admission_number", "tenant_id"],
    )
    op.create_unique_constraint(
        "uq_students_user_id_tenant",
        "students",
        ["user_id", "tenant_id"],
    )

    # --- class_teachers ---
    op.add_column("class_teachers", sa.Column("tenant_id", sa.String(36), nullable=True))
    op.execute(
        sa.text(
            "UPDATE class_teachers ct SET tenant_id = (SELECT tenant_id FROM classes c WHERE c.id = ct.class_id)"
        )
    )
    op.alter_column("class_teachers", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_class_teachers_tenant_id", "class_teachers", "tenants",
        ["tenant_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(
        op.f("ix_class_teachers_tenant_id"),
        "class_teachers",
        ["tenant_id"],
        unique=False,
    )
    op.drop_constraint("uq_class_teacher", "class_teachers", type_="unique")
    op.create_unique_constraint(
        "uq_class_teacher_tenant",
        "class_teachers",
        ["class_id", "teacher_id", "tenant_id"],
    )

    # --- attendance ---
    op.add_column("attendance", sa.Column("tenant_id", sa.String(36), nullable=True))
    op.execute(
        sa.text(
            "UPDATE attendance a SET tenant_id = (SELECT tenant_id FROM classes c WHERE c.id = a.class_id)"
        )
    )
    op.alter_column("attendance", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_attendance_tenant_id", "attendance", "tenants",
        ["tenant_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(op.f("ix_attendance_tenant_id"), "attendance", ["tenant_id"], unique=False)
    op.drop_constraint("uq_attendance_date_class_student", "attendance", type_="unique")
    op.create_unique_constraint(
        "uq_attendance_date_class_student_tenant",
        "attendance",
        ["date", "class_id", "student_id", "tenant_id"],
    )


def downgrade():
    # Remove tenant_id and tenant-scoped constraints; restore original uniques

    # attendance
    op.drop_constraint("uq_attendance_date_class_student_tenant", "attendance", type_="unique")
    op.create_unique_constraint(
        "uq_attendance_date_class_student",
        "attendance",
        ["date", "class_id", "student_id"],
    )
    op.drop_index(op.f("ix_attendance_tenant_id"), table_name="attendance")
    op.drop_constraint("fk_attendance_tenant_id", "attendance", type_="foreignkey")
    op.drop_column("attendance", "tenant_id")

    # class_teachers
    op.drop_constraint("uq_class_teacher_tenant", "class_teachers", type_="unique")
    op.create_unique_constraint("uq_class_teacher", "class_teachers", ["class_id", "teacher_id"])
    op.drop_index(op.f("ix_class_teachers_tenant_id"), table_name="class_teachers")
    op.drop_constraint("fk_class_teachers_tenant_id", "class_teachers", type_="foreignkey")
    op.drop_column("class_teachers", "tenant_id")

    # students
    op.drop_constraint("uq_students_user_id_tenant", "students", type_="unique")
    op.drop_constraint("uq_students_admission_number_tenant", "students", type_="unique")
    op.create_index(op.f("ix_students_admission_number"), "students", ["admission_number"], unique=True)
    op.create_unique_constraint("students_user_id_key", "students", ["user_id"])
    op.drop_index(op.f("ix_students_tenant_id"), table_name="students")
    op.drop_constraint("fk_students_tenant_id", "students", type_="foreignkey")
    op.drop_column("students", "tenant_id")

    # teachers
    op.drop_constraint("uq_teachers_user_id_tenant", "teachers", type_="unique")
    op.drop_constraint("uq_teachers_employee_id_tenant", "teachers", type_="unique")
    op.create_index(op.f("ix_teachers_employee_id"), "teachers", ["employee_id"], unique=True)
    op.create_unique_constraint("teachers_user_id_key", "teachers", ["user_id"])
    op.drop_index(op.f("ix_teachers_tenant_id"), table_name="teachers")
    op.drop_constraint("fk_teachers_tenant_id", "teachers", type_="foreignkey")
    op.drop_column("teachers", "tenant_id")

    # classes
    op.drop_constraint("uq_class_section_year_tenant", "classes", type_="unique")
    op.create_unique_constraint(
        "uq_class_section_year",
        "classes",
        ["name", "section", "academic_year"],
    )
    op.drop_index(op.f("ix_classes_tenant_id"), table_name="classes")
    op.drop_constraint("fk_classes_tenant_id", "classes", type_="foreignkey")
    op.drop_column("classes", "tenant_id")

    # user_roles
    op.drop_constraint("uq_user_role_tenant", "user_roles", type_="unique")
    op.create_unique_constraint("uq_user_role", "user_roles", ["user_id", "role_id"])
    op.drop_index(op.f("ix_user_roles_tenant_id"), table_name="user_roles")
    op.drop_constraint("fk_user_roles_tenant_id", "user_roles", type_="foreignkey")
    op.drop_column("user_roles", "tenant_id")

    # role_permissions
    op.drop_constraint("uq_role_permission_tenant", "role_permissions", type_="unique")
    op.create_unique_constraint(
        "uq_role_permission",
        "role_permissions",
        ["role_id", "permission_id"],
    )
    op.drop_index(op.f("ix_role_permissions_tenant_id"), table_name="role_permissions")
    op.drop_constraint("fk_role_permissions_tenant_id", "role_permissions", type_="foreignkey")
    op.drop_column("role_permissions", "tenant_id")

    # roles
    op.drop_index("uq_roles_name_tenant", table_name="roles")
    op.create_index(op.f("ix_roles_name"), "roles", ["name"], unique=True)
    op.drop_index(op.f("ix_roles_tenant_id"), table_name="roles")
    op.drop_constraint("fk_roles_tenant_id", "roles", type_="foreignkey")
    op.drop_column("roles", "tenant_id")

    # sessions
    op.drop_index(op.f("ix_sessions_tenant_id"), table_name="sessions")
    op.drop_constraint("fk_sessions_tenant_id", "sessions", type_="foreignkey")
    op.drop_column("sessions", "tenant_id")

    # users
    op.drop_index("uq_users_email_tenant", table_name="users")
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.drop_index(op.f("ix_users_tenant_id"), table_name="users")
    op.drop_constraint("fk_users_tenant_id", "users", type_="foreignkey")
    op.drop_column("users", "tenant_id")

    # tenants
    op.drop_index(op.f("ix_tenants_subdomain"), table_name="tenants")
    op.drop_index(op.f("ix_tenants_status"), table_name="tenants")
    op.drop_table("tenants")
