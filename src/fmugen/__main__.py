"""fmugen CLI.

    fmugen init path/to/model.py[:Name]                      # write path/to/fmugen.toml for review
    fmugen build path/to/fmugen.toml -o out/model.fmu        # packaged FMU (default)
    fmugen build path/to/model.py -o out/model.fmu           # same, with the config inferred in memory
    fmugen build path/to/fmugen.toml -o out/model --format folder
    fmugen build path/to/fmugen.toml -o out/model.fmu --fmi 3        # FMI 3.0 instead of 2.0
    fmugen build path/to/fmugen.toml -o out/model.fmu --vendor       # runs on other machines with Python
    fmugen build path/to/fmugen.toml -o out/model.fmu --compile pyinstaller   # ... without Python, no sources
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

from fmugen.compose import PARTS_DIR, Composite, combine, is_composite
from fmugen.config import MODEL_DIR, Config, InterfaceError, load_config, normalize
from fmugen.description import write_model_description
from fmugen.distribute import COMPILERS, bundle_hf_models, compile_fmu, compiled_launch_command, vendor as vendor_wheels
from fmugen.interface import infer_config, parse_target, render_toml
from fmugen.templates.fmugen_runtime import setup_sys_path

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
ADAPTERS = {2: TEMPLATES_DIR / "model_fmi2.py", 3: TEMPLATES_DIR / "model_fmi3.py"}
RUNTIME = TEMPLATES_DIR / "fmugen_runtime.py"
LAUNCHER = TEMPLATES_DIR / "fmugen_launch.py"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "venv", ".venv")
FORMATS = ("fmu", "folder")

# By default the FMU runs with the Python fmugen is installed in: the model's own virtual
# environment, which has the model's packages and (as fmugen's dependencies) the UniFMU
# backend's. --vendor and --compile make FMUs for other machines (see distribute.py).
OSES = ("linux", "macos", "windows")
DEFAULT_PYTHON = {"linux": "python3", "macos": "python3", "windows": "python"}
CURRENT_OS = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
# What UniFMU 0.14's Python backend imports (its own requirements.txt lists more), plus fmugen's runtime
BACKEND_REQUIREMENTS = ["protobuf==5.27.3", "pyzmq", "cloudpickle"]   # cloudpickle: FMU state fallback

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


def _write_launch_toml(resources_dir, mode=None):
    """How UniFMU starts the backend on each OS.

    mode None: this interpreter on this OS (other OSes keep UniFMU's defaults);
    "vendor": the system Python runs fmugen_launch.py; "compile": the frozen executable.
    """
    if mode == "compile":
        commands = {system: compiled_launch_command(system) for system in OSES}
    elif mode == "vendor":
        commands = {system: [DEFAULT_PYTHON[system], "fmugen_launch.py"] for system in OSES}
    else:
        pythons = {**DEFAULT_PYTHON, CURRENT_OS: sys.executable}
        commands = {system: [pythons[system], "main.py"] for system in OSES}
    (resources_dir / "launch.toml").write_text(
        "".join(f"{system} = {json.dumps(commands[system])}\n" for system in OSES)
    )


def write_interface(interface, path):
    Path(path).write_text(json.dumps(interface, indent=2))


@contextlib.contextmanager
def isolated_imports():
    """Undo sys.path changes and forget modules loaded from the added paths.

    Building imports the user's code to inspect it (it is not run); this keeps one build
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
            # Read __dict__, not getattr: lazy modules (e.g. transformers) import on attribute access
            attrs = getattr(sys.modules[name], "__dict__", {})
            locations = [attrs.get("__file__"), *(attrs.get("__path__") or [])]
            if any(loc and Path(loc).resolve().is_relative_to(p) for loc in locations for p in added):
                del sys.modules[name]


def resolve_target(target, call=None, fmi_version=None, probe=False):
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
        data, _ = infer_config(target, call=call, fmi_version=fmi_version, probe=probe)
    return Config(data, model_path.parent if model_path else Path.cwd())


def _copy_sources(config, model_dir):
    for src, rel in config.source_files():
        dest = model_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, ignore=IGNORE, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dest)


