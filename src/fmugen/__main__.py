"""fmugen CLI.

    fmugen init path/to/model.py[:Name]                      # write path/to/fmugen.toml for review
    fmugen build path/to/fmugen.toml -o out/model.fmu        # packaged FMU (default)
    fmugen build path/to/model.py -o out/model.fmu           # same, with the config inferred in memory
    fmugen build path/to/fmugen.toml -o out/model --format folder
    fmugen build path/to/fmugen.toml -o out/model.fmu --fmi 3        # FMI 3.0 instead of 2.0
"""
import argparse
import contextlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from fmugen.config import MODEL_DIR, Config, InterfaceError, load_config, normalize
from fmugen.description import write_model_description
from fmugen.interface import infer_config, parse_target, render_toml
from fmugen.templates import model_fmi2, model_fmi3
from fmugen.templates.fmugen_runtime import Status, setup_sys_path

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
ADAPTERS = {2: TEMPLATES_DIR / "model_fmi2.py", 3: TEMPLATES_DIR / "model_fmi3.py"}
RUNTIME = TEMPLATES_DIR / "fmugen_runtime.py"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "venv", ".venv")
FORMATS = ("fmu", "folder")

# The FMU runs with the Python fmugen is installed in: the model's own virtual environment,
# which has the model's packages and (as fmugen's dependencies) the UniFMU backend's.
OSES = ("linux", "macos", "windows")
DEFAULT_PYTHON = {"linux": "python3", "macos": "python3", "windows": "python"}
CURRENT_OS = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
# What UniFMU 0.14's Python backend imports (its own requirements.txt lists more)
BACKEND_REQUIREMENTS = ["protobuf==5.27.3", "pyzmq"]

# The FMU boilerplate (native binaries + Python backend) comes from `unifmu generate`.
# The adapters are written against this exact UniFMU version's backend.
UNIFMU_VERSION = "0.14.0"
UNIFMU_ENV = "FMUGEN_UNIFMU"   # path to the unifmu executable, if it isn't on PATH
UNIFMU_INSTALL = (f"install UniFMU {UNIFMU_VERSION} from "
                  "https://github.com/INTO-CPS-Association/unifmu/releases "
                  f"and put it on PATH, or set {UNIFMU_ENV} to the executable")
_unifmu_checked = None


def find_unifmu():
    """Return the path of the unifmu executable, after checking it is version UNIFMU_VERSION."""
    global _unifmu_checked
    exe = os.environ.get(UNIFMU_ENV) or shutil.which("unifmu")
    if not exe:
        raise InterfaceError(f"the unifmu command was not found; {UNIFMU_INSTALL}")
    if _unifmu_checked == exe:
        return exe
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise InterfaceError(f"cannot run {exe}: {e}; {UNIFMU_INSTALL}") from e
    found = out.split()[-1] if out.split() else "?"
    if found != UNIFMU_VERSION:
        raise InterfaceError(f"{exe} is UniFMU {found}, but fmugen needs exactly {UNIFMU_VERSION}; {UNIFMU_INSTALL}")
    _unifmu_checked = exe
    return exe


def generate_boilerplate(fmi_version, dest):
    """Write UniFMU's Python FMU template for `fmi_version` (2 or 3) to `dest`."""
    exe = find_unifmu()
    result = subprocess.run([exe, "generate", "python", str(dest), f"fmi{fmi_version}"],
                            capture_output=True, text=True)
    if result.returncode != 0 or not (Path(dest) / "resources").is_dir():
        raise InterfaceError(f"`unifmu generate python {dest} fmi{fmi_version}` failed:\n"
                             f"{result.stdout}{result.stderr}")


def _write_launch_toml(resources_dir):
    """Run the backend with this interpreter on this OS (other OSes keep UniFMU's defaults)."""
    pythons = {**DEFAULT_PYTHON, CURRENT_OS: sys.executable}
    (resources_dir / "launch.toml").write_text(
        "".join(f'{system} = [{json.dumps(pythons[system])}, "main.py"]\n' for system in OSES)
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


def resolve_target(target, call=None, fmi_version=None):
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
        data, _ = infer_config(target, call=call, fmi_version=fmi_version)
    return Config(data, model_path.parent if model_path else Path.cwd())


def _copy_sources(config, model_dir):
    for src, rel in config.source_files():
        dest = model_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, ignore=IGNORE, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dest)


