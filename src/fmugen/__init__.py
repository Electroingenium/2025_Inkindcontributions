"""Generate UniFMU-style FMUs from plain Python models.

A model module must define:
    INPUTS     = {name: {"start": value, "unit": str?, "type": str?}, ...}
    OUTPUTS    = {name: {"unit": str?, "type": str?}, ...}
    PARAMETERS = {...}                 # optional, same shape as INPUTS
    def step(**inputs) -> dict         # returns {output_name: value}
"""