def _prepare(config, resources, version, model_name, author, capture_output):
    """Copy a model's code into `resources`, import it and write its interface.json."""
    resources.mkdir(parents=True, exist_ok=True)
    _copy_sources(config, resources / MODEL_DIR)
    module, sys_path = config.entry_import()
    cwd = config.model_cwd()
    if cwd:
        (resources / cwd).mkdir(parents=True, exist_ok=True)
    with isolated_imports(), contextlib.chdir(resources / cwd if cwd else Path.cwd()):
        setup_sys_path({"sys_path": sys_path}, resources)
        try:
            entry_obj = getattr(importlib.import_module(module), config.entry_name)
        except (ImportError, AttributeError) as e:
            hint = " (install the model's requirements in the environment fmugen runs in)"                 if config.requirements else ""
            raise InterfaceError(f"cannot import {config.model['entry']}: {e!r}{hint}") from e
        interface = normalize(config, entry_obj, module, sys_path, model_name, author, version)
        interface["capture_output"] = bool(capture_output)
        for note in interface.pop("notes"):
            print(f"note: {note}")
    write_interface(interface, resources / "interface.json")
    return interface


def _flat(interface, resources):
    """The parts' variables and constants together (for --hf-weights), for a composite FMU."""
    if not interface.get("composite"):
        return interface
    parts = [json.loads((resources / p["dir"] / "interface.json").read_text()) for p in interface["parts"]]
    return {"variables": [v for p in parts for v in p["variables"]],
            "constants": {f"{i}.{k}": v for i, p in enumerate(parts) for k, v in p.get("constants", {}).items()},
            "call_constants": {f"{i}.{k}": v for i, p in enumerate(parts)
                               for k, v in p.get("call_constants", {}).items()}}


def build(target, output, model_name=None, author=None, output_format="fmu", call=None, fmi_version=None,
          vendor=False, platforms=(), python_versions=(), compiler=None, capture_output=False, probe=False,
          hf_weights=None):
    """Build an FMU. `vendor` (with `platforms`/`python_versions`) or `compiler` ("pyinstaller"
    or "nuitka") make it run on other machines; see distribute.py. `capture_output` sends what
    the model prints to the importer's log instead of the console."""
    if vendor and compiler:
        raise InterfaceError("--vendor and --compile exclude each other: a compiled FMU already contains its packages")
    if (platforms or python_versions) and not vendor:
        raise InterfaceError("--platform and --python-version only apply with --vendor")
    if compiler is not None and compiler not in COMPILERS:
        raise InterfaceError(f"unknown compiler {compiler!r}, expected one of {sorted(COMPILERS)}")
    if output_format not in FORMATS:
        raise ValueError(f"unknown output format {output_format!r}, expected one of {FORMATS}")
    output = Path(output)
    if output_format == "fmu" and output.is_dir():
        raise FileExistsError(f"{output} is a directory; cannot write an .fmu archive there")
    if output_format == "folder" and output.is_file():
        raise FileExistsError(f"{output} is a file; cannot write a folder there")

    composite_path = is_composite(target)
    if composite_path:
        if compiler:
            raise InterfaceError("--compile does not support composite FMUs yet; use --vendor")
        composite = Composite(composite_path)
        version = fmi_version or composite.fmi_version
        configs, base_dir = composite.parts, composite.path.parent
    else:
        config = resolve_target(target, call=call, fmi_version=fmi_version, probe=probe)
        version = config.fmi_version(fmi_version)
        configs, base_dir = {None: config}, config.base_dir
    if version not in ADAPTERS:
        raise InterfaceError(f"unknown FMI version {version!r}, expected one of {sorted(ADAPTERS)}")
    requirements = list(dict.fromkeys(r for c in configs.values() for r in c.requirements))

    with tempfile.TemporaryDirectory() as tmp:
        fmu_dir = Path(tmp) / "fmu"
        generate_boilerplate(version, fmu_dir)
        resources = fmu_dir / "resources"
        shutil.copy2(ADAPTERS[version], resources / "model.py")
        shutil.copy2(RUNTIME, resources / "fmugen_runtime.py")
        (resources / "requirements.txt").write_text(
            "# UniFMU backend\n" + "\n".join(BACKEND_REQUIREMENTS) + "\n"
            + ("# model requirements\n" + "\n".join(requirements) + "\n" if requirements else "")
        )
        if composite_path:
            parts = list(configs)
            interfaces = {
                # output capture redirects the process's console once: the last part's engine does it
                name: _prepare(cfg, resources / PARTS_DIR / name, version, None, None,
                               capture_output and name == parts[-1])
                for name, cfg in configs.items()
            }
            interface = combine(composite, interfaces, version, model_name, author)
        else:
            interface = _prepare(config, resources, version, model_name, author, capture_output)
        write_interface(interface, resources / "interface.json")

        write_model_description(interface, fmu_dir / "modelDescription.xml")
        if hf_weights if hf_weights is not None else (vendor or compiler):   # an FMU meant to run elsewhere
            for repo_id in bundle_hf_models(_flat(interface, resources), base_dir, resources):
                print(f"note: bundled the Hugging Face model {repo_id!r}; the FMU loads it offline")
        if vendor:
            shutil.copy2(LAUNCHER, resources / "fmugen_launch.py")
            vendor_wheels([*BACKEND_REQUIREMENTS, *requirements], resources / "wheels",
                          platforms, python_versions)
        if compiler:
            compile_fmu(compiler, resources, interface, Path(tmp) / "compile")
        _write_launch_toml(resources, "vendor" if vendor else "compile" if compiler else None)

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


