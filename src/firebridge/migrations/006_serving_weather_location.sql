CREATE OR REPLACE VIEW serving.weather AS SELECT rp.release_id,w.id,w.source_id,w.variable,w.unit,w.valid_start,
 w.valid_end,w.issued_at,w.available_at,w.data_kind,w.statistic,w.value,w.quality_status,
 w.asset_id,w.derivation,l.support_kind,l.geom,ST_X(l.geom) AS longitude,ST_Y(l.geom) AS latitude,
 l.metadata AS location_metadata,p.support_spec,w.location_id
 FROM firebridge.release_partitions rp JOIN firebridge.data_releases r ON r.id=rp.release_id
 JOIN firebridge.partition_weather_values pw ON pw.partition_id=rp.partition_id
 JOIN firebridge.data_partitions p ON p.id=rp.partition_id JOIN firebridge.weather_values w ON w.id=pw.weather_value_id
 JOIN firebridge.weather_locations l ON l.id=w.location_id WHERE r.status='published';
