-- Finishing enumeration must not revoke operator authorization or prevent gap repair.
ALTER TABLE firebridge.ingestion_subscriptions ADD COLUMN planning_complete boolean NOT NULL DEFAULT false;
CREATE VIEW serving.subscription_planning AS
 SELECT id,feed_id,scope_key,mode,enabled,planning_complete,history_start,fixed_end_exclusive
 FROM firebridge.ingestion_subscriptions;
