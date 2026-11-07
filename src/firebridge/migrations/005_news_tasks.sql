ALTER TABLE firebridge.ingest_tasks DROP CONSTRAINT ingest_tasks_kind_check;
ALTER TABLE firebridge.ingest_tasks ADD CONSTRAINT ingest_tasks_kind_check
 CHECK (kind IN ('firms','weather','availability','cmr','news'));
