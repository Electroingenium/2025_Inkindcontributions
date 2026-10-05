"""Making an FMU run on other machines: vendored wheels (--vendor) or a frozen executable (--compile).

By default an FMU runs with the virtual environment fmugen was installed in, so it only
works where it was built. Two ways to ship it elsewhere:

- `vendor()`: wheels of every requirement go into resources/wheels/. The FMU starts
  through fmugen_launch.py, which builds a cached virtual environment from them on its
  first run, offline. The target needs a Python interpreter.
- `compile_fmu()`: PyInstaller or Nuitka freezes the backend, the adapter, the runtime
  and the model, with the interpreter and every package, into resources/dist/main/.
  No .py files are shipped and the target needs no Python, but the executable only runs
  on the OS (and architecture) it was built on.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

from fmugen.config import MODEL_DIR, InterfaceError

COMPILERS = {"pyinstaller": "PyInstaller", "nuitka": "nuitka"}   # --compile value -> module
EXE_DIR = "dist/main"   # resources/dist/main/: the frozen backend
EXE_NAME = "main"
# What stays in resources/ after compiling; everything else is inside the executable
KEEP_AFTER_COMPILE = {"dist", "launch.toml"}


# ---------------- --vendor ----------------

def _pip():
    """Command prefix that runs pip (the environment's, else pip through uvx)."""
    if importlib.util.find_spec("pip"):
        return [sys.executable, "-m", "pip"]
    uvx = shutil.which("uvx")
    if uvx:
        return [uvx, "pip"]
    raise InterfaceError("--vendor needs pip: install it in this environment (pip is missing from uv venvs), "
                         "or install uv")


def vendor(requirements, wheels_dir, platforms=(), python_versions=()):
    """Put wheels for `requirements` (and their dependencies) into wheels_dir.

    Without targets, wheels are made for this machine and Python; packages published only
    as source are built into wheels here, so the target needs no compiler. With targets,
    each platform and Python version is downloaded separately, and only published wheels
    can be used.
    """
    pip = [*_pip(), "--disable-pip-version-check"]
    if not platforms and not python_versions:
        commands = [[*pip, "wheel", "--quiet", "--wheel-dir", str(wheels_dir), *requirements]]
    else:
        commands = []
        for platform in platforms or [None]:
            for version in python_versions or [None]:
                cmd = [*pip, "download", "--quiet", "--only-binary=:all:", "--dest", str(wheels_dir)]
                cmd += ["--platform", platform] if platform else []
                cmd += ["--python-version", version] if version else []
                commands.append(cmd + list(requirements))
    for cmd in commands:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise InterfaceError(f"vendoring {requirements} failed ({' '.join(cmd[len(pip):])}):\n"
                                 f"{result.stdout}{result.stderr}")


# ---------------- --compile ----------------

def compile_fmu(compiler, resources, interface, work):
    """Freeze resources/main.py and everything it runs into resources/dist/main/; drop the sources."""
    module = COMPILERS[compiler]
    if not importlib.util.find_spec(module):
        raise InterfaceError(f"--compile {compiler} needs {module} in this environment: "
                             f"pip install {compiler} (or pip install fmugen[{compiler}])")
    resources, work = Path(resources), Path(work)
    work.mkdir(parents=True, exist_ok=True)
    paths = [resources, *(resources / p for p in interface["sys_path"])]
    modules = _modules(interface)
    data = [(resources / "interface.json", ".")] + _model_data(resources, interface)

    if compiler == "pyinstaller":
        cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--log-level", "WARN", "--name", EXE_NAME,
               "--distpath", str(work / "dist"), "--workpath", str(work / "build"), "--specpath", str(work)]
        cmd += [arg for p in paths for arg in ("--paths", str(p))]
        cmd += [arg for m in modules for arg in ("--hidden-import", m)]
        cmd += [arg for src, dest in data for arg in ("--add-data", f"{src}{os.pathsep}{dest}")]
        built = work / "dist" / EXE_NAME
        env = None
    else:
        cmd = [sys.executable, "-m", "nuitka", "--standalone", "--assume-yes-for-downloads", "--quiet",
               f"--output-dir={work}", f"--output-filename={EXE_NAME}"]
        cmd += [f"--include-module={m}" for m in modules]
        cmd += [f"--include-data-files={src}={Path(dest, src.name).as_posix()}" for src, dest in data]
        built = work / "main.dist"
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(map(str, paths))}
    cmd.append(str(resources / "main.py"))

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=work, env=env)
    if result.returncode != 0 or not built.is_dir():
        raise InterfaceError(f"--compile {compiler} failed:\n{result.stdout[-4000:]}{result.stderr[-4000:]}")

    for item in resources.iterdir():
        if item.name not in KEEP_AFTER_COMPILE:
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    shutil.move(str(built), str(resources / EXE_DIR))


def compiled_launch_command(system):
    """launch.toml entry for the frozen backend (relative paths need a shell to resolve)."""
    if system == "windows":
        return ["powershell", "-command", f"./{EXE_DIR}/{EXE_NAME}.exe"]
    exe = f"{EXE_DIR}/{EXE_NAME}"
    return ["sh", "-c", f"chmod +x {exe} && ./{exe}"]


def _modules(interface):
    """Modules the runtime imports by name, which a freezer can't find by itself."""
    modules = {"model", "fmugen_runtime", interface["entry"]["module"]}
    refs = [step["call"] for step in interface.get("setup", [])]
    refs += [td["enum"] for td in interface.get("type_definitions", {}).values() if td.get("enum")]
    refs += [c["call"] for c in interface.get("clocks", []) if c.get("call")]
    for table in ("constants", "call_constants"):
        refs += [v["ref"] for v in interface.get(table, {}).values() if isinstance(v, dict) and "ref" in v]
    for step in interface.get("setup", []):
        refs += [a["ref"] for a in [*step.get("args", []), *step.get("kwargs", {}).values()]
                 if isinstance(a, dict) and "ref" in a]
    for ref in refs:
        if ":" in ref:
            modules.add(ref.partition(":")[0])
        elif "." in ref:
            modules.add(ref.split(".")[0])
    return sorted(modules)


def _model_data(resources, interface):
    """Non-Python files of the model, placed where the model's modules will look for them."""
    roots = sorted((resources / p for p in interface["sys_path"]), key=lambda p: len(p.parts), reverse=True)
    data = []
    model_dir = resources / MODEL_DIR
    if not model_dir.is_dir():
        return data
    for file in model_dir.rglob("*"):
        if file.is_dir() or file.suffix in (".py", ".pyc") or "__pycache__" in file.parts:
            continue
        root = next((r for r in roots if file.is_relative_to(r)), None)
        if root is not None:
            data.append((file, file.parent.relative_to(root).as_posix() or "."))
    return data
