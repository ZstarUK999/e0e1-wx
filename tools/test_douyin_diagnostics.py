import json
import logging
import time
from package.plugin_manager.douyin import DouyinCache,atomic_json

def test_connection_diagnostic_distinguishes_mismatch_and_stale_without_logging_token(tmp_path,caplog):
    cache=DouyinCache(tmp_path/'settings',tmp_path/'cache')
    cache.build='expected-build';cache.version='0.1.71'
    atomic_json(cache.mailbox('state'),{'token':'sensitive-secret','build':'actual-build','at':time.time()*1000})
    caplog.set_level(logging.INFO,logger='plugin_manager.douyin')
    cache.log_diagnostics();cache.log_diagnostics()
    assert len(caplog.records)==1
    assert 'token_mismatch' in caplog.text and 'sensitive-secret' not in caplog.text and cache.token not in caplog.text
    atomic_json(cache.mailbox('state'),{'token':cache.token,'build':'actual-build','at':time.time()*1000})
    cache.log_diagnostics();assert 'build_mismatch_need_reenter' in caplog.text
    atomic_json(cache.mailbox('state'),{'token':cache.token,'build':cache.build,'appid':'tt310e47b3ae06acc002','protocol':'static-v1','at':time.time()*1000-20000})
    cache.log_diagnostics();assert 'stale_heartbeat' in caplog.text


def test_connection_diagnostics_tolerates_corrupt_and_missing_state(tmp_path,caplog):
    cache=DouyinCache(tmp_path/'settings',tmp_path/'cache')
    caplog.set_level(logging.INFO,logger='plugin_manager.douyin')
    cache.log_diagnostics();assert 'FileNotFoundError' in caplog.text
    cache.mailbox('state').parent.mkdir(parents=True,exist_ok=True)
    cache.mailbox('state').write_text('{')
    cache.log_diagnostics();assert 'JSONDecodeError' in caplog.text
    cache.mailbox('state').write_text('{"at": "NaN"}')
    cache.log_diagnostics()
