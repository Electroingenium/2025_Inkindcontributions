"""fmugen CLI.

    fmugen init path/to/model.py[:Name]                      # write path/to/fmugen.toml for review
    fmugen build path/to/fmugen.toml -o out/model.fmu        # packaged FMU (default)
    fmugen build path/to/model.py -o out/model.fmu           # same, with the config inferred in memory
    fmugen build path/to/fmugen.toml -o out/model --format folder
"""
import argparse
import contextlib
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from fmugen.config import MODEL_DIR, SITE_DIR, Config, InterfaceError, load_config, normalize
from fmugen.description import write_model_description
from fmugen.interface import infer_config, parse_target, render_toml
from fmugen.templates import model as runtime

PACKAGE_DIR = Path(__file__).resolve().parent
BOILERPLATE_DIR = PACKAGE_DIR.parent / "fmu"
TEMPLATE_MODEL = PACKAGE_DIR / "templates" / "model.py"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "venv", ".venv")
FORMATS = ("fmu", "folder")


def _write_launch_toml(resources_dir, python_exec):
    python_exec = python_exec.replace("\\", "/")
    (resources_dir / "launch.toml").write_text(
        'linux = ["python3", "main.py"]\n'
        'macos = ["python3", "main.py"]\n'
        f'windows = ["{python_exec}", "main.py"]\n'
    )


def write_interface(interface, path):
    Path(path).write_text(json.dumps(interface, indent=2))


@contextlib.contextmanager
def isolated_imports():
    """Undo sys.path changes and forget modules loaded from the added paths.

    Building imports the user's code to inspect and probe it; this keeps one build
    (or a test) from seeing modules cached by another.
    """
    saved_path = list(sys.path)
    saved_modules = set(sys.modules)
    try:
        yield
    finally:
        added = [Path(p).resolve() for p in sys.path if p and p not in saved_path]
        sys.path[:] = saved_path
        for name in set(sys.modules) - saved_modules:
            module = sys.modules[name]
            locations = [getattr(module, "__file__", None), *(getattr(module, "__path__", None) or [])]
            if any(loc and Path(loc).resolve().is_relative_to(p) for loc in locations for p in added):
                del sys.modules[name]


def resolve_target(target, call=None):
    """Return a Config for a fmugen.toml, a directory containing one, or a model file."""
    path = Path(target)
    if path.is_dir():
        path = path / "fmugen.toml"
    if path.suffix == ".toml":
        if not path.exists():
            raise InterfaceError(f"{path} does not exist; create it with `fmugen init`")
        return load_config(path)
    model_path, _, _ = parse_target(target)
    with isolated_imports():
        data, _ = infer_config(target, call=call)
    return Config(data, model_path.parent if model_path else Path.cwd())


def _copy_sources(config, model_dir):
    for src, rel in config.source_files():
        dest = model_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, ignore=IGNORE, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dest)


