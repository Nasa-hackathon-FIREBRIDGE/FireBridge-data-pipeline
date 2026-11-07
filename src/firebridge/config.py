from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_dir: Path
    firms_key: str = ""
    earthdata_token: str = ""
    max_bytes: int = 256 * 1024 * 1024
    firms_budget: int = 60
    poll_seconds: int = 30

    @classmethod
    def load(cls):
        load_dotenv(Path.cwd() / ".env", override=False)
        url = os.getenv("DATABASE_URL", "")
        if not url:
            raise ValueError("DATABASE_URL missing; run python scripts/init_local.py first")
        return cls(url, Path(os.getenv("FIREBRIDGE_DATA_DIR", "data/platform")).resolve(),
                   os.getenv("FIRMS_MAP_KEY", ""), os.getenv("EARTHDATA_TOKEN", ""),
                   int(os.getenv("FIREBRIDGE_MAX_DOWNLOAD_MB", "256")) * 1024 * 1024,
                   int(os.getenv("FIREBRIDGE_FIRMS_REQUESTS_PER_10_MIN", "60")),
                   int(os.getenv("FIREBRIDGE_POLL_SECONDS", "30")))
