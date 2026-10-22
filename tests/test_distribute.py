"""FMUs for other machines: vendored wheels (--vendor) and frozen executables (--compile)."""
import importlib.util
import tomllib
import zipfile

import pytest
from conftest import EXAMPLES
from fmpy import simulate_fmu

from fmugen.builder import build
from fmugen.config import InterfaceError


def _contents(fmu):
    with zipfile.ZipFile(fmu) as z:
        return tomllib.loads(z.read("resources/launch.toml").decode()), z.namelist()


def _simulate_pid(fmu):
    return simulate_fmu(str(fmu), stop_time=1, output=["output"])["output"]


def test_options_are_checked(tmp_path):
    with pytest.raises(InterfaceError, match="exclude each other"):
        build(EXAMPLES / "simple_pid", tmp_path / "a.fmu", vendor=True, compiler="pyinstaller")
    with pytest.raises(InterfaceError, match="only apply with --vendor"):
        build(EXAMPLES / "simple_pid", tmp_path / "b.fmu", platforms=["win_amd64"])


@pytest.mark.fmu
def test_vendored_fmu_installs_its_wheels_offline_once(tmp_path, monkeypatch):
    envs = tmp_path / "envs"
    monkeypatch.setenv("FMUGEN_ENV_DIR", str(envs))
    fmu = build(EXAMPLES / "simple_pid", tmp_path / "pid.fmu", vendor=True)[0]
    launch, names = _contents(fmu)
    assert launch["windows"] == ["python", "fmugen_launch.py"] and launch["linux"] == ["python3", "fmugen_launch.py"]
    wheels = {n.split("/")[-1].split("-")[0].lower() for n in names if n.endswith(".whl")}
    assert {"protobuf", "pyzmq", "simple_pid"} <= wheels

    first = _simulate_pid(fmu)
    created = sorted(p.name for p in envs.iterdir())
    assert len(created) == 1 and (envs / created[0] / ".complete").exists()
    second = _simulate_pid(fmu)
    assert sorted(p.name for p in envs.iterdir()) == created
    assert first[-1] != 0 and list(first) == list(second)


@pytest.mark.slow
@pytest.mark.parametrize("compiler", ["pyinstaller", "nuitka"])
def test_compiled_fmu_has_no_sources_and_simulates(tmp_path, compiler):
    module = {"pyinstaller": "PyInstaller", "nuitka": "nuitka"}[compiler]
    if not importlib.util.find_spec(module):
        pytest.skip(f"{module} is not installed")
    fmu = build(EXAMPLES / "simple_pid", tmp_path / "pid.fmu", compiler=compiler)[0]
    launch, names = _contents(fmu)
    assert launch["windows"][0] == "powershell" and "dist/main/main" in launch["linux"][-1]
    resources = [n for n in names if n.startswith("resources/") and not n.startswith("resources/dist/")
                 and not n.endswith("/")]
    assert resources == ["resources/launch.toml"]
    assert not any(n.endswith(".py") for n in names)
    assert _simulate_pid(fmu)[-1] != 0


def test_compile_finds_the_modules_of_computed_constants():
    from fmugen.distribute import _modules
    interface = {"entry": {"module": "joblib"}, "constants": {
        "filename": {"call": "huggingface_hub:hf_hub_download(repo_id='x', grid=numpy.linspace(0, 1, 3))"}}}
    assert {"joblib", "huggingface_hub", "numpy"} <= set(_modules(interface))


def test_compile_collects_the_dependencies_of_the_model_packages():
    from fmugen.distribute import _packages
    direct, packages, distributions, imports = _packages(["fmpy.simulation", "cloudpickle"])
    assert direct == ["cloudpickle", "fmpy"]   # their submodules are collected
    assert {"fmpy", "numpy", "lxml"} <= set(packages)   # data files and binaries of the whole tree
    assert {"fmpy", "numpy"} <= set(distributions)
    assert {"numpy", "lxml"} <= set(imports)   # fmpy's own dependencies, imported by name
    assert "fmugen" not in packages and "os" not in direct
    assert _packages(["os", "not_installed_anywhere"]) == ([], [], [], [])


def test_nuitka_gets_package_options_only_for_packages():
    # matplotlib's pylab.py and six.py are single modules: Nuitka stops on package options for them
    from fmugen.distribute import _nuitka_package_args
    if not (importlib.util.find_spec("matplotlib") and importlib.util.find_spec("six")):
        pytest.skip("matplotlib and six are needed")
    expected = ["--include-package-data=matplotlib", "--include-package=matplotlib", "--include-module=six"]
    packages, direct = ["matplotlib", "pylab", "six", "not_installed_anywhere"], ["matplotlib", "six"]
    assert _nuitka_package_args(packages, direct) == expected
    import six   # once imported, six's spec has __path__ = [] (for six.moves), as during a build
    assert six.__spec__.submodule_search_locations == []
    assert _nuitka_package_args(packages, direct) == expected


