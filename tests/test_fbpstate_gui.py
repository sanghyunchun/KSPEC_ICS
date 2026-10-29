"""Manual fbpstate initial resets the individual positioner indicators."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class Label:
    def __init__(self, color):
        self.color = color


def state_gui_class():
    source = Path(__file__).resolve().parents[1] / 'KSPECRUN_gui.py'
    tree = ast.parse(source.read_text())
    window = next(node for node in tree.body
                  if isinstance(node, ast.ClassDef) and node.name == 'MainWindow')
    names = {'_set_button_state', 'reset_fbp_error_labels', 'set_fbp_state'}
    methods = [node for node in window.body
               if isinstance(node, ast.FunctionDef) and node.name in names]
    cls = ast.ClassDef(name='StateGUI', bases=[], keywords=[], body=methods,
                       decorator_list=[])
    namespace = {'QLabel': Label}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])),
                 str(source), 'exec'), namespace)
    return namespace['StateGUI']


class FBPStateTests(unittest.TestCase):
    def test_initial_resets_all_mapped_positioners(self):
        gui = state_gui_class()()
        gui.fbp_state = 'assign'
        gui.msglog_path = None
        gui.positioner_axis_map = {'E1': {}, 'E2': {}}
        gui.ui = SimpleNamespace(
            circle_E1=Label('green'), circle_E2=Label('green'),
            circle_spare=Label('gray'),
            pushbtn_FBP_assign=Mock(), pushbtn_FBP_assign_2=Mock(),
        )
        gui.FPLabelStyle = lambda label, color: setattr(label, 'color', color)
        gui.logging = Mock()

        gui.set_fbp_state('initial')

        self.assertEqual(gui.ui.circle_E1.color, 'black')
        self.assertEqual(gui.ui.circle_E2.color, 'black')
        self.assertEqual(gui.ui.circle_spare.color, 'gray')
        for button in (gui.ui.pushbtn_FBP_assign, gui.ui.pushbtn_FBP_assign_2):
            button.setStyleSheet.assert_called_with('color: black')
            button.setChecked.assert_called_with(False)


if __name__ == '__main__':
    unittest.main()