def _probe(resources, interface):
    """Run the packaged model once through the real adapter; return whether its state can be saved."""
    logs = []

    def log(status, category, message):
        logs.append(message)

    experiment = interface["experiment"]
    start = experiment.get("start_time", 0.0)
    stop = experiment.get("stop_time")
    step = experiment.get("step_size", 1.0)

    def check(status, what):
        if status != Status.ok:
            raise InterfaceError(f"probe {what} failed:\n" + "\n".join(logs))

    if interface["fmi_version"] == 3:
        event_mode = interface["has_event_mode"]
        model = model_fmi3.Model("probe", "", str(resources), False, False, event_mode, False, [], log,
                                 resources_dir=resources)
        check(model.fmi3EnterInitializationMode(False, 0.0, start, stop is not None, stop or 0.0), "initialization")
        check(model.fmi3ExitInitializationMode(), "initialization")
        if event_mode:
            input_clocks = [c["valueReference"] for c in interface["clocks"] if c["causality"] == "input"]
            if input_clocks:  # tick every input clock once
                check(model.fmi3SetClock(input_clocks, [True] * len(input_clocks)), "setting clocks")
                check(model.fmi3UpdateDiscreteStates()[0], "clock tick (updateDiscreteStates)")
            check(model.fmi3EnterStepMode(), "entering step mode")
        check(model.fmi3DoStep(start, step, False)[0], "doStep")
        serialize, deserialize = model.fmi3SerializeFmuState, model.fmi3DeserializeFmuState
    else:
        model = model_fmi2.Model(log, resources_dir=resources)
        check(model.fmi2SetupExperiment(start, stop, experiment.get("tolerance")), "setup")
        check(model.fmi2EnterInitializationMode(), "initialization")
        check(model.fmi2ExitInitializationMode(), "initialization")
        check(model.fmi2DoStep(start, step, False), "doStep")
        serialize, deserialize = model.fmi2SerializeFmuState, model.fmi2DeserializeFmuState

    status, state = serialize()
    if status != Status.ok:
        print(f"note: the model object cannot be pickled, so FMU state save/restore is disabled ({logs[-1]})")
        return False
    check(deserialize(state), "state restore")
    return True


def build(target, output, model_name=None, author=None, output_format="fmu", call=None, fmi_version=None):
    if output_format not in FORMATS:
        raise ValueError(f"unknown output format {output_format!r}, expected one of {FORMATS}")
    output = Path(output)
    if output_format == "fmu" and output.is_dir():
        raise FileExistsError(f"{output} is a directory; cannot write an .fmu archive there")
    if output_format == "folder" and output.is_file():
        raise FileExistsError(f"{output} is a file; cannot write a folder there")

    config = resolve_target(target, call=call, fmi_version=fmi_version)
    version = config.fmi_version(fmi_version)
    if version not in ADAPTERS:
        raise InterfaceError(f"unknown FMI version {version!r}, expected one of {sorted(ADAPTERS)}")

    with tempfile.TemporaryDirectory() as tmp:
        fmu_dir = Path(tmp) / "fmu"
        generate_boilerplate(version, fmu_dir)
        resources = fmu_dir / "resources"
        shutil.copy2(ADAPTERS[version], resources / "model.py")
        shutil.copy2(RUNTIME, resources / "fmugen_runtime.py")
        _copy_sources(config, resources / MODEL_DIR)

        (resources / "requirements.txt").write_text(
            "# UniFMU backend\n" + "\n".join(BACKEND_REQUIREMENTS) + "\n"
            + ("# model requirements\n" + "\n".join(config.requirements) + "\n" if config.requirements else "")
        )
        module, sys_path = config.entry_import()

        with isolated_imports():
            setup_sys_path({"sys_path": sys_path}, resources)
            try:
                entry_obj = getattr(importlib.import_module(module), config.entry_name)
            except (ImportError, AttributeError) as e:
                hint = " (install the model's requirements in the environment fmugen runs in)" \
                    if config.requirements else ""
                raise InterfaceError(f"cannot import {config.model['entry']}: {e!r}{hint}") from e
            interface = normalize(config, entry_obj, module, sys_path, model_name, author, version)
            for note in interface.pop("notes"):
                print(f"note: {note}")
            write_interface(interface, resources / "interface.json")
            interface["can_get_and_set_state"] = _probe(resources, interface)
        write_interface(interface, resources / "interface.json")

        write_model_description(interface, fmu_dir / "modelDescription.xml")
        _write_launch_toml(resources)

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


