# 🧩 FMU Simulation + OPC UA + Streamlit (UI)

This project implements a simulation architecture using **Docker** that integrates three main components:

1. **OPC UA Server** – exposes FMU model variables as OPC UA nodes.  
2. **OPC UA Client + FMU Executor** – runs the FMU using [FMPy](https://github.com/CATIA-Systems/FMPy), publishes its outputs to the OPC UA server, and saves results in CSV and PDF formats.  
3. **Streamlit Interface** – provides a simple real-time dashboard to monitor and modify setpoints.

---

## 📁 Project Structure

```
.
├─ docker-compose.yml
├─ model/
│  └─ model.fmu               # Your FMU file (must include linux64 binaries)
├─ results/                    # Generated output files: CSV and PDF
├─ opcua_server/
│  ├─ Dockerfile
│  └─ opcua_server.py
├─ fmu_client/
│  ├─ Dockerfile
│  └─ fmu_runner_opc.py
└─ streamlit_ui/
   ├─ Dockerfile
   └─ streamlit_app.py
```

---

## ⚙️ Prerequisites

- **Docker** and **Docker Compose** installed.  
- Valid `.fmu` file with Linux binaries (`binaries/linux64`).  
- Enough disk space for simulation results.

---

## 🚀 How to Run

### 1️⃣ Prepare the FMU

Copy your FMU file to the `model/` directory:
```bash
mkdir -p model results
cp FMUs/ORIGINAL_modified_auto.fmu model/model.fmu
```

---

### 2️⃣ Build Containers

```bash
docker compose build
```

---

### 3️⃣ Start the Environment

```bash
docker compose up
```

This will start:

- **OPC UA Server:** `opc.tcp://localhost:4840`  
- **FMU Client:** runs the FMU simulation and sends variable data to the server.  
- **Streamlit UI:** available at [http://localhost:8501](http://localhost:8501)

---

### 4️⃣ Simulation Results

Simulation results are saved in the `results/` folder:

| File | Description |
|-------|--------------|
| `simulation_inputs_outputs.csv` | Input/output variables recorded at each simulation step |
| `simulation_plots.pdf` | Plots of inputs and outputs |

---

## 🧠 Architecture Overview

```text
 ┌────────────────────┐      ┌──────────────────────────┐      ┌──────────────────────┐
 │  OPC UA Server     │◄────►│  OPC UA Client + FMU     │◄────►│  Streamlit UI (web)  │
 │ (python-opcua)     │      │ (FMPy + python-opcua)    │      │ (streamlit)          │
 └────────────────────┘      └──────────────────────────┘      └──────────────────────┘
         ↑                           ↑
         │                           │
         │      Publishes variables  │
         │      and reads setpoints  │
         └───────────────────────────┘
```

---

## ⚙️ Main Environment Variables

| Variable | Description | Service |
|-----------|--------------|----------|
| `OPCUA_ENDPOINT` | OPC UA server address (default `opc.tcp://opcua-server:4840`) | All |
| `FMU_PATH` | Path to the `.fmu` file inside the container | fmu-client |
| `RESULTS_DIR` | Directory to store simulation results | fmu-client |
| `START_TIME`, `STOP_TIME`, `STEP_SIZE` | Simulation time parameters | fmu-client |

---

## 🧩 Customization

- **Simulation duration:** adjust `STOP_TIME` and `STEP_SIZE` in `docker-compose.yml`.  
- **Published variables:** edit `DEFAULT_OUTPUTS` in `fmu_runner_opc.py` and `VARS_READONLY` / `VARS_WRITABLE` in `opcua_server.py`.  
- **Real-time updates:** Streamlit provides manual refresh buttons or auto-reload as desired.

---

## 🧾 Example Output

After a typical run:
```
✅ CSV Results: /results/simulation_inputs_outputs.csv
📊 PDF Charts: /results/simulation_plots.pdf
```

The CSV file contains time-series data of all input and output variables, and the PDF shows the corresponding plots.

---

## 🧰 Useful Commands

- **Restart environment**
  ```bash
  docker compose down && docker compose up --build
  ```

- **Check FMU Client logs**
  ```bash
  docker logs fmu-client
  ```

- **Open the web UI**
  [http://localhost:8501](http://localhost:8501)

---

## 🧹 Cleanup

To stop and remove everything:
```bash
docker compose down
rm -rf results/*
```

---

## 🧑‍💻 Author

Integration environment for **FMU–OPC UA simulation** with real-time visualization using **Streamlit**.  
Fully modular structure ready for deployment in containerized systems.
