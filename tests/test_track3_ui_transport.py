"""The route fixture must accept real multipart audio without UTF-8 decoding it."""
import importlib.util
from pathlib import Path


def test_browser_fixture_handles_binary_wake_without_accessing_text_body():
    spec=importlib.util.spec_from_file_location('track3_browser_fixture',Path(__file__).parent/'ui_track3/fixtures.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    class Request:
        url='http://fixture.invalid/api/meet/voice/wake'
        method='POST'
        headers={'content-type':'multipart/form-data; boundary=synthetic'}
        post_data_buffer=b'RIFF\xff\xee\x00\x80'
        @property
        def post_data(self):raise UnicodeDecodeError('utf-8',self.post_data_buffer,4,5,'binary WAV')
        @property
        def post_data_json(self):raise AssertionError('Audio is not JSON')
    class Route:
        request=Request()
        def fulfill(self,**kwargs):self.result=kwargs
    route=Route();api=module.FixtureAPI();api.handle(route)
    assert route.result=={'status':200,'json':{'activated':False,'text':''}}
    assert api.count('/voice/wake')==1
