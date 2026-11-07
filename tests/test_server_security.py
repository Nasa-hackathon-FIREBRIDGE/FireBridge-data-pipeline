import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('secure_vps',Path(__file__).resolve().parents[1]/'scripts/secure_vps.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_admin_policy_preserves_private_tunnels_and_requires_keys():
    text=module.ssh_policy('dataadmin')
    values=dict(line.split(' ',1) for line in text.splitlines() if line and not line.startswith('#'))
    assert values['PermitRootLogin']=='no'
    assert values['AuthenticationMethods']=='publickey'
    assert values['PasswordAuthentication']=='no'
    assert values['KbdInteractiveAuthentication']=='no'
    assert values['AllowUsers']=='dataadmin'
    assert values['AllowTcpForwarding']=='local'


@pytest.mark.parametrize('name',['root','bad name','admin\nPermitRootLogin yes','-oOption',''])
def test_policy_rejects_root_and_config_injection(name):
    with pytest.raises(ValueError):module.ssh_policy(name)


def test_transition_retains_root_key_access_and_still_rejects_passwords():
    text=module.ssh_policy('dataadmin',keep_root_key=True)
    assert 'PermitRootLogin prohibit-password\n' in text
    assert 'AllowUsers dataadmin root\n' in text
    assert 'AuthenticationMethods publickey\n' in text
    assert 'PasswordAuthentication no\n' in text


def test_final_policy_preserves_restricted_ci_account():
    text=module.ssh_policy('dataadmin',allow_deploy=True)
    assert 'AllowUsers dataadmin firebridge-deploy\n' in text
    assert 'PermitRootLogin no\n' in text