def _vendor(requirements, target):
    uv = shutil.which("uv")
    if uv:
        cmd = [uv, "pip", "install", "--quiet", "--python", sys.executable, "--target", str(target), *requirements]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(target), *requirements]
    try:
        subprocess.run(cmd, check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise InterfaceError(f"installing {requirements} into the FMU failed: {e}") from e


def _probe(resources, interface):
    """Run the packaged model once through the real adapter; return whether its state can be saved."""
    logs = []
    model = runtime.Model(lambda status, category, message: logs.append(message), resources_dir=resources)
    experiment = interface["experiment"]
    start = experiment.get("start_time", 0.0)
    step = experiment.get("step_size", 1.0)

    def check(status, what):
        if status != runtime.Fmi2Status.ok:
            raise InterfaceError(f"probe {what} failed:\n" + "\n".join(logs))

    check(model.fmi2SetupExperiment(start, experiment.get("stop_time"), experiment.get("tolerance")), "setup")
    check(model.fmi2EnterInitializationMode(), "initialization")
    check(model.fmi2ExitInitializationMode(), "initialization")
    check(model.fmi2DoStep(start, step, False), "doStep")
    status, state = model.fmi2SerializeFmuState()
    if status != runtime.Fmi2Status.ok:
        print(f"note: the model object cannot be pickled, so FMU state save/restore is disabled ({logs[-1]})")
        return False
    check(model.fmi2DeserializeFmuState(state), "state restore")
    return True


def build(target, output, model_name=None, author=None, python_exec=None, output_format="fmu",
          vendor=False, call=None):
    if output_format not in FORMATS:
        raise ValueError(f"unknown output format {output_format!r}, expected one of {FORMATS}")
    output = Path(output)
    if output_format == "fmu" and output.is_dir():
        raise FileExistsError(f"{output} is a directory; cannot write an .fmu archive there")
    if output_format == "folder" and output.is_file():
        raise FileExistsError(f"{output} is a file; cannot write a folder there")

    config = resolve_target(target, call=call)

    with tempfile.TemporaryDirectory() as tmp:
        fmu_dir = Path(tmp) / "fmu"
        shutil.copytree(BOILERPLATE_DIR, fmu_dir, ignore=IGNORE)
        resources = fmu_dir / "resources"
        shutil.copy2(TEMPLATE_MODEL, resources / "model.py")
        _copy_sources(config, resources / MODEL_DIR)

        if config.requirements:
            with (resources / "requirements.txt").open("a") as f:
                f.write("\n# model requirements\n" + "\n".join(config.requirements) + "\n")
            if vendor:
                _vendor(config.requirements, resources / SITE_DIR)
        module, sys_path = config.entry_import(vendored=vendor and bool(config.requirements))

        with isolated_imports():
            runtime.setup_sys_path({"sys_path": sys_path}, resources)
            try:
                entry_obj = getattr(importlib.import_module(module), config.entry_name)
            except (ImportError, AttributeError) as e:
                hint = " (install the model's requirements in this environment, or pass --vendor)" \
                    if config.requirements else ""
                raise InterfaceError(f"cannot import {config.model['entry']}: {e!r}{hint}") from e
            interface = normalize(config, entry_obj, module, sys_path, model_name, author)
            write_interface(interface, resources / "interface.json")
            interface["can_get_and_set_state"] = _probe(resources, interface)
        write_interface(interface, resources / "interface.json")

        write_model_description(interface, fmu_dir / "modelDescription.xml")
        if python_exec:
            _write_launch_toml(resources, python_exec)

        output.parent.mkdir(parents=True, exist_ok=True)
        if output_format == "fmu":
            output.unlink(missing_ok=True)
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zipf:
                for file in sorted(fmu_dir.rglob("*")):
                    if "__pycache__" not in file.parts:
                        zipf.write(file, arcname=file.relative_to(fmu_dir).as_posix())
        else:
            if output.exists():
                shutil.rmtree(output)
            shutil.copytree(fmu_dir, output, ignore=IGNORE)

    return output, interface


def init(target, output=None, call=None, force=False):
    """Write the inferred config to `output` (default: fmugen.toml next to the model; "-": stdout)."""
    model_path, _, _ = parse_target(target)
    default_dir = model_path.parent if model_path else Path.cwd()
    to_stdout = output == "-"
    output = default_dir / "fmugen.toml" if (output is None or to_stdout) else Path(output)
    if output.exists() and not force and not to_stdout:
        raise FileExistsError(f"{output} already exists; pass --force to overwrite it, or -o - to print it")
    with isolated_imports():
        data, comments = infer_config(target, call=call, config_dir=output.parent)
    text = render_toml(data, comments)
    if to_stdout:
        sys.stdout.write(text)
        return None, data
    output.write_text(text, encoding="utf-8")
    return output, data


def main(argv=None):
    parser = argparse.ArgumentParser(prog="fmugen", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    i = sub.add_parser("init", help="write a fmugen.toml by inspecting a model",
                       description="Import the model, inspect its function or class, make one probe call "
                                   "and write a commented fmugen.toml to review. See docs/models.md.")
    i.add_argument("model", help="model.py, model.py:Name, or package.module:Name")
    i.add_argument("-o", "--output", help="config path (default: fmugen.toml next to the model; - prints it)")
    i.add_argument("--call", help="method run on each step, for classes (default: step/do_step/update/__call__)")
    i.add_argument("--force", action="store_true", help="overwrite an existing config")

    b = sub.add_parser("build", help="build a UniFMU from a fmugen.toml or a model file",
                       description="Build an FMI 2.0 Co-Simulation FMU. MODEL is a fmugen.toml, a directory "
                                   "containing one, or a model file whose config is inferred in memory. "
                                   "See docs/config.md and docs/packaging.md.")
    b.add_argument("model", help="fmugen.toml, a directory containing one, or model.py[:Name]")
    b.add_argument("-o", "--output", required=True, help="output path, used exactly as given")
    b.add_argument("--format", choices=FORMATS, default="fmu",
                   help="fmu: zipped .fmu archive (default); folder: unzipped UniFMU folder")
    b.add_argument("--name", help="modelName in modelDescription.xml (default: [model] name, else the entry name)")
    b.add_argument("--author", default=None, help="author in modelDescription.xml (default: [model] author)")
    b.add_argument("--python", nargs="?", const=sys.executable, default=None,
                   help="python executable written into launch.toml for Windows "
                        "(flag alone = the current interpreter; omitted = keep boilerplate 'python')")
    b.add_argument("--vendor", action="store_true",
                   help="install [model] requirements into the FMU (resources/site)")
    b.add_argument("--call", help="method run on each step when MODEL is a .py file with a class")

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            output, data = init(args.model, args.output, args.call, args.force)
            if output:
                print(f"Wrote {output.resolve()}; review it, then run: fmugen build {output}")
            return
        output, interface = build(args.model, args.output, args.name, args.author, args.python,
                                  args.format, args.vendor, args.call)
    except (FileExistsError, InterfaceError) as e:
        parser.exit(2, f"fmugen: error: {e}\n")

    counts = {}
    for v in interface["variables"]:
        counts[v["causality"]] = counts.get(v["causality"], 0) + 1
    summary = ", ".join(f"{n} {c}s" for c, n in counts.items())
    print(f"Built {output.resolve()} ({summary})")


if __name__ == "__main__":
    main()
