# syntax=docker/dockerfile:1
# One image for the whole stack: OPC UA server, Streamlit UI and FMU runs.
# Build context: the repository root (see docker-compose.yml / liqo/up.sh).
#
# The FMU is built here, with fmugen installed in /opt/venv, so its launch.toml points at
# /opt/venv/bin/python and the model's requirements are installed next to it.
#   MODEL=examples/simple_pid        build another model (a folder with fmugen.toml)
#   FMUGEN_ARGS="--fmi 3"            extra `fmugen build` options
#   PREBUILT=1                       use docker/model/model.fmu instead of building one;
#                                    it must run on Linux (fmugen build --vendor ... or --compile on Linux)
FROM python:3.13-slim

ARG UNIFMU_VERSION=0.14.0
ARG MODEL=examples/psychrometry
ARG FMUGEN_ARGS=""
ARG PREBUILT=0

ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
RUN python -m venv /opt/venv

COPY docker/app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# fmugen from this repository
COPY pyproject.toml README.md /src/fmugen/
COPY src /src/fmugen/src
RUN pip install --no-cache-dir /src/fmugen

COPY examples /src/examples
COPY docker/model /src/docker/model
COPY docker/build_fmu.py /src/docker/build_fmu.py
RUN python /src/docker/build_fmu.py

COPY docker/app /app
WORKDIR /app
ENV FMU_PATH=/model/model.fmu
EXPOSE 4840 8501
CMD ["python", "fmu_runner.py"]
