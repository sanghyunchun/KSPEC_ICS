"""Viewer keeps the last real image during gaps between GFA exposures."""
import ast
import unittest
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def viewer_class():
    source = Path(__file__).resolve().parents[1] / 'GFA' / 'viewer.py'
    tree = ast.parse(source.read_text())
    viewer = next(node for node in tree.body
                  if isinstance(node, ast.ClassDef) and node.name == 'FitsLiveViewer')
    names = {'_poll', '_update_status', 'on_prev', 'on_next', 'on_latest', 'on_relock'}
    methods = [node for node in viewer.body
               if isinstance(node, ast.FunctionDef) and node.name in names]
    cls = ast.ClassDef(name='Viewer', bases=[], keywords=[], body=methods,
                       decorator_list=[])
    namespace = {'sorted_keys': sorted}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])),
                 str(source), 'exec'), namespace)
    return namespace['Viewer']


FrameKey = namedtuple('FrameKey', 'date t')


class ViewerWaitingTests(unittest.TestCase):
    def setUp(self):
        self.viewer = viewer_class()()
        self.key = FrameKey('20261029', '120000')
        self.viewer._closing = False
        self.viewer.actual_groups = {}
        self.viewer.groups = {self.key: {'camera': '/raw/old.fits'}}
        self.viewer.keys = [self.key]
        self.viewer.idx = 0
        self.viewer.demo_active = False
        self.viewer.waiting_for_next_frame = False
        self.viewer.follow_latest = True
        self.viewer.reference_locked = True
        self.viewer.source_label = 'raw'
        self.viewer.status_var = SimpleNamespace(set=Mock())
        self.viewer.win = SimpleNamespace(title=Mock())
        self.viewer._rescan = Mock(return_value=True)
        self.viewer._activate_demo_mode = Mock()
        self.viewer._activate_actual_mode = Mock()
        self.viewer._schedule_poll = Mock()
        self.viewer._render_current = Mock()
        self.viewer._lock_reference_stars = Mock()
        self.viewer._copy_groups = dict

    def test_empty_raw_keeps_last_frame_and_waits(self):
        self.viewer._poll()
        self.assertTrue(self.viewer.waiting_for_next_frame)
        self.assertEqual(self.viewer.groups[self.key]['camera'], '/raw/old.fits')
        self.assertTrue(self.viewer.reference_locked)
        self.assertIn('Waiting for next frame', self.viewer.status_var.set.call_args.args[0])
        self.viewer._activate_demo_mode.assert_not_called()
        self.viewer._render_current.assert_not_called()

    def test_new_frame_replaces_waiting_frame(self):
        self.viewer._poll()
        new_key = FrameKey('20261029', '120100')
        self.viewer.actual_groups = {new_key: {'camera': '/raw/new.fits'}}
        self.viewer._poll()
        self.assertFalse(self.viewer.waiting_for_next_frame)
        self.assertEqual(self.viewer.groups[new_key]['camera'], '/raw/new.fits')
        self.viewer._render_current.assert_called_once()

    def test_initial_empty_directory_still_shows_demo(self):
        self.viewer.groups = {}
        self.viewer.keys = []
        self.viewer._poll()
        self.viewer._activate_demo_mode.assert_called_once()

    def test_navigation_does_not_reopen_deleted_raw_files(self):
        self.viewer._poll()
        self.viewer.follow_var = SimpleNamespace(set=Mock())
        for method in (self.viewer.on_prev, self.viewer.on_next,
                       self.viewer.on_latest, self.viewer.on_relock):
            method()
        self.viewer._render_current.assert_not_called()
        self.viewer._lock_reference_stars.assert_not_called()


if __name__ == '__main__':
    unittest.main()
