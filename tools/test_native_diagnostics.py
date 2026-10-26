import faulthandler

from package.plugin_manager.native_diagnostics import checkpoint, set_stream


def test_checkpoint_is_immediately_visible_and_can_include_thread_stack(tmp_path):
    path=tmp_path/'native.log'
    with path.open('a',encoding='utf-8') as stream:
        set_stream(stream)
        try:
            checkpoint('render-begin player=123')
            assert 'render-begin player=123' in path.read_text(encoding='utf-8')
            faulthandler.dump_traceback(file=stream,all_threads=True)
            text=path.read_text(encoding='utf-8')
            assert 'test_native_diagnostics.py' in text and 'thread=' in text
        finally:
            set_stream(None)
    checkpoint('disabled diagnostics must be harmless')
