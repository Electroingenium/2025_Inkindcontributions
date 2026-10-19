"""Build and init: packaging Python models into FMUs via UniFMU."""
import atexit
import contextlib
import importlib
import importlib.util
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
from fmugen.description import build_time, stamp_guid, write_model_description
from fmugen.distribute import (
    COMPILERS,
    bundle_hf_models,
    compile_fmu,
    compiled_launch_command,
)
from fmugen.distribute import vendor as vendor_wheels
from fmugen.interface import import_failure, infer_config, parse_target
from fmugen.arguments import assumptions, guessed_outputs, unfit_outputs
from fmugen.toml_output import render_toml
from fmugen.templates.fmugen_runtime import setup_sys_path

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
ADAPTERS = {2: TEMPLATES_DIR / "model_fmi2.py", 3: TEMPLATES_DIR / "model_fmi3.py"}
RUNTIME = TEMPLATES_DIR / "fmugen_runtime.py"
LAUNCHER = TEMPLATES_DIR / "fmugen_launch.py"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "venv", ".venv")
FORMATS = ("fmu", "folder")

OSES = ("linux", "macos", "windows")
DEFAULT_PYTHON = {"linux": "python3", "macos": "python3", "windows": "python"}
CURRENT_OS = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
BACKEND_REQUIREMENTS = ["protobuf==5.27.3", "pyzmq", "cloudpickle"]
DISTRIBUTED_REQUIREMENTS = ["toml", "coloredlogs", "colorama"]

UNIFMU_VERSION = "0.14.0"
UNIFMU_ENV = "FMUGEN_UNIFMU"
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


_templates = {}


def _template(args, check):
    """Run `unifmu *args` once per process, in a cached folder, and return that folder."""
    exe = find_unifmu()
    key = (exe, *args)
    if key not in _templates:
        folder = Path(tempfile.mkdtemp(prefix="fmugen-unifmu-"))
        atexit.register(shutil.rmtree, folder, ignore_errors=True)
        result = subprocess.run([exe, *args], capture_output=True, text=True, cwd=folder)
        if result.returncode != 0 or not check(folder):
            shutil.rmtree(folder, ignore_errors=True)
            raise InterfaceError(f"`unifmu {' '.join(args)}` failed:\n{result.stdout}{result.stderr}")
        _templates[key] = folder
    return _templates[key]


def _link_or_copy(src, dst):
    """Hard-link UniFMU binaries when possible (avoids virus scanner rescan), else copy."""
    if "binaries" in Path(src).parts:
        try:
            os.link(src, dst)
            return dst
        except OSError:
            pass
    return shutil.copy2(src, dst)


def generate_boilerplate(fmi_version, dest):
    """Write UniFMU's Python FMU template for `fmi_version` (2 or 3) to `dest`."""
    template = _template(["generate", "python", "out", f"fmi{fmi_version}"],
                         lambda folder: (folder / "out" / "resources").is_dir())
    shutil.copytree(template / "out", dest, copy_function=_link_or_copy)


def generate_distributed_boilerplate(fmi_version, dest, endpoint):
    """Write UniFMU's distributed Python template for `fmi_version` into `dest`."""
    template = _template(["generate-distributed", "python", "x", f"fmi{fmi_version}", "--endpoint", endpoint],
                         lambda folder: (folder / "x_proxy" / "resources" / "launch.toml").is_file()
                         and (folder / "x_private" / "main.py").is_file())
    dest = Path(dest)
    shutil.copytree(template, dest, copy_function=_link_or_copy, dirs_exist_ok=True)
    return dest / "x_proxy", dest / "x_private"


def private_start_command(mode=None):
    """How to start a distributed FMU's private side from its folder."""
    if mode == "compile":
        return r".\dist\main\main.exe PORT" if CURRENT_OS == "windows" else "./dist/main/main PORT"
    return f"{DEFAULT_PYTHON[CURRENT_OS]} {'fmugen_launch.py' if mode == 'vendor' else 'main.py'} PORT"


