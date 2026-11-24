"""Row Level Security on every table (plan section 5).

Signed-in users may only SELECT rows of businesses they belong to. No customer write
policies exist: all writes go through FastAPI with explicit tenant scoping. Platform
tables (webhook_events, audit_logs, admin_users) have RLS on and no customer policy.

On Supabase the `auth` schema, `auth.uid()` and the `anon`/`authenticated` roles already
exist. For local development and tests this migration creates minimal stand-ins only when
they are missing, so it is safe to run on Supabase unchanged.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TENANT_TABLES = [
    "business_hours",
    "holiday_closures",
    "services",
    "service_areas",
    "assistants",
    "phone_lines",
    "calls",
    "leads",
    "lead_events",
]
# The backend connects as the table owner (Supabase `postgres`), which bypasses RLS;
# isolation for backend queries is enforced by explicit business_id scoping.
PLATFORM_TABLES = ["webhook_events", "audit_logs", "admin_users"]
ALL = ["businesses", "business_members", *TENANT_TABLES, *PLATFORM_TABLES, "alembic_version"]


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            CREATE ROLE anon NOLOGIN;
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            CREATE ROLE authenticated NOLOGIN;
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'auth') THEN
            CREATE SCHEMA auth;
            CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $f$
              SELECT nullif(
                coalesce(
                  current_setting('request.jwt.claim.sub', true),
                  (current_setting('request.jwt.claims', true)::jsonb ->> 'sub')
                ), ''
              )::uuid
            $f$;
            GRANT USAGE ON SCHEMA auth TO anon, authenticated;
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.bileksa_member_business_ids()
        RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = ''
        AS $$
          SELECT business_id FROM public.business_members WHERE user_id = auth.uid()
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.bileksa_member_business_ids() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.bileksa_member_business_ids() TO authenticated")
    op.execute("GRANT USAGE ON SCHEMA public TO authenticated")
    for table in ALL:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON public.{table} FROM anon")
        op.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.{table} FROM authenticated")
    for table in ["businesses", "business_members", *TENANT_TABLES]:
        op.execute(f"GRANT SELECT ON public.{table} TO authenticated")
    op.execute(
        "CREATE POLICY member_read ON public.businesses FOR SELECT TO authenticated "
        "USING (id IN (SELECT public.bileksa_member_business_ids()))"
    )
    op.execute(
        "CREATE POLICY member_read ON public.business_members FOR SELECT TO authenticated "
        "USING (user_id = auth.uid())"
    )
    for table in TENANT_TABLES:
        op.execute(
            f"CREATE POLICY member_read ON public.{table} FOR SELECT TO authenticated "
            "USING (business_id IN (SELECT public.bileksa_member_business_ids()))"
        )


def downgrade() -> None:
    for table in ["businesses", "business_members", *TENANT_TABLES]:
        op.execute(f"DROP POLICY IF EXISTS member_read ON public.{table}")
    for table in ALL:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS public.bileksa_member_business_ids()")
