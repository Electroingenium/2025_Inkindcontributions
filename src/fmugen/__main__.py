"""fmugen CLI.

    python -m fmugen build path/to/model.py -o out/model.fmu   # packaged FMU
    python -m fmugen build path/to/model.py -o out/model       # unzipped UniFMU folder
"""
import argparse
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from fmugen.description import write_model_description
from fmugen.interface import load_interface, write_interface

PACKAGE_DIR = Path(__file__).resolve().parent
BOILERPLATE_DIR = PACKAGE_DIR.parent / "fmu"
TEMPLATE_MODEL = PACKAGE_DIR / "templates" / "model.py"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "venv", ".venv")


def _write_launch_toml(resources_dir, python_exec):
    python_exec = python_exec.replace("\\", "/")
    (resources_dir / "launch.toml").write_text(
        'linux = ["python3", "main.py"]\n'
        'macos = ["python3", "main.py"]\n'
        f'windows = ["{python_exec}", "main.py"]\n'
    )


def build(model_path, output, model_name=None, author="", python_exec=None):
    model_path = Path(model_path).resolve()
    output = Path(output)

    interface = load_interface(model_path)

    with tempfile.TemporaryDirectory() as tmp:
        fmu_dir = Path(tmp) / "fmu"
        shutil.copytree(BOILERPLATE_DIR, fmu_dir, ignore=IGNORE)
        resources = fmu_dir / "resources"

        shutil.copy2(TEMPLATE_MODEL, resources / "model.py")
        shutil.copy2(model_path, resources / model_path.name)
        write_interface(interface, resources / "interface.json")
        write_model_description(
            interface, fmu_dir / "modelDescription.xml",
            model_name=model_name, author=author,
        )
        if python_exec:
            _write_launch_toml(resources, python_exec)

        output.parent.mkdir(parents=True, exist_ok=True)
        if output.suffix == ".fmu":
            output.unlink(missing_ok=True)
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zipf:
                for file in sorted(fmu_dir.rglob("*")):
                    zipf.write(file, arcname=file.relative_to(fmu_dir).as_posix())
        else:
            if output.exists():
                shutil.rmtree(output)
            shutil.copytree(fmu_dir, output)

    return output, interface


def main(argv=None):
    parser = argparse.ArgumentParser(prog="fmugen", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="build a UniFMU from a Python model")
    b.add_argument("model", help="path to the model .py file")
    b.add_argument("-o", "--output", required=True,
                   help="output path; ending in .fmu produces a zip, otherwise a folder")
    b.add_argument("--name", help="modelName in modelDescription.xml (default: module name)")
    b.add_argument("--author", default="")
    b.add_argument("--python", nargs="?", const=sys.executable, default=None,
                   help="python executable written into launch.toml for Windows "
                        "(flag alone = the current interpreter; omitted = keep boilerplate 'python')")

    args = parser.parse_args(argv)
    output, interface = build(args.model, args.output, args.name, args.author, args.python)

    counts = {}
    for v in interface["variables"]:
        counts[v["causality"]] = counts.get(v["causality"], 0) + 1
    summary = ", ".join(f"{n} {c}s" for c, n in counts.items())
    print(f"Built {output.resolve()} ({summary})")


if __name__ == "__main__":
    main()
