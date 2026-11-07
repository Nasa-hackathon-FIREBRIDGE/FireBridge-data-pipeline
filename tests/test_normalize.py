import pytest
from firebridge.normalize import normalize,parse_csv
from firebridge.util import days,utc


def native(**changes):
    row=dict(satellite='Terra',latitude='35',longitude='-5',acq_date='2024-01-17',acq_time='39',
             confidence='57',daynight='N',brightness='307.9',bright_t31='294.2',frp='11.8',version='61.03')
    return row|changes


def test_native_semantics_and_hash():
    a=normalize(native(source_row=2),'standard',['Terra'])
    b=normalize(native(source_row=900),'standard',['Terra'])
    assert a['record_sha256']==b['record_sha256']
    assert a['acquired_at'].isoformat()=='2024-01-17T00:39:00+00:00'
    assert a['brightness_bands']['T21_22']['unit']=='K'
    assert a['confidence_scheme']=='MODIS_0_100'


@pytest.mark.parametrize('changes',[{'longitude':'nan'},{'acq_time':'2460'},{'latitude':'91'},
                                   {'confidence':'101'},{'frp':'-1'},{'daynight':'?'},{'sample':'3.5'}])
def test_bad_native_rows_rejected(changes):
    with pytest.raises(ValueError):normalize(native(**changes),'standard',['Terra'])


def test_viirs_and_landsat_stay_distinct():
    v=normalize(native(satellite='N20',confidence='n',version='2.0NRT'),'nrt',['N20'])
    assert 'I4' in v['brightness_bands'] and v['confidence_scheme']=='VIIRS_l_n_h'
    l=normalize(native(satellite='L8',confidence='H',scan='99',track='100',frp=None,brightness=None,bright_t31=None),'nrt',['L8'])
    assert l['scan_km'] is None and l['track_km'] is None
    assert l['native_fields']['scan']=='99' and l['frp_mw'] is None
    legacy=normalize(native(satellite='1',confidence='n',version='2'),'standard',['N20'])
    assert legacy['source_id']=='viirs-noaa20-c2-standard'
    with pytest.raises(ValueError,match='collection'):
        normalize(native(satellite='N20',confidence='n',version='1'),'standard',['N20'])


def test_rt_excluded_standard_stream_guard():
    assert normalize(native(version='61URT'),'nrt',['Terra']) is None
    with pytest.raises(ValueError):normalize(native(version='6.1NRT'),'standard',['Terra'])


def test_empty_csv_vs_html_and_truncation():
    header=b'latitude,longitude,acq_date,acq_time,satellite,confidence,daynight\n'
    assert parse_csv(header,'nrt',['Terra'])==([],0)
    for invalid in [b'<html>login</html>',header+b'35,-5,2024-01-17,0039,Terra\n',b'']:
        with pytest.raises(ValueError):parse_csv(invalid,'nrt',['Terra'])


def test_half_open_boundaries():
    assert len(list(days('2024-01-17','2025-01-18')))==367
    with pytest.raises(ValueError):list(days('2024-01-17T12:00:00','2024-01-18'))