def _write_private_readme(private, model_name, endpoint, mode=None):
    packages = {None: "\nThe Python running it needs the packages in requirements.txt.\n",
                "vendor": "\nfmugen_launch.py installs the packages from wheels/ on its first run.\n",
                "compile": ""}[mode]
    (private / "README.md").write_text(
        f"# {model_name}: private side of a distributed FMU\n\n"
        f"Built by fmugen with UniFMU {UNIFMU_VERSION}. The FMU the importer loads is only a proxy;\n"
        "this folder runs the model and connects to it over TCP. See fmugen's docs/packaging.md.\n\n"
        "1. Start the simulation with the proxy FMU, with logging on for the `logUnifmuMessages`\n"
        f"   category. The proxy, on the host {endpoint} (see endpoint.toml), logs:\n\n"
        "       ACTION REQUIRED ~ Connect remote backend to dispatcher through port: PORT\n\n"
        "   UniFMU 0.14 picks a new port on every run, and it can't be set.\n"
        f"2. In this folder, run:\n\n       {private_start_command(mode)}\n" + packages,
        encoding="utf-8")


def _write_launch_toml(resources_dir, mode=None):
    """How UniFMU starts the backend on each OS."""
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
    """Undo sys.path changes and forget modules loaded from the added paths."""
    saved_path = list(sys.path)
    saved_modules = set(sys.modules)
    try:
        yield
    finally:
        added = [Path(p).resolve() for p in sys.path if p and p not in saved_path]
        sys.path[:] = saved_path
        to_forget = []
        for name in set(sys.modules) - saved_modules:
            attrs = getattr(sys.modules[name], "__dict__", {})
            try:
                locations = [attrs.get("__file__"), *(attrs.get("__path__") or [])]
            except KeyError:
                locations = [attrs.get("__file__")]
            if any(loc and Path(loc).resolve().is_relative_to(p) for loc in locations for p in added):
                to_forget.append(name)
        for name in to_forget:
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
    config.check_module_names()
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
            hint = (" (install the model's requirements in the environment fmugen runs in)"
                    if config.requirements else "")
            raise InterfaceError(f"cannot import {config.model['entry']}: {e!r}{hint}") from e
        except (Exception, SystemExit) as e:
            raise import_failure(config.model["entry"], e) from e
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


def _write_zip(fmu_dir, output):
    """Zip fmu_dir reproducibly."""
    date_time = build_time().timetuple()[:6] if "SOURCE_DATE_EPOCH" in os.environ else (1980, 1, 1, 0, 0, 0)
    date_time = max(date_time, (1980, 1, 1, 0, 0, 0))
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file in sorted(fmu_dir.rglob("*")):
            if file.is_file() and "__pycache__" not in file.parts:
                info = zipfile.ZipInfo(file.relative_to(fmu_dir).as_posix(), date_time)
                info.compress_type = zipfile.ZIP_DEFLATED
                if os.name == "nt":
                    executable = "binaries" in file.relative_to(fmu_dir).parts or file.suffix in (".exe", ".sh")
                else:
                    executable = bool(file.stat().st_mode & 0o111)
                info.external_attr = (0o100755 if executable else 0o100644) << 16
                with open(file, "rb") as src, zipf.open(info, "w", force_zip64=True) as dst:
                    shutil.copyfileobj(src, dst)


def _replace(output, write):
    """Call write(path) on a new path next to `output`, then put it in place atomically."""
    new = output.with_name(f".{output.name}.new")
    old = output.with_name(f".{output.name}.old")
    for leftover in (new, old):
        if leftover.is_dir():
            shutil.rmtree(leftover)
        else:
            leftover.unlink(missing_ok=True)
    try:
        write(new)
    except BaseException:
        shutil.rmtree(new, ignore_errors=True) if new.is_dir() else new.unlink(missing_ok=True)
        raise
    if output.is_dir():
        output.rename(old)
        new.rename(output)
        shutil.rmtree(old)
    else:
        os.replace(new, output)


