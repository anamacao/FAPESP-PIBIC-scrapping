import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class OriginalNotebookSelectionTests(unittest.TestCase):
    def test_all_selects_only_the_21_original_notebooks(self):
        spec = importlib.util.spec_from_file_location(
            "check_notebooks", ROOT / "scripts" / "check_notebooks.py"
        )
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"nbformat": types.ModuleType("nbformat")}):
            spec.loader.exec_module(module)

        paths = module.original_notebooks()

        self.assertEqual(len(paths), 21)
        self.assertEqual({path.stem for path in paths}, set(module.DATAFRAMES))
        self.assertNotIn(Path("Mercosul/agesic.ipynb"), paths)
        self.assertNotIn(Path("Mercosul/anpd.ipynb"), paths)
        self.assertNotIn(Path("UE/dsa_transparency.ipynb"), paths)


if __name__ == "__main__":
    unittest.main()