def init(target, output=None, call=None, force=False, fmi_version=None, starts=None, setup=None, kind=None,
         create=None, probe=False, converts=None):
    """Write the inferred config to `output` (default: fmugen.toml next to the model; "-": stdout).

    The model is not called unless `probe` is set (init --probe)."""
    model_path, _, _ = parse_target(target)
    default_dir = model_path.parent if model_path else Path.cwd()
    to_stdout = output == "-"
    output = default_dir / "fmugen.toml" if (output is None or to_stdout) else Path(output)
    if output.exists() and not force and not to_stdout:
        raise FileExistsError(f"{output} already exists; pass --force to overwrite it, or -o - to print it")
    with isolated_imports():
        data, comments = infer_config(target, call=call, config_dir=output.parent, fmi_version=fmi_version,
                                      starts=starts, setup=setup, kind=kind, create=create, probe=probe,
                                      converts=converts)
    text = render_toml(data, comments)
    if to_stdout:
        sys.stdout.write(text)
        return None, data
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return output, data


def _parse_converts(items):
    """["NAME=module:function" | "NAME=numpy", ...] -> {NAME: converter}."""
    converts = {}
    for item in items:
        name, sep, converter = item.partition("=")
        name, converter = name.strip(), converter.strip()
        if not sep or not name.isidentifier() or not (converter == "numpy" or ":" in converter):
            raise InterfaceError(f"--convert {item!r}: expected NAME=module:function (e.g. x=torch:tensor) or NAME=numpy")
        converts[name] = converter
    return converts


def _parse_starts(items):
    import ast
    starts = {}
    for item in items:
        name, sep, text = item.partition("=")
        if not sep or not all(part.isidentifier() for part in name.strip().split(".")):   # NAME or ARG.FIELD
            raise InterfaceError(f"--start {item!r}: expected NAME=VALUE")
        text = text.strip()
        if text.startswith("call:"):   # a constant computed by a call, e.g. a downloaded file's path
            starts[name.strip()] = {"call": text[len("call:"):]}
            continue
        if text.lower() in ("true", "false"):   # TOML spelling, as in fmugen.toml
            starts[name.strip()] = text.lower() == "true"
            continue
        try:
            starts[name.strip()] = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            starts[name.strip()] = text  # a bare word: a string
    return starts


