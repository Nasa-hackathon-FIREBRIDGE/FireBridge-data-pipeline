from contextlib import contextmanager
import hashlib
from importlib.resources import files
import os
import psycopg
from psycopg.rows import dict_row
from psycopg import sql


@contextmanager
def connect(settings):
    with psycopg.connect(settings.database_url, row_factory=dict_row,
                         options="-c timezone=UTC -c search_path=firebridge,public",
                         connect_timeout=10) as conn:
        yield conn


def migrate(settings):
    with connect(settings) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('firebridge:migrate',0))")
        conn.execute("CREATE TABLE IF NOT EXISTS public.firebridge_migrations (name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
        for path in sorted(files("firebridge").joinpath("migrations").iterdir(), key=lambda p: p.name):
            if not path.name.endswith(".sql"):
                continue
            body = path.read_text()
            sha = hashlib.sha256(body.encode()).hexdigest()
            old = conn.execute("SELECT sha256 FROM public.firebridge_migrations WHERE name=%s", (path.name,)).fetchone()
            if old:
                if old["sha256"] != sha:
                    raise ValueError(f"Applied migration changed: {path.name}; add a new migration")
                continue
            conn.execute(body, prepare=False)
            conn.execute("INSERT INTO public.firebridge_migrations(name,sha256) VALUES (%s,%s)", (path.name, sha))
        password = os.getenv("FIREBRIDGE_READER_PASSWORD")
        if password:
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='firebridge_reader'").fetchone():
                conn.execute(sql.SQL("CREATE ROLE firebridge_reader LOGIN PASSWORD {}").format(sql.Literal(password)))
            # Only the curated contract is granted. No provider tokens/worker writes.
            conn.execute("GRANT USAGE ON SCHEMA serving TO firebridge_reader")
            conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA serving TO firebridge_reader")
        transform_password = os.getenv('FIREBRIDGE_DBT_PASSWORD')
        if transform_password:
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='firebridge_transform'").fetchone():
                conn.execute(sql.SQL('CREATE ROLE firebridge_transform LOGIN PASSWORD {}').format(sql.Literal(transform_password)))
            conn.execute('GRANT USAGE ON SCHEMA serving TO firebridge_transform')
            conn.execute('GRANT SELECT ON ALL TABLES IN SCHEMA serving TO firebridge_transform')
