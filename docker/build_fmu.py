"""Image build step: put the FMU at /model/model.fmu.

Builds MODEL with fmugen and UniFMU's Linux CLI, after installing the model's
[model] requirements, or copies docker/model/model.fmu when PREBUILT=1.
"""
import io
import os
import shutil
import stat
import subprocess
import sys
import tomllib
import urllib.request
import zipfile
from pathlib import Path

Path("/model").mkdir(exist_ok=True)
if os.environ["PREBUILT"] == "1":
    shutil.copy("/src/docker/model/model.fmu", "/model/model.fmu")
    sys.exit()

model = Path("/src") / os.environ["MODEL"]
config = model / "fmugen.toml" if model.is_dir() else model
requirements = tomllib.loads(config.read_text())["model"].get("requirements", []) if config.suffix == ".toml" else []
if requirements:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", *requirements])

version = os.environ["UNIFMU_VERSION"]
url = f"https://github.com/INTO-CPS-Association/unifmu/releases/download/v{version}/unifmu-x86_64-unknown-linux-gnu-{version}.zip"
with zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(url).read())) as z:
    name = next(n for n in z.namelist() if Path(n).name == "unifmu")
    unifmu = Path("/tmp/unifmu")
    unifmu.write_bytes(z.read(name))
unifmu.chmod(unifmu.stat().st_mode | stat.S_IEXEC)

env = {**os.environ, "FMUGEN_UNIFMU": str(unifmu)}
args = os.environ["FMUGEN_ARGS"].split()
subprocess.check_call(["fmugen", "build", str(model), "-o", "/model/model.fmu", *args], env=env)
unifmu.unlink()
