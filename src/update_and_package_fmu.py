"""Build a UniFMU from a Python model (see src/fmugen).

Usage:
    python src/update_and_package_fmu.py build src/fmu_psycrometry.py -o out/psycrometry.fmu
"""
from fmugen.__main__ import main

if __name__ == "__main__":
    main()
