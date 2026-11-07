"""Parse every shipped Dag without scheduling jobs or calling providers."""
from airflow.dag_processing.dagbag import DagBag
bag=DagBag(dag_folder='/opt/airflow/dags',safe_mode=False)
if bag.import_errors:
    for name,error in bag.import_errors.items():print(name,error)
    raise SystemExit(1)
expected={'firebridge_ingestion','firebridge_analytics','firebridge_health','firebridge_archive_import','firebridge_local_archive_lake','firebridge_full_history_download'}
if set(bag.dags)!=expected:raise RuntimeError('Unexpected Dag inventory')
for dag in bag.dags.values():
    assert dag.catchup is False
print({'dags':sorted(bag.dags),'import_errors':0})
