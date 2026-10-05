"""fmugen FMU launcher for vendored FMUs (fmugen build --vendor).

UniFMU runs this file (see launch.toml) instead of main.py. The first time the FMU
runs on a machine, it creates a virtual environment from the wheels in
resources/wheels/, without a network connection, and caches it. Then it runs
UniFMU's main.py with that environment's Python. Later runs, and other FMUs with
the same wheels, reuse the environment.

The cache is in FMUGEN_ENV_DIR if set, else the user cache folder
(%LOCALAPPDATA%\\fmugen\\envs, ~/Library/Caches/fmugen/envs, ~/.cache/fmugen/envs).

Only the standard library is used, so that any Python 3.8+ can run it.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(HERE, "requirements.txt")
WHEELS = os.path.join(HERE, "wheels")


def say(message):
    sys.stderr.write("[fmugen] " + message + "\n")
    sys.stderr.flush()


def cache_dir():
    if os.environ.get("FMUGEN_ENV_DIR"):
        return os.environ["FMUGEN_ENV_DIR"]
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "fmugen", "envs")


def env_key():
    """Same requirements, wheels and interpreter -> same environment."""
    h = hashlib.sha256()
    with open(REQUIREMENTS, "rb") as f:
        h.update(f.read())
    h.update("\n".join(sorted(os.listdir(WHEELS))).encode())
    h.update(sys.version.encode())
    h.update(os.path.realpath(sys.executable).encode())
    return h.hexdigest()[:16]


def env_python(env):
    if sys.platform == "win32":
        return os.path.join(env, "Scripts", "python.exe")
    return os.path.join(env, "bin", "python")


def run(cmd):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    if result.returncode != 0:
        raise RuntimeError("command failed: " + " ".join(cmd) + "\n" + result.stdout)


def create(env):
    offline = ["--no-index", "--find-links", WHEELS, "-r", REQUIREMENTS]
    uv = shutil.which("uv")
    if uv:
        run([uv, "venv", "--quiet", "--python", sys.executable, env])
        run([uv, "pip", "install", "--quiet", "--python", env_python(env)] + offline)
    else:
        run([sys.executable, "-m", "venv", env])
        run([env_python(env), "-m", "pip", "install", "--quiet", "--disable-pip-version-check"] + offline)


def ensure_env():
    root = cache_dir()
    env = os.path.join(root, env_key())
    if os.path.exists(os.path.join(env, ".complete")):
        return env
    os.makedirs(root, exist_ok=True)
    say("installing this FMU's packages into " + env + " (first run only)")
    # Build in a private folder and rename it into place, so FMU instances started at
    # the same time never see a half-installed environment.
    tmp = tempfile.mkdtemp(prefix="tmp-", dir=root)
    try:
        create(tmp)
        open(os.path.join(tmp, ".complete"), "w").close()
        try:
            os.rename(tmp, env)
        except OSError:
            if not os.path.exists(os.path.join(env, ".complete")):
                raise
            # another instance finished first; use its environment
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return env


def main():
    try:
        env = ensure_env()
    except Exception as e:
        say("cannot install this FMU's packages: " + str(e))
        say("the FMU may have no wheels for this platform or Python version; rebuild it with "
            "fmugen build --vendor --platform ... --python-version ...")
        return 1
    return subprocess.call([env_python(env), os.path.join(HERE, "main.py")], cwd=HERE)


if __name__ == "__main__":
    sys.exit(main())
