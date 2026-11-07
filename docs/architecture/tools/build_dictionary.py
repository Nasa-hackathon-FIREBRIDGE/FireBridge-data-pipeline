"""Regenerate documentation and static validation, without connecting to a database.

Requires pglast==8.7 in a disposable environment. Run from any directory.
SQL is the source for columns/constraints; column_notes.json supplies explanations.
"""
from pathlib import Path
import hashlib
import json
import re
from pglast import ast, parse_sql
from pglast.stream import RawStream

ROOT = Path(__file__).resolve().parents[1]
def render(node):
    return RawStream()(node)
def names(items):
    return tuple(x.sval for x in (items or ()))
sql=(ROOT/'schema.sql').read_text()
statements=parse_sql(sql)
tables={s.stmt.relation.relname:s.stmt for s in statements if isinstance(s.stmt,ast.CreateStmt)}
notes=json.loads((ROOT/'tools/column_notes.json').read_text())
columns={name:{c.colname:c for c in t.tableElts if isinstance(c,ast.ColumnDef)} for name,t in tables.items()}
cons={name:[] for name in tables}
for name,t in tables.items():
    for el in t.tableElts:
        if isinstance(el,ast.ColumnDef):
            cons[name].extend((c,(el.colname,)) for c in el.constraints or ())
        else: cons[name].append((el,None))
for s in statements:
    if isinstance(s.stmt,ast.AlterTableStmt):
        for cmd in s.stmt.cmds:
            if isinstance(cmd.def_,ast.Constraint): cons[s.stmt.relation.relname].append((cmd.def_,None))
errors=[]
keys={n:[inline or names(c.keys) for c,inline in cs if c.contype.name in ('CONSTR_PRIMARY','CONSTR_UNIQUE')] for n,cs in cons.items()}
foreign_keys=0
for n,cs in cons.items():
    for c,inline in cs:
        if c.contype.name!='CONSTR_FOREIGN': continue
        foreign_keys+=1
        target=c.pktable.relname
        local=inline or names(c.fk_attrs); remote=names(c.pk_attrs)
        if target not in tables: errors.append(f'{n}: unknown FK table {target}'); continue
        if len(local)!=len(remote): errors.append(f'{n}: FK arity')
        if remote not in keys[target]: errors.append(f'{n}: FK target not unique: {target}.{remote}')
        for a,b in zip(local,remote):
            if a not in columns[n] or b not in columns[target]: errors.append(f'{n}: missing FK column {a}/{b}')
            elif render(columns[n][a].typeName)!=render(columns[target][b].typeName): errors.append(f'{n}.{a}: FK type mismatch')
indexes=[s.stmt for s in statements if isinstance(s.stmt,ast.IndexStmt)]
for idx in indexes:
    n=idx.relation.relname
    if n not in tables: errors.append(f'Index table missing: {n}')
    for field in idx.indexParams:
        if field.name and field.name not in columns[n]:errors.append(f'Index column missing: {n}.{field.name}')