def test_hugging_face_model_ids_are_found(tmp_path):
    from fmugen.distribute import hf_models
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.csv").write_text("1")
    interface = {
        "variables": [{"start": "amazon/chronos-bolt-tiny"}, {"start": "data/x.csv"}, {"start": "male"},
                      {"start": 1.0}],
        "constants": {"repo": {"python": "'sb3/ppo-CartPole-v1'"}, "n": {"python": "3"}},
    }
    assert hf_models(interface, tmp_path) == ["amazon/chronos-bolt-tiny", "sb3/ppo-CartPole-v1"]


def test_file_paths_are_not_taken_for_hugging_face_models(tmp_path):
    from fmugen.distribute import hf_models
    (tmp_path / "run" / "data").mkdir(parents=True)
    (tmp_path / "run" / "data" / "weather.bin").write_text("1")
    interface = {
        "cwd": "fmugen_model/run",   # [model] cwd = "run": data/weather.bin is opened from there
        "variables": [{"start": "data/weather.bin"}, {"start": "results/out.csv"}, {"start": "sb3/ppo-x"}],
    }
    assert hf_models(interface, tmp_path) == ["sb3/ppo-x"]


def test_compiled_launcher_restores_the_execute_bits_of_the_whole_bundle():
    # unzipping drops them; gekko runs its solver from inside the bundle (dist/main/_internal/gekko/bin)
    from fmugen.distribute import compiled_launch_command
    assert compiled_launch_command("linux") == ["sh", "-c", "chmod -R u+x dist/main && ./dist/main/main"]
    assert compiled_launch_command("windows")[0] == "powershell"


@pytest.mark.parametrize("meipass", [True, False])   # PyInstaller, Nuitka
def test_data_kept_outside_a_compiled_bundle_is_found(tmp_path, monkeypatch, meipass):
    from fmugen.templates.fmugen_runtime import _helpers
    resources = tmp_path / "resources"
    exe_dir = resources / "dist" / "main"
    bundle = exe_dir / "_internal" if meipass else exe_dir
    (bundle / "parts" / "pv").mkdir(parents=True)
    assert _helpers.outside_bundle(bundle) == bundle   # not compiled: unchanged
    monkeypatch.setattr(_helpers.sys, "frozen", True, raising=False)
    monkeypatch.setattr(_helpers.sys, "executable", str(exe_dir / "main"))
    if meipass:
        monkeypatch.setattr(_helpers.sys, "_MEIPASS", str(bundle), raising=False)
    else:
        monkeypatch.delattr(_helpers.sys, "_MEIPASS", raising=False)
    assert _helpers.outside_bundle(bundle) == resources.resolve()
    assert _helpers.outside_bundle(bundle / "parts" / "pv") == (resources / "parts" / "pv").resolve()
    assert _helpers.outside_bundle(tmp_path) == tmp_path   # not in the bundle


@pytest.mark.slow
def test_compiled_fmu_reads_the_data_files_of_its_working_folder(tmp_path):
    # like NHES and CGE: [model] cwd, and a file the model reads by a relative path
    if not importlib.util.find_spec("PyInstaller"):
        pytest.skip("PyInstaller is not installed")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "load.csv").write_text("12.5\n")
    (tmp_path / "grid.py").write_text(
        "def load(scale: float = 2.0):\n"
        "    with open('data/load.csv') as f:\n"
        "        return scale * float(f.read())\n")
    (tmp_path / "fmugen.toml").write_text(
        '[model]\nentry = "grid.py:load"\ncwd = "."\nsources = ["data/load.csv"]\n'
        '[inputs]\nscale = { start = 2.0 }\n[outputs]\ny = { from = "return" }\n')
    fmu = build(tmp_path / "fmugen.toml", tmp_path / "grid.fmu", compiler="pyinstaller")[0]
    assert simulate_fmu(str(fmu), stop_time=1, output=["y"])["y"][-1] == 25.0


def test_packages_that_import_their_own_submodules_are_collected_whole(monkeypatch):
    # pyomo.environ imports its plugins by name; pyomo is only a dependency of OpenHENS
    from fmugen import distribute
    monkeypatch.setattr(distribute, "IMPORTS_OWN_SUBMODULES", {"numpy"})
    direct, packages, _, imports = distribute._packages(["fmpy.simulation"])
    assert "numpy" in direct and "numpy" not in imports   # a dependency of fmpy, collected with its submodules


def test_editable_installs_are_put_on_the_freezer_path(tmp_path, monkeypatch):
    # pip install -e: an import hook finds the project, which isn't on sys.path (the debutanizer project)
    import importlib.machinery
    import sys
    from fmugen.distribute import _editable_paths
    project = tmp_path / "project"
    (project / "debutanizer_like").mkdir(parents=True)
    (project / "debutanizer_like" / "__init__.py").write_text("")

    class EditableFinder:   # what setuptools' __editable___*_finder installs
        @classmethod
        def find_spec(cls, name, path=None, target=None):
            if name == "debutanizer_like":
                return importlib.machinery.PathFinder.find_spec(name, [str(project)])
            return None

    monkeypatch.setattr(sys, "meta_path", [EditableFinder, *sys.meta_path])
    assert _editable_paths(["debutanizer_like", "pytest", "json", "not_installed_anywhere"]) == [project.resolve()]
