from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
from psycopg.types.json import Jsonb
from .util import uid, canonical


@dataclass(frozen=True)
class Object:
    path: Path
    sha256: str
    size: int

    @property
    def uri(self):
        return str(Path('objects') / self.sha256[:2] / self.path.name)


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, chunks, suffix=".bin"):
        staging = self.root / "staging"
        staging.mkdir(exist_ok=True)
        fd, name = tempfile.mkstemp(dir=staging)
        sha = hashlib.sha256(); size = 0
        try:
            with os.fdopen(fd, "wb") as f:
                for chunk in chunks:
                    sha.update(chunk); size += len(chunk); f.write(chunk)
                f.flush(); os.fsync(f.fileno())
            checksum = sha.hexdigest()
            path = self.root / "objects" / checksum[:2] / (checksum + suffix)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Never replace a finalized object. Parallel writers have identical bytes.
            try:
                os.link(name, path)
            except FileExistsError:
                if path.stat().st_size != size:
                    raise ValueError("Content-addressed object size mismatch")
            return Object(path, checksum, size)
        finally:
            Path(name).unlink(missing_ok=True)

    def file(self, path):
        with Path(path).open("rb") as f:
            return self.put(iter(lambda: f.read(8 * 1024 * 1024), b""), Path(path).suffix)

    def json(self, value):
        return self.put([canonical(value).encode()], ".json")

    def resolve(self, uri):
        path=Path(uri)
        if path.is_absolute() and '/objects/' in str(path):
            # Read original immutable manifests written before portable URIs were introduced.
            path=Path('objects') / str(path).split('/objects/',1)[1]
        resolved=(self.root / path).resolve()
        if not resolved.is_relative_to(self.root.resolve()) or '..' in path.parts:
            raise ValueError('Object URI outside configured storage root')
        return resolved


def asset(conn, obj, source, native_key, source_url, metadata=None, start=None, end=None):
    asset_id = uid([source,native_key,obj.sha256])
    conn.execute("""INSERT INTO assets(id,source_id,native_key,revision,source_url,storage_uri,sha256,byte_size,
      time_start,time_end,retrieved_at,validation_status,metadata)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),'accepted',%s) ON CONFLICT DO NOTHING""",
      (asset_id,source,native_key,obj.sha256,source_url,obj.uri,obj.sha256,obj.size,start,end,Jsonb(metadata or {})))
    return asset_id