assert set(tables)==set(notes), {'undocumented':list(set(tables)-set(notes)),'stale':list(set(notes)-set(tables))}
lines=[f'''# FIREBRIDGE database dictionary

**Proposed schema v2 — October 24, 2026.** Generated from [schema.sql](schema.sql) and versioned column explanations. The {len(tables)} tables below specify each row's meaning, every column/type, required values, defaults, keys and constraints. No database has been created by this design.

Start with [the data-platform overview](DATA_PLATFORM.md), then [pipelines](PIPELINES.md) and [API contracts](API.md). Small operational and join tables are included in the full count; they are not separate services.

`uuid` is an application-generated ID. `timestamptz` is an absolute timestamp handled in UTC. `jsonb` fields must be validated against versioned Pydantic/JSON contracts. Geometry uses WGS84 longitude/latitude (SRID 4326), while metric areas are calculated in the documented equal-area projection. Null is unavailable/not-applicable. Required means NOT NULL or primary-key membership; conditional checks may impose additional requirements.

This is a schema for an empty development database, not an in-place migration from the previous draft. Use Alembic and data migration planning when an actual deployment exists. Large files/global rows remain outside PostgreSQL; serving completeness must be verified.
''']
for num,(n,t) in enumerate(tables.items(),1):
    assert set(columns[n])==set(notes[n]['columns']), (n,set(columns[n])^set(notes[n]['columns']))
    primary=set()
    for c,inline in cons[n]:
        if c.contype.name=='CONSTR_PRIMARY': primary.update(inline or names(c.keys))
    lines += [f'## {num}. `{n}`','',notes[n]['grain'],'','| Column | SQL type | Required | Default / generation | Meaning |','|---|---|---|---|---|']
    for name,col in columns[n].items():
        types={c.contype.name for c in col.constraints or ()}
        required='Yes' if name in primary or 'CONSTR_NOTNULL' in types else 'No'
        defaults=[render(c) for c in col.constraints or () if c.contype.name in ('CONSTR_DEFAULT','CONSTR_IDENTITY','CONSTR_GENERATED')]
        default='; '.join(defaults) or '—'
        default=default.replace('|','\\|').replace('\n',' ')
        lines.append(f'| `{name}` | `{render(col.typeName)}` | {required} | {default} | {notes[n]["columns"][name]} |')
    lines += ['','**Keys and value rules**','']
    for c,inline in cons[n]:
        if c.contype.name in ('CONSTR_DEFAULT','CONSTR_NOTNULL','CONSTR_IDENTITY','CONSTR_GENERATED'):continue
        prefix=f'`{inline[0]}`: ' if inline else ''
        lines.append('- '+prefix+'`'+render(c).replace('\n',' ')+'`')
    lines.append('')
lines += [(ROOT/'tools/publication_checks.md').read_text()]
(ROOT/'DATABASE.md').write_text('\n'.join(lines))
query_statements=parse_sql((ROOT/'query_patterns.sql').read_text())
endpoints=json.loads((ROOT/'endpoint_catalog.json').read_text())['endpoints']
seen=set()
api=(ROOT/'API.md').read_text()
for e in endpoints:
    key=(e['method'],e['path'])
    if key in seen:errors.append(f'Duplicate endpoint {key}')
    seen.add(key)
    for n in e['reads']+e['writes']:
        if n not in tables:errors.append(f'{key}: unknown table {n}')
    if f"**{e['section']}. `{e['method']} {e['path']}`" not in api:errors.append(f'Missing detailed endpoint section {key}')
for p in [ROOT/'README.md',ROOT/'DATA_PLATFORM.md',ROOT/'DATABASE.md',ROOT/'PIPELINES.md',ROOT/'API.md',ROOT/'SOURCES.md',ROOT.parents[1]/'README.md']:
    for link in re.findall(r'(?<!!)\[[^\]]*\]\(([^)]+)\)',p.read_text()):
        if '://' in link or link.startswith('#'):continue
        if not (p.parent/link.split('#')[0]).exists():errors.append(f'Broken local link {p.name}: {link}')
report={'design_date':'2026-10-24','design_version':2,'checker':'pglast 8.7 PostgreSQL syntax parser plus AST and contract checks','sql_parse':'passed','statement_count':len(statements),'table_count':len(tables),'column_count':sum(len(c) for c in columns.values()),'foreign_key_count':foreign_keys,'index_count':len(indexes),'query_pattern_parse':'passed','query_pattern_statement_count':len(query_statements),'endpoint_contract_count':len(endpoints),'foreign_key_table_column_type_and_unique_target_checks':'passed' if not errors else 'see_errors','dictionary_column_documentation':'complete','endpoint_table_references_and_documentation':'passed' if not errors else 'see_errors','local_document_links':'passed' if not errors else 'see_errors','schema_sha256':hashlib.sha256(sql.encode()).hexdigest(),'database_execution':'not_run','postgis_runtime_validation':'not_run','source_api_authenticated_calls':'not_run','scheduler_created':False,'errors':errors}
(ROOT/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
assert not errors, errors
