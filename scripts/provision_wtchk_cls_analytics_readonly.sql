-- Provision the dedicated Cube read-only role for the wtchk_cls database.
--
-- Run this file with psql as a PostgreSQL administrator while connected to
-- wtchk_cls. The \password command prompts securely and does not place the new
-- password in this file or your shell history.
--
-- Step 1 - log in to the wtchk_cls database from the repository root:
--   psql --host <postgres-host> --username postgres --dbname wtchk_cls
--
-- Step 2 - run this file from the psql prompt:
--   \i scripts/provision_wtchk_cls_analytics_readonly.sql

-- Clear any unfinished statement that was already buffered at the psql prompt.
\r
\set ON_ERROR_STOP on

-- Fail before creating/changing the role when migration 0009 has not created
-- the governed semantic views and safe JSON helper functions.
DO $preflight$
DECLARE
    missing_objects text;
BEGIN
    SELECT string_agg(required.name, ', ' ORDER BY required.name)
    INTO missing_objects
    FROM (
        VALUES
            ('public.analytics_survey_facts',
             to_regclass('public.analytics_survey_facts') IS NOT NULL),
            ('public.analytics_survey_topics',
             to_regclass('public.analytics_survey_topics') IS NOT NULL),
            ('public.analytics_survey_departments',
             to_regclass('public.analytics_survey_departments') IS NOT NULL),
            ('public.analytics_survey_keywords',
             to_regclass('public.analytics_survey_keywords') IS NOT NULL),
            ('public.analytics_normalize_raw_row(json)',
             to_regprocedure('public.analytics_normalize_raw_row(json)') IS NOT NULL),
            ('public.analytics_raw_value(json,text)',
             to_regprocedure('public.analytics_raw_value(json,text)') IS NOT NULL),
            ('public.analytics_raw_number(json,text)',
             to_regprocedure('public.analytics_raw_number(json,text)') IS NOT NULL),
            ('public.analytics_raw_number_invalid(json,text)',
             to_regprocedure('public.analytics_raw_number_invalid(json,text)') IS NOT NULL),
            ('public.analytics_raw_boolean(json,text)',
             to_regprocedure('public.analytics_raw_boolean(json,text)') IS NOT NULL),
            ('public.analytics_raw_date(json,text)',
             to_regprocedure('public.analytics_raw_date(json,text)') IS NOT NULL),
            ('public.analytics_raw_time(json,text)',
             to_regprocedure('public.analytics_raw_time(json,text)') IS NOT NULL),
            ('public.analytics_raw_timestamp(json,text)',
             to_regprocedure('public.analytics_raw_timestamp(json,text)') IS NOT NULL)
    ) AS required(name, present)
    WHERE NOT required.present;

    IF missing_objects IS NOT NULL THEN
        RAISE EXCEPTION
            'Analytics migration 0009 must run before role provisioning. Missing: %',
            missing_objects
            USING HINT = 'Upgrade the backend database to Alembic head, then rerun this file.';
    END IF;
END
$preflight$;

DO $provision$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'wtchk_cls_analytics'
    ) THEN
        CREATE ROLE wtchk_cls_analytics
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT
            NOREPLICATION
            NOBYPASSRLS;
    ELSE
        ALTER ROLE wtchk_cls_analytics
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT
            NOREPLICATION
            NOBYPASSRLS;
    END IF;
END
$provision$;

-- Prompt twice for the password assigned to
-- WTCHK_CLS_ANALYTICS_DB_PASSWORD in deploy/profile/wtchk_cls.env.
\password wtchk_cls_analytics

GRANT CONNECT ON DATABASE wtchk_cls TO wtchk_cls_analytics;
GRANT USAGE ON SCHEMA public TO wtchk_cls_analytics;
REVOKE CREATE ON SCHEMA public FROM wtchk_cls_analytics;

-- Remove direct access left by any previous use of this role, then grant only
-- the four governed semantic grains.
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public
    FROM wtchk_cls_analytics;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public
    FROM wtchk_cls_analytics;

GRANT SELECT ON TABLE
    public.analytics_survey_facts,
    public.analytics_survey_topics,
    public.analytics_survey_departments,
    public.analytics_survey_keywords
TO wtchk_cls_analytics;

GRANT EXECUTE ON FUNCTION public.analytics_normalize_raw_row(json)
    TO wtchk_cls_analytics;
GRANT EXECUTE ON FUNCTION public.analytics_raw_value(json, text)
    TO wtchk_cls_analytics;
GRANT EXECUTE ON FUNCTION public.analytics_raw_number(json, text)
    TO wtchk_cls_analytics;
GRANT EXECUTE ON FUNCTION public.analytics_raw_number_invalid(json, text)
    TO wtchk_cls_analytics;
GRANT EXECUTE ON FUNCTION public.analytics_raw_boolean(json, text)
    TO wtchk_cls_analytics;
GRANT EXECUTE ON FUNCTION public.analytics_raw_date(json, text)
    TO wtchk_cls_analytics;
GRANT EXECUTE ON FUNCTION public.analytics_raw_time(json, text)
    TO wtchk_cls_analytics;
GRANT EXECUTE ON FUNCTION public.analytics_raw_timestamp(json, text)
    TO wtchk_cls_analytics;

ALTER ROLE wtchk_cls_analytics
    SET default_transaction_read_only TO on;
ALTER ROLE wtchk_cls_analytics
    SET statement_timeout TO '300s';
ALTER ROLE wtchk_cls_analytics
    SET search_path TO public, pg_catalog;

-- Verify the role flags and direct relation grants without displaying secrets.
SELECT
    rolname,
    rolsuper,
    rolcreatedb,
    rolcreaterole,
    rolinherit,
    rolreplication,
    rolbypassrls
FROM pg_roles
WHERE rolname = 'wtchk_cls_analytics';

SELECT
    table_schema,
    table_name,
    privilege_type
FROM information_schema.role_table_grants
WHERE grantee = 'wtchk_cls_analytics'
ORDER BY table_schema, table_name, privilege_type;
