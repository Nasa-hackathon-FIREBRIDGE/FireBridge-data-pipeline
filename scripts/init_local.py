"""Create private local development credentials without displaying their values."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    print(".env already exists; left unchanged.")
else:
    text = (root / ".env.example").read_text()
    text = text.replace("replace-with-random-password", secrets.token_hex(24))
    text = text.replace("replace-with-another-random-password", secrets.token_hex(24))
    with target.open("x") as f:
        f.write(text)
    target.chmod(0o600)
    print("Created private .env with random local database passwords.")