def main(argv=None):
    parser = argparse.ArgumentParser(prog="fmugen", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    i = sub.add_parser("init", help="write a fmugen.toml by inspecting a model",
                       description="Import the model, read its signatures and source code, and write a commented "
                                   "fmugen.toml to review. The model is not called unless --probe is given. "
                                   "See docs/models.md.")
    i.add_argument("model", help="model.py, model.py:Name, or package.module:Name")
    i.add_argument("-o", "--output", help="config path (default: fmugen.toml next to the model; - prints it)")
    i.add_argument("--call", help="method run on each step, for classes (default: step/do_step/update/__call__)")
    i.add_argument("--force", action="store_true", help="overwrite an existing config")
    i.add_argument("--fmi", type=int, choices=(2, 3), help="target FMI version; 3 also infers Binary, Float32 and resizable arrays")
    i.add_argument("--start", action="append", default=[], metavar="NAME=VALUE",
                   help="start/probe value for an argument (a Python literal), e.g. for arguments "
                        "without a default, or ARG.FIELD=VALUE for a field of an object argument; repeatable")
    i.add_argument("--setup", action="append", default=[], metavar="CALL",
                   help="run before the model is used, e.g. 'psychrolib:SetUnitSystem(psychrolib.SI)' "
                        "or 'reset' (a method, after construction); repeatable")
    i.add_argument("--create", metavar="CLASSMETHOD",
                   help="classes built by a factory: the classmethod that creates the object, "
                        "e.g. from_pretrained; its arguments become parameters")
    i.add_argument("--kind", choices=("function",),
                   help="function: treat a class whose constructor does the work as a function called every step")
    i.add_argument("--probe", action="store_true",
                   help="also call the model once (setup, construction, one step) with the start values, to find "
                        "what the code doesn't show: array sizes, exact types, results built at runtime, whether "
                        "its state can be saved. Without it, the model is never called")
    i.add_argument("--convert", action="append", default=[], metavar="NAME=module:function",
                   help="how an argument is passed to the model, e.g. x=torch:tensor or x=numpy; repeatable")

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
    b.add_argument("--probe", action="store_true",
                   help="when MODEL is a .py file: infer its config like init --probe (calls the model once)")
    b.add_argument("--vendor", action="store_true",
                   help="put wheels of every requirement into the FMU; it installs them offline on its first "
                        "run on a machine (the target needs Python, not this environment)")
    b.add_argument("--platform", action="append", default=[], metavar="TAG",
                   help="with --vendor: also vendor wheels for this platform, e.g. win_amd64, "
                        "manylinux2014_x86_64, macosx_11_0_arm64; repeatable (default: this machine)")
    b.add_argument("--python-version", action="append", default=[], metavar="X.Y",
                   help="with --vendor: vendor wheels for this Python version; repeatable (default: this one)")
    b.add_argument("--compile", choices=sorted(COMPILERS),
                   help="freeze the model, its packages and Python into an executable: the FMU contains no "
                        "source code and needs no Python, but only runs on this OS")
    b.add_argument("--fmi", type=int, choices=(2, 3), help="FMI version (default: [model] fmi_version, else 2)")
    b.add_argument("--hf-weights", action=argparse.BooleanOptionalAction, default=None,
                   help="put the Hugging Face models the model loads (string parameters such as "
                        "\"amazon/chronos-bolt-tiny\") into the FMU, which then loads them offline "
                        "(default: on with --vendor and --compile)")
    b.add_argument("--capture-output", action="store_true",
                   help="send what the model prints (stdout/stderr) to the importer's log instead of the "
                        "console; use it when the model prints more than a few KB, which hangs UniFMU 0.14")

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            output, data = init(args.model, args.output, args.call, args.force, args.fmi,
                                _parse_starts(args.start), args.setup, args.kind, args.create, args.probe,
                                _parse_converts(args.convert))
            if output:
                print(f"Wrote {output.resolve()}; review it, then run: fmugen build {output}")
            return
        output, interface = build(args.model, args.output, args.name, args.author,
                                  args.format, args.call, args.fmi, args.vendor, args.platform,
                                  args.python_version, args.compile, args.capture_output, args.probe,
                                  args.hf_weights)
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
