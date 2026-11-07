import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest

spec=importlib.util.spec_from_file_location('cd_gateway',Path(__file__).resolve().parents[1]/'deploy/cd_gateway.py')
cd=importlib.util.module_from_spec(spec);spec.loader.exec_module(cd)
REV='a'*40


@pytest.mark.parametrize('command',['status',f'activate {REV}',f'rollback {REV}',f'source {REV} '+('b'*64),f'image {REV} '+('c'*64)])
def test_restricted_protocol_accepts_expected_commands(command):
    assert cd.parse_command(command)==command.split()


@pytest.mark.parametrize('command',['sh','bash -c id','status; id','activate main',f'activate {REV};id',f'activate {REV} extra',f'image {REV} ../../passwd'])
def test_restricted_protocol_rejects_shell_commands_and_injection(command):
    with pytest.raises(ValueError):cd.parse_command(command)


@pytest.mark.parametrize('name,kind',[('../escape','file'),('/etc/shadow','file'),('src/link','symlink'),
    ('src/hard','hardlink'),('.env','file'),('deploy/server-profile','file'),('data/token','file'),
    ('scripts/.env.private','file'),('unexpected.py','file')])
def test_source_archive_rejects_unsafe_paths_links_and_secrets(name,kind):
    member=tarfile.TarInfo(name)
    if kind=='symlink':member.type=tarfile.SYMTYPE;member.linkname='/etc/shadow'
    if kind=='hardlink':member.type=tarfile.LNKTYPE;member.linkname='/etc/shadow'
    with pytest.raises(ValueError):cd.validate_members([member])


def fixture_tar():
    out=io.BytesIO()
    with tarfile.open(fileobj=out,mode='w:gz') as t:
        for name in ('compose.yaml','compose.airflow.yaml','compose.contabo.yaml','compose.release.yaml','scripts/init_server.py'):
            body=b'# fixture\n';member=tarfile.TarInfo(name);member.size=len(body);t.addfile(member,io.BytesIO(body))
    return out.getvalue()


def test_checksum_failure_cannot_publish_source(tmp_path,monkeypatch):
    monkeypatch.setattr(cd,'ROOT',tmp_path);monkeypatch.setattr(cd,'RESERVE',0)
    (tmp_path/'inbox').mkdir()
    with pytest.raises(ValueError,match='checksum'):
        cd.receive('source',REV,'b'*64,io.BytesIO(fixture_tar()))
    assert not list((tmp_path/'inbox').glob('*'))


def test_release_layout_links_shared_state_and_rejects_changed_image(tmp_path,monkeypatch):
    monkeypatch.setattr(cd,'ROOT',tmp_path);monkeypatch.setattr(cd,'SHARED',tmp_path/'shared')
    monkeypatch.setattr(cd,'RESERVE',0)
    for name in ('inbox','releases','shared'):(tmp_path/name).mkdir()
    payload=fixture_tar()
    cd.receive('source',REV,hashlib.sha256(payload).hexdigest(),io.BytesIO(payload))
    (tmp_path/'inbox'/f'{REV}-image.json').write_text(json.dumps({'image_id':'sha256:fixture'}))
    monkeypatch.setattr(cd,'run',lambda *a,**kw:json.dumps([{'Id':'sha256:fixture'}]))
    release=cd.prepare_release(REV)
    assert (release/'data').is_symlink()
    assert (release/'deploy/server-profile').read_text().strip()=='contabo-plus-6'
    assert not (release/'.env').is_symlink()  # initializer creates first secrets before linking
    monkeypatch.setattr(cd,'run',lambda *a,**kw:json.dumps([{'Id':'sha256:changed'}]))
    with pytest.raises(ValueError,match='changed'):cd.prepare_release(REV)


def test_failed_activation_recovers_previous_code_and_schedules(tmp_path,monkeypatch):
    shared=tmp_path/'shared';(shared/'deployments').mkdir(parents=True)
    (shared/'.env').write_text('fixture')
    previous=tmp_path/('b'*40);previous.mkdir()
    (tmp_path/'current').symlink_to(previous,target_is_directory=True)
    release=tmp_path/REV;release.mkdir()
    monkeypatch.setattr(cd,'ROOT',tmp_path);monkeypatch.setattr(cd,'SHARED',shared);monkeypatch.setattr(cd,'RESERVE',0)
    monkeypatch.setattr(cd,'prepare_release',lambda r:release)
    monkeypatch.setattr(cd,'pause_and_drain',lambda r:['firebridge_analytics'])
    calls=[];restored=[]
    def stack(path,*args,**kw):
        calls.append((path,args))
        if path==release and args[:2]==('run','--rm'):raise RuntimeError('fixture init failure')
    monkeypatch.setattr(cd,'stack',stack);monkeypatch.setattr(cd,'run',lambda *a,**kw:None)
    monkeypatch.setattr(cd,'restore_schedules',restored.append)
    with pytest.raises(RuntimeError,match='previous code'):cd.activate(REV)
    assert (tmp_path/'current').resolve()==previous
    assert any(path==previous and args[0]=='up' for path,args in calls)
    assert restored==[['firebridge_analytics']]


def test_same_revision_failed_rebuild_restores_original_image(tmp_path,monkeypatch):
    shared=tmp_path/'shared';(shared/'deployments').mkdir(parents=True)
    (shared/'.env').write_text('fixture');(tmp_path/'inbox').mkdir()
    (shared/'deployment.json').write_text(json.dumps({'image_id':'sha256:old-working-image'}))
    release=tmp_path/REV;release.mkdir();(tmp_path/'current').symlink_to(release,target_is_directory=True)
    monkeypatch.setattr(cd,'ROOT',tmp_path);monkeypatch.setattr(cd,'SHARED',shared);monkeypatch.setattr(cd,'RESERVE',0)
    monkeypatch.setattr(cd,'prepare_release',lambda r:release)
    monkeypatch.setattr(cd,'pause_and_drain',lambda r:[])
    calls=[]
    def stack(path,*args,**kw):
        if args[:2]==('run','--rm'):raise RuntimeError('fixture failure')
    monkeypatch.setattr(cd,'stack',stack)
    monkeypatch.setattr(cd,'run',lambda args,**kw:calls.append(args))
    monkeypatch.setattr(cd,'restore_schedules',lambda r:None)
    with pytest.raises(RuntimeError,match='previous code'):cd.activate(REV)
    assert ['docker','image','tag','sha256:old-working-image',f'firebridge-airflow:{REV}'] in calls
    assert json.loads((tmp_path/'inbox'/f'{REV}-image.json').read_text())['image_id']=='sha256:old-working-image'
