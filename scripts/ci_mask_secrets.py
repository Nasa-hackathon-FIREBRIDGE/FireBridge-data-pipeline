"""Register generated fixture credentials with the Actions log masker."""
import os
from pathlib import Path

if os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('This command is only for GitHub Actions; it must not print credentials locally.')
for line in Path('.env').read_text().splitlines():
    if '=' not in line or line.startswith('#'):continue
    key,value=line.split('=',1)
    if value and any(word in key for word in ('PASSWORD','SECRET','KEY','TOKEN')):
        print('::add-mask::'+value.strip('"\''))
