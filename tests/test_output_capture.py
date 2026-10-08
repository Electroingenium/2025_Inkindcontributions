"""fmugen build --capture-output: a model that prints a lot must not crash UniFMU.

UniFMU 0.14 panics (zeromq rep.rs: not yet implemented) and the importer hangs when the
backend writes more than about 4 KB to the console. With --capture-output, the runtime
captures that output and forwards it to the importer's log instead. The FMU runs in a
subprocess with a timeout, so a regression fails instead of hanging the test run.
"""
import subprocess
import sys
import textwrap

from fmugen.__main__ import build

SIMULATE = textwrap.dedent("""
    import sys
    from fmpy import simulate_fmu
    logs = []
    result = simulate_fmu(sys.argv[1], stop_time=2, output=["y"],
                          logger=lambda *args: logs.append(args[-1]), debug_logging=True)
    printed = [m for m in logs if (m.decode() if isinstance(m, bytes) else m).startswith("[output]")]
    print("OK", result["y"][-1], len(printed))
""")


def test_large_console_output_reaches_the_log_instead_of_crashing(tmp_path):
    (tmp_path / "noisy.py").write_text(textwrap.dedent("""
        import sys
        def noisy(u=1.0):
            print("p" * 20000)                      # stdout
            sys.stderr.write("e" * 20000 + "\\n")    # stderr, like warnings and progress bars
            return {"y": 2 * u}
    """))
    fmu = build(tmp_path / "noisy.py", tmp_path / "noisy.fmu", capture_output=True)[0]
    (tmp_path / "simulate.py").write_text(SIMULATE)
    log = tmp_path / "simulate.log"
    with log.open("w") as out:   # a file, not a pipe: a hung backend would keep a pipe open past the timeout
        try:
            subprocess.run([sys.executable, str(tmp_path / "simulate.py"), str(fmu)],
                           stdout=out, stderr=subprocess.STDOUT, timeout=120)
        except subprocess.TimeoutExpired:
            pass
    text = log.read_text(errors="replace")
    ok = [line for line in text.splitlines() if line.startswith("OK")]
    assert ok, "the FMU hung or failed:\n" + text[-2000:]
    _, y, printed = ok[0].split()
    assert float(y) == 2.0 and int(printed) > 0


def test_output_goes_to_the_console_by_default(tmp_path):
    import json
    import zipfile
    (tmp_path / "quiet.py").write_text("def quiet(u=1.0):\n    return {'y': u}\n")
    for flag in (False, True):
        fmu = build(tmp_path / "quiet.py", tmp_path / f"quiet{flag}.fmu", capture_output=flag)[0]
        with zipfile.ZipFile(fmu) as z:
            assert json.loads(z.read("resources/interface.json"))["capture_output"] is flag
