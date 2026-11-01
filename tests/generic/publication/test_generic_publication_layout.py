"""Guard relocation of the G47-G48 publication and native route tests."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[3]
PUBLICATION = ROOT / "tests" / "generic" / "publication"
MOVED = (
    "test_generic_registry_g47.py",
    "test_generic_registry_g47b.py",
    "test_generic_publication_g48.py",
    "test_generic_publication_coverage_g48a.py",
    "test_generic_route_navigation_g48b.py",
    "test_generic_native_route_decisions_g48c.py",
    "test_generic_all_class_product_gate_g48d.py",
)


class PublicationLayout(unittest.TestCase):
    def test_all_moved_modules_exist_and_parse(self):
        for name in MOVED:
            with self.subTest(test_module=name):
                self.assertFalse((ROOT / "tests" / name).exists())
                path = PUBLICATION / name
                self.assertTrue(path.is_file())
                source = path.read_text(encoding="utf-8")
                syntax = ast.parse(source, filename=str(path))
                self.assertTrue(any(
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test_")
                    for node in ast.walk(syntax)
                ))
                self.assertNotIn("Path(__file__)", source)
                self.assertNotIn("from tests.", source)

    def test_normal_pytest_collection_includes_publication(self):
        ini = (ROOT / "pytest.ini").read_text()
        self.assertIn("testpaths = tests", ini)
        self.assertIn("norecursedirs = release", ini)
        self.assertNotIn("norecursedirs = generic", ini)


if __name__ == "__main__":
    unittest.main()