def init(target, output=None, call=None, force=False, fmi_version=None, starts=None, setup=None, kind=None):
    """Write the inferred config to `output` (default: fmugen.toml next to the model; "-": stdout)."""
    model_path, _, _ = parse_target(target)
    default_dir = model_path.parent if model_path else Path.cwd()
    to_stdout = output == "-"
    output = default_dir / "fmugen.toml" if (output is None or to_stdout) else Path(output)
    if output.exists() and not force and not to_stdout:
        raise FileExistsError(f"{output} already exists; pass --force to overwrite it, or -o - to print it")
    with isolated_imports():
        data, comments = infer_config(target, call=call, config_dir=output.parent, fmi_version=fmi_version,
                                      starts=starts, setup=setup, kind=kind)
    text = render_toml(data, comments)
    if to_stdout:
        sys.stdout.write(text)
        return None, data
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return output, data


def _parse_starts(items):
    import ast
    starts = {}
    for item in items:
        name, sep, text = item.partition("=")
        if not sep or not name.strip().isidentifier():
            raise InterfaceError(f"--start {item!r}: expected NAME=VALUE")
        try:
            starts[name.strip()] = ast.literal_eval(text.strip())
        except (ValueError, SyntaxError):
            starts[name.strip()] = text.strip()  # a bare word: a string
    return starts


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
    i.add_argument("--fmi", type=int, choices=(2, 3), help="target FMI version; 3 also infers arrays and Binary")
    i.add_argument("--start", action="append", default=[], metavar="NAME=VALUE",
                   help="start/probe value for an argument (a Python literal), e.g. for arguments "
                        "without a default; repeatable")
    i.add_argument("--setup", action="append", default=[], metavar="CALL",
                   help="run before the model is used, e.g. 'psychrolib:SetUnitSystem(psychrolib.SI)' "
                        "or 'reset' (a method, after construction); repeatable")
    i.add_argument("--kind", choices=("function",),
                   help="function: treat a class whose constructor does the work as a function called every step")

    b = sub.add_parser("build", help="build a UniFMU from a fmugen.toml or a model file",
                       description="Build an FMI 2.0 or 3.0 Co-Simulation FMU. MODEL is a fmugen.toml, a directory "
                                   "containing one, or a model file whose config is inferred in memory. "
                                   "See docs/config.md and docs/packaging.md.")
    b.add_argument("model", help="fmugen.toml, a directory containing one, or model.py[:Name]")
    b.add_argument("-o", "--output", required=True, help="output path, used exactly as given")
    b.add_argument("--format", choices=FORMATS, default="fmu",
                   help="fmu: zipped .fmu archive (default); folder: unzipped UniFMU folder")
    b.add_argument("--name", help="modelName in modelDescription.xml (default: [model] name, else the entry name)")
    b.add_argument("--author", default=None, help="author in modelDescription.xml (default: [model] author)")
    b.add_argument("--call", help="method run on each step when MODEL is a .py file with a class")
    b.add_argument("--fmi", type=int, choices=(2, 3), help="FMI version (default: [model] fmi_version, else 2)")

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            output, data = init(args.model, args.output, args.call, args.force, args.fmi,
                                _parse_starts(args.start), args.setup, args.kind)
            if output:
                print(f"Wrote {output.resolve()}; review it, then run: fmugen build {output}")
            return
        output, interface = build(args.model, args.output, args.name, args.author,
                                  args.format, args.call, args.fmi)
    except (FileExistsError, InterfaceError) as e:
        parser.exit(2, f"fmugen: error: {e}\n")

    counts = {}
    for v in interface["variables"]:
        if v["causality"] != "independent":
            counts[v["causality"]] = counts.get(v["causality"], 0) + 1
    summary = ", ".join(f"{n} {c}s" for c, n in counts.items())
    if interface.get("clocks"):
        summary += f", {len(interface['clocks'])} clocks"
    print(f"Built {output.resolve()} (FMI {interface['fmi_version']}.0; {summary})")


if __name__ == "__main__":
    main()
