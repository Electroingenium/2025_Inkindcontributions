"""FMU variables as seen by the stack: shared by the OPC UA server, the runner and the UI.

Works for FMI 2 and FMI 3 FMUs. FMI 3 arrays become OPC UA arrays; Binary and Clock
variables are not exposed over OPC UA.
"""
import logging

from fmpy import read_model_description
from opcua import ua

NAMESPACE_URI = "urn:eium:opcua:fmu"
RESULTS_BEGIN = "----- BEGIN RESULTS CSV -----"
RESULTS_END = "----- END RESULTS CSV -----"


def run_timeout(start_time, stop_time, step_size, step_delay, setting=None):
    """Seconds a run may take before it is stopped: RUN_TIMEOUT if set (0: no limit), else 10 minutes
    (for loading the model, which may compile code on first use) plus twice the paced stepping time."""
    if setting not in (None, ""):
        return float(setting)
    steps = max(0.0, stop_time - start_time) / step_size if step_size > 0 else 0.0
    return 600.0 + 2.0 * steps * step_delay

logger = logging.getLogger("fmu_io")

# FMI type -> (OPC UA type, Python type, FMI get/set suffix)
TYPES = {
    # FMI 2
    "Real": (ua.VariantType.Double, float, "Real"),
    "Integer": (ua.VariantType.Int32, int, "Integer"),
    # FMI 3
    "Float64": (ua.VariantType.Double, float, "Float64"),
    "Float32": (ua.VariantType.Float, float, "Float32"),
    "Int8": (ua.VariantType.SByte, int, "Int8"),
    "UInt8": (ua.VariantType.Byte, int, "UInt8"),
    "Int16": (ua.VariantType.Int16, int, "Int16"),
    "UInt16": (ua.VariantType.UInt16, int, "UInt16"),
    "Int32": (ua.VariantType.Int32, int, "Int32"),
    "UInt32": (ua.VariantType.UInt32, int, "UInt32"),
    "Int64": (ua.VariantType.Int64, int, "Int64"),
    "UInt64": (ua.VariantType.UInt64, int, "UInt64"),
    # both
    "Boolean": (ua.VariantType.Boolean, bool, "Boolean"),
    "String": (ua.VariantType.String, str, "String"),
}


class Var:
    """One FMU input/parameter or output: name, type, value reference, size (None = scalar)."""

    def __init__(self, mv, fmi3, size):
        self.name = mv.name
        self.causality = mv.causality
        # what can change between steps: inputs and tunable parameters
        self.tunable = mv.causality == "input" or mv.variability == "tunable"
        self.vr = mv.valueReference
        self.size = size
        fmi_type = mv.type
        if fmi_type == "Enumeration":   # FMI 2 enumerations are Integers, FMI 3 ones Int64
            fmi_type = "Int64" if fmi3 else "Integer"
        self.ua_type, self.py_type, self.suffix = TYPES[fmi_type]
        self.start = self._parse_start(mv.start)

    def _parse_start(self, start):
        def one(text):
            if self.py_type is bool:
                return text.strip().lower() in ("true", "1")
            return self.py_type(text)

        if self.size is None:
            return one(start) if start is not None else self.py_type()
        if start is None:
            return [self.py_type()] * self.size
        items = start.split()
        return [one(t) for t in items] if len(items) == self.size else [one(items[0])] * self.size

    def variant(self, value):
        return ua.Variant(value, self.ua_type)


def _array_size(mv, by_vr):
    """Number of elements of an FMI 3 array, or None for a scalar."""
    if not mv.dimensions:
        return None
    size = 1
    for dim in mv.dimensions:
        if dim.start is not None:
            size *= int(dim.start)
        else:   # sized by a structural parameter
            size *= int(by_vr[dim.valueReference].start)
    return size


def read_fmu(fmu_path):
    """Return (model_description, inputs, outputs). Inputs are inputs and parameters."""
    md = read_model_description(fmu_path)
    fmi3 = md.fmiVersion.startswith("3")
    by_vr = {v.valueReference: v for v in md.modelVariables}
    inputs, outputs = [], []
    for mv in md.modelVariables:
        if mv.causality not in ("input", "parameter", "output"):
            continue
        if mv.type not in TYPES and mv.type != "Enumeration":
            logger.warning(f"{mv.name}: {mv.type} variables are not exposed over OPC UA")
            continue
        var = Var(mv, fmi3, _array_size(mv, by_vr))
        (outputs if mv.causality == "output" else inputs).append(var)
    return md, inputs, outputs


def experiment(md):
    """(start, stop, step, fixed_step) from the FMU's DefaultExperiment, with the stack's defaults."""
    de = md.defaultExperiment
    start = float(de.startTime) if de and de.startTime else 0.0
    stop = float(de.stopTime) if de and de.stopTime else start + 10.0
    step = float(de.stepSize) if de and de.stepSize else 1.0
    fixed = not md.coSimulation.canHandleVariableCommunicationStepSize
    return start, stop, step, fixed