def build(target, output, model_name=None, author=None, output_format="fmu", call=None, fmi_version=None,
          vendor=False, platforms=(), python_versions=(), compiler=None, capture_output=False, probe=False,
          hf_weights=None, distributed=False, endpoint=None, private_output=None):
    """Build an FMU."""
    if (endpoint or private_output) and not distributed:
        raise InterfaceError("--endpoint and --private-output only apply with --distributed")
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
    if distributed:
        endpoint = endpoint or "127.0.0.1"
        private_output = Path(private_output) if private_output else output.with_name(output.stem + "_private")
        if private_output.resolve() == output.resolve():
            raise FileExistsError(f"{private_output} is the proxy FMU's path; give --private-output another one")
        if private_output.is_file():
            raise FileExistsError(f"{private_output} is a file; cannot write the private folder there")

    composite_path = is_composite(target)
    if composite_path:
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
    backend_requirements = BACKEND_REQUIREMENTS + (DISTRIBUTED_REQUIREMENTS if distributed else [])

    with tempfile.TemporaryDirectory() as tmp:
        if distributed:
            fmu_dir, resources = generate_distributed_boilerplate(version, Path(tmp) / "unifmu", endpoint)
        else:
            fmu_dir = Path(tmp) / "fmu"
            generate_boilerplate(version, fmu_dir)
            resources = fmu_dir / "resources"
        shutil.copy2(ADAPTERS[version], resources / "model.py")
        shutil.copy2(RUNTIME, resources / "fmugen_runtime.py")
        (resources / "requirements.txt").write_text(
            "# UniFMU backend\n" + "\n".join(backend_requirements) + "\n"
            + ("# model requirements\n" + "\n".join(requirements) + "\n" if requirements else "")
        )
        if composite_path:
            parts = list(configs)
            interfaces = {
                name: _prepare(cfg, resources / PARTS_DIR / name, version, None, None,
                               capture_output and name == parts[-1])
                for name, cfg in configs.items()
            }
            interface = combine(composite, interfaces, version, model_name, author)
        else:
            interface = _prepare(config, resources, version, model_name, author, capture_output)
        write_interface(interface, resources / "interface.json")

        write_model_description(interface, fmu_dir / "modelDescription.xml")
        if hf_weights if hf_weights is not None else (vendor or compiler):
            for repo_id in bundle_hf_models(_flat(interface, resources), base_dir, resources):
                print(f"note: bundled the Hugging Face model {repo_id!r}; the FMU loads it offline")
        if vendor:
            shutil.copy2(LAUNCHER, resources / "fmugen_launch.py")
            vendor_wheels([*backend_requirements, *requirements], resources / "wheels",
                          platforms, python_versions)
        if compiler:
            compile_fmu(compiler, resources, interface, Path(tmp) / "compile", requirements)
        mode = "vendor" if vendor else "compile" if compiler else None
        if distributed:
            _write_private_readme(resources, interface["model_name"], endpoint, mode)
            missing = [r for r in DISTRIBUTED_REQUIREMENTS if not importlib.util.find_spec(r)]
            if missing and not mode:
                print(f"note: the private side's main.py imports {', '.join(missing)}, which this environment "
                      "lacks: pip install fmugen[distributed] where it runs")
        else:
            _write_launch_toml(resources, mode)

        stamp_guid(fmu_dir)

        output.parent.mkdir(parents=True, exist_ok=True)
        if output_format == "fmu":
            _replace(output, lambda path: _write_zip(fmu_dir, path))
        else:
            _replace(output, lambda path: shutil.copytree(fmu_dir, path, ignore=IGNORE))
        if distributed:
            private_output.parent.mkdir(parents=True, exist_ok=True)
            _replace(private_output, lambda path: shutil.copytree(resources, path, ignore=IGNORE))
            interface = {**interface, "private_output": private_output, "private_start": private_start_command(mode)}

    return output, interface


NO_OUTPUTS = "no outputs found: add [outputs] by hand (e.g. attributes or properties of the model object)"


def init(target, output=None, call=None, force=False, fmi_version=None, starts=None, setup=None, kind=None,
         create=None, probe=False, converts=None):
    """Write the inferred config to `output` (default: fmugen.toml next to the model; "-": stdout)."""
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
    for warning in _init_warnings(data, comments, probe):
        print(f"warning: {warning}", file=sys.stderr)
    text = render_toml(data, comments)
    if to_stdout:
        sys.stdout.write(text)
        return None, data
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return output, data


def _init_warnings(data, comments, probe):
    warnings = assumptions(comments)
    outputs = data.get("outputs", {})
    if not outputs:
        warnings.append(NO_OUTPUTS)
        comments.setdefault(("outputs", None), NO_OUTPUTS)
    guessed = guessed_outputs(data, comments)
    if guessed:
        warnings.append(f"{_names(guessed)}: type not shown by the code, assumed a single Real; "
                        + ("set type = ... if that's wrong" if probe else
                           "it may be an array or a tuple, which fails the step: run init --probe, "
                           "or set type = ... / dimensions = [...]"))
    by_reason = {}
    for name, why in unfit_outputs(comments).items():
        by_reason.setdefault(why, []).append(name)
    for why, names in by_reason.items():
        warnings.append(f"{_names(names)}: left commented out in the config, since {why}")
    return warnings


def _names(names):
    return ", ".join(names[:8]) + (f" and {len(names) - 8} more" if len(names) > 8 else "")
