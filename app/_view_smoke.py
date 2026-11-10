import sys
sys.path.insert(0, 'app')


class MW:
    transcribe_route = ''
    tmap = None
    edit_roll = None

    def _open_editor(self):
        pass


from transcribe_view import TranscribeView
tv = TranscribeView(MW())
assert not hasattr(tv, 'b_route_tk'), '路线卡应已删除'
assert not hasattr(tv, 'b_route_ms'), '路线卡应已删除'
assert hasattr(tv, 'b_audio'), '音频按钮应存在'
assert hasattr(tv, 'rb_sw'), '分离单选应存在'
print('VIEW OK')
