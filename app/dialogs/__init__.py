# -*- coding: utf-8 -*-
"""对话框包 (P3-H): 每个对话框一个文件, 此处统一再导出 (对外 import 路径不变)。"""
from dialogs.octave_map import OctaveMapDialog
from dialogs.keymap_dialog import KeymapDialog
from dialogs.transpose_analysis import TransposeAnalysisDialog
from dialogs.settings_dialog import SettingsDialog
from dialogs.note_settings import NoteSettingsDialog
from dialogs.app_settings import AppSettingsDialog
from dialogs.track_sound import TrackSoundDialog
from dialogs.note_props import NotePropsDialog, NotePropsMultiDialog
from dialogs.density_result import DensityResultDialog
from dialogs.transcribe_instruments import TranscribeInstrumentsDialog
__all__ = ['OctaveMapDialog', 'KeymapDialog', 'TransposeAnalysisDialog', 'SettingsDialog',
           'NoteSettingsDialog', 'AppSettingsDialog', 'TrackSoundDialog', 'NotePropsDialog',
           'NotePropsMultiDialog', 'TranscribeInstrumentsDialog', 'DensityResultDialog']
