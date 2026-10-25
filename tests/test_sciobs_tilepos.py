import ast
import json
import os
import tempfile
import unittest
from pathlib import Path


def tilepos_method():
    source = Path(__file__).resolve().parents[1] / 'SCIOBS' / 'sciobscli.py'
    tree = ast.parse(source.read_text())
    sciobs_class = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                        and node.name == 'sciobscli')
    method = next(node for node in sciobs_class.body if isinstance(node, ast.FunctionDef)
                  and node.name == 'load_tilepos')
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    namespace = {'json': json, 'os': os}
    exec(compile(module, str(source), 'exec'), namespace)
    return namespace['load_tilepos']


class TilePositionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.info_path = Path(self.directory.name) / 'ASPECS_2627.info.txt'
        self.sciobs = type('Sciobs', (), {})()
        self.sciobs.targetpath = self.directory.name
        self.sciobs.project = 'ASPECS'
        self.sciobs.tile_id = '0005'
        self.sciobs.ra = None
        self.sciobs.dec = None
        self.load_tilepos = tilepos_method()

    def test_headerless_sparse_ids_and_trailing_comment(self):
        self.info_path.write_text('0005 270.872801 10.806923 #main\n'
                                  '0010 80.859375 8.385539 #main\n')
        message = json.loads(self.load_tilepos(self.sciobs))
        self.assertEqual((self.sciobs.ra, self.sciobs.dec), (270.872801, 10.806923))
        self.assertEqual((message['tid'], message['ra'], message['dec']),
                         (5, 270.872801, 10.806923))

    def test_missing_tile_is_rejected(self):
        self.info_path.write_text('0010 80.859375 8.385539 #main\n')
        with self.assertRaisesRegex(ValueError, 'found 0'):
            self.load_tilepos(self.sciobs)

    def test_duplicate_tile_is_rejected(self):
        self.info_path.write_text('0005 270.872801 10.806923 #main\n'
                                  '5 270.872801 10.806923 #secondary\n')
        with self.assertRaisesRegex(ValueError, 'found 2'):
            self.load_tilepos(self.sciobs)
        self.assertIsNone(self.sciobs.ra)
        self.assertIsNone(self.sciobs.dec)


if __name__ == '__main__':
    unittest.main()
