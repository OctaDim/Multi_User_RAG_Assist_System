import importlib.util
import shutil

from app import resources


def test_installed_package_ignores_an_unrelated_neighbor_config(tmp_path):
    package = tmp_path / "app"
    package.mkdir()
    module_file = package / "resources.py"
    shutil.copyfile(resources.__file__, module_file)
    packaged = package / "_resources" / "config"
    packaged.mkdir(parents=True)
    (packaged / "runtime.toml").write_text("max_active = 12\n")
    unrelated = tmp_path / "config"
    unrelated.mkdir()
    (unrelated / "runtime.toml").write_text("unrelated = true\n")
    spec = importlib.util.spec_from_file_location("installed_resources", module_file)
    installed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installed)
    assert (installed.resource_path("config") / "runtime.toml").read_text() == "max_active = 12\n"


def test_working_tree_resources_still_load_runtime_and_migrations():
    assert (resources.resource_path("config") / "runtime.toml").is_file()
    assert (resources.resource_path("migrations") / "001_answer_lifecycle.sql").is_file()
