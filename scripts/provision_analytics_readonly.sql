-- Generic, profile-scoped Cube analytics role provisioning.
-- Run after the profile's Alembic migrations, for example:
--   psql --host <host> --username <admin> --dbname <profile> \
--     -v profile=<profile> -v analytics_role=<profile>_analytics \
--     -f scripts/provision_analytics_readonly.sql
-- psql prompts for the password so no secret is stored in this file.

\if :{?profile}
\else
  \quit 2
\endif
\if :{?analytics_role}
\else
  \quit 2
\endif

SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS', :'analytics_role')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'analytics_role') \gexec
\password :analytics_role

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'analytics_role') \gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'analytics_role') \gexec
SELECT format('REVOKE CREATE ON SCHEMA public FROM %I', :'analytics_role') \gexec
SELECT format('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM %I', :'analytics_role') \gexec
SELECT format('REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM %I', :'analytics_role') \gexec
SELECT format('GRANT SELECT ON TABLE public.analytics_survey_facts, public.analytics_survey_topics, public.analytics_survey_departments, public.analytics_survey_keywords, public.analytics_survey_assignments TO %I', :'analytics_role') \gexec
SELECT format('GRANT EXECUTE ON FUNCTION public.analytics_normalize_raw_row(json), public.analytics_raw_value(json,text), public.analytics_raw_number(json,text), public.analytics_raw_number_invalid(json,text), public.analytics_raw_boolean(json,text), public.analytics_raw_date(json,text), public.analytics_raw_time(json,text), public.analytics_raw_timestamp(json,text) TO %I', :'analytics_role') \gexec
SELECT format('ALTER ROLE %I SET default_transaction_read_only TO on', :'analytics_role') \gexec
SELECT format('ALTER ROLE %I SET statement_timeout TO %L', :'analytics_role', '300s') \gexec
