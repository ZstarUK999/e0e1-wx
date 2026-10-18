"""Release packaging must fail before distributing a client without gRPC."""
from pathlib import Path
import importlib.util
import pytest

spec=importlib.util.spec_from_file_location('build_release_test',Path(__file__).with_name('build_exe.py'))
build=importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def test_release_collects_grpc_and_generated_stubs():
    kwargs=dict(windowed=True,onefile=False,exclude_frida=False,keep_cryptography=False,features_file=None,build_file=Path('build.json'),certs_dir=None)
    release=build.build_command(**kwargs,exclude_grpc=False)
    assert release[release.index('--collect-all')+1]=='grpc'
    assert release[release.index('--collect-submodules')+1]=='google.protobuf'
    assert 'package.plugin_manager.grpc_stub.plugin_pb2_grpc' in release
    debug=build.build_command(**kwargs,exclude_grpc=True)
    assert '--collect-all' not in debug
    assert debug[debug.index('grpc')-1]=='--exclude-module'


def test_release_preflight_rejects_missing_grpc(monkeypatch):
    def missing(name):
        raise ModuleNotFoundError("No module named 'grpc'")
    monkeypatch.setattr(build.importlib,'import_module',missing)
    with pytest.raises(RuntimeError,match='requirements.txt'):
        build.check_release_dependencies()
