-- Relocate references, not object contents or scientific release membership.
UPDATE firebridge.assets SET storage_uri=regexp_replace(storage_uri,'^.*(/objects/)','objects/')
 WHERE storage_uri LIKE '%/objects/%';
UPDATE firebridge.data_partitions SET
 storage_uri=regexp_replace(storage_uri,'^.*(/objects/)','objects/'),
 input_manifest_uri=regexp_replace(input_manifest_uri,'^.*(/objects/)','objects/');
UPDATE firebridge.pipeline_runs SET
 input_manifest_uri=regexp_replace(input_manifest_uri,'^.*(/objects/)','objects/'),
 output_manifest_uri=regexp_replace(output_manifest_uri,'^.*(/objects/)','objects/');
UPDATE firebridge.data_releases SET
 manifest_uri=regexp_replace(manifest_uri,'^.*(/objects/)','objects/'),
 validation_report_uri=regexp_replace(validation_report_uri,'^.*(/objects/)','objects/');
UPDATE firebridge.release_changes SET diff_manifest_uri=regexp_replace(diff_manifest_uri,'^.*(/objects/)','objects/');
