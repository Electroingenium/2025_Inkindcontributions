# 🧩 FMU Simulation + OPC UA + Streamlit (UI)

This project implements a **modular simulation architecture** based on **Docker**, integrating three synchronized components:

1. **🖥️ OPC UA Server** – exposes model variables (calculated, control, and auxiliary) as OPC UA nodes.  
2. **⚙️ FMU Client + OPC UA Publisher** – runs the FMU using [FMPy](https://github.com/CATIA-Systems/FMPy), exchanges data with the OPC UA server, and stores results in CSV format.  
3. **📊 Streamlit Dashboard** – provides a user interface for real-time monitoring, setpoint control, and graphical visualization of simulation outputs.

---

## 📁 Project Structure

```
.
├─ docker-compose.yml
├─ model/
│  └─ model.fmu                # FMU file (must include linux64 binaries)
├─ results/                    # Generated simulation outputs (CSV)
├─ opcua_server/
│  ├─ Dockerfile
│  └─ opcua_server.py          # Defines all OPC UA variables and permissions
├─ fmu_client/
│  ├─ Dockerfile
│  └─ fmu_runner_opc.py        # Runs FMU and exchanges variables via OPC UA
└─ streamlit_ui/
   ├─ Dockerfile
   └─ streamlit_app.py         # Streamlit dashboard with tabs and charts
```

---

## ⚙️ Prerequisites

- 🐳 **Docker** and **Docker Compose** installed.  
- Valid `.fmu` file containing `binaries/linux64/`.  
- Shared `results/` directory for inter-container data exchange.  

---

## 🚀 How to Run

### 1️⃣ Prepare the FMU
Copy your FMU file into the `model/` directory:
```bash
mkdir -p model results
cp FMUs/your_model.fmu model/model.fmu
```

---

### 2️⃣ Build Containers
```bash
docker compose build
```

---

### 3️⃣ Start the System
```bash
docker compose up
```

This will start:

| Component | Description | Default Endpoint |
|------------|--------------|------------------|
| 🖥️ **OPC UA Server** | Hosts model variables | `opc.tcp://localhost:4840` |
| ⚙️ **FMU Client** | Executes the FMU and updates OPC UA nodes | Internal Docker network |
| 📊 **Streamlit UI** | Web dashboard to view and control variables | [http://localhost:8501](http://localhost:8501) |

---

### 4️⃣ View Simulation Results

Simulation outputs are automatically saved in:

```
results/simulation_outputs.csv
```

You can view them interactively in Streamlit under the **📊 Resultados (FMU)** tab.

---

## 🧠 Architecture Overview

```text
 ┌──────────────────────────────┐
 │         Streamlit UI         │
 │  - View & edit setpoints     │
 │  - Visualize CSV results     │
 └─────────────▲────────────────┘
               │
               │ OPC UA (python-opcua)
               │
 ┌─────────────┴────────────────┐
 │        OPC UA Server         │
 │  - Defines namespaces         │
 │  - Controls read/write perms  │
 └─────────────▲────────────────┘
               │
               │ Variable updates
               │
 ┌─────────────┴────────────────┐
 │     FMU Runner + Client      │
 │  - Runs FMU via FMPy         │
 │  - Reads setpoints from OPC  │
 │  - Publishes results (CSV)   │
 └──────────────────────────────┘
```

---

## ⚙️ Environment Variables

| Variable | Description | Service |
|-----------|-------------|----------|
| `OPCUA_ENDPOINT` | OPC UA server address (`opc.tcp://opcua-server:4840`) | fmu-client |
| `FMU_PATH` | Path to FMU file | fmu-client |
| `RESULTS_DIR` | Directory to save results | fmu-client |
| `START_TIME` / `STOP_TIME` / `STEP_SIZE` | FMU simulation timing | fmu-client |

---

## 💡 Streamlit Dashboard Overview

The Streamlit app is divided into **three tabs**:

| Tab | Description |
|-----|--------------|
| 🟩 **Read (OPC UA)** | Displays calculated read-only variables (e.g., `energy_balance`, `Q_in`, `Q_out`). |
| 🟦 **Setpoints (OPC UA)** | Allows user input to update control and auxiliary variables (e.g., `regen_target_temp`, `temp_1`, etc.). |
| 📊 **Results (FMU)** | Loads `/results/simulation_outputs.csv`, shows data table, and interactive line charts of selected variables. |

### Example Chart View:
- Select one or more variables from the multiselect dropdown.
- Data plotted dynamically against simulation time.
- Optionally auto-refreshable for near real-time updates.

---

## 🧩 Customization

- 🕒 **Adjust simulation duration** → edit `STOP_TIME` and `STEP_SIZE` in `docker-compose.yml`.  
- 🧾 **Add or remove OPC UA variables** → modify `calc_vars`, `control_vars`, or `aux_vars` in `opcua_server.py`.  
- 🔄 **Auto-refresh UI** → Streamlit can be configured to reload the CSV at intervals.  
- 🎨 **Charts** → The app uses `st.line_chart` (simple) or `Altair` (multi-variable, color-coded).

---

## 🧾 Example Output

After simulation completes:

```
INFO:fmu_runner_opc:📊 Results saved to /results/simulation_outputs.csv
```

The CSV typically contains:

| time | energy_balance | mass_balance | mdot_air_in | Q_in | Q_out |
|------|----------------|---------------|--------------|------|-------|
| 0.0  | 3029.9 | 0.12 | 0.24 | 6059.9 | 3029.9 |
| 1.0  | 3039.9 | 0.13 | 0.25 | 6069.9 | 3039.9 |
| ...  | ... | ... | ... | ... | ... |

---

## 🧰 Useful Commands

| Action | Command |
|---------|----------|
| 🧱 Rebuild all containers | `docker compose build --no-cache` |
| 🚀 Start simulation | `docker compose up` |
| 🧼 Stop and remove | `docker compose down` |
| 📄 View FMU logs | `docker logs fmu-client` |
| 🌐 Open UI | [http://localhost:8501](http://localhost:8501) |

---

## 🧹 Cleanup

To remove containers and generated data:
```bash
docker compose down
rm -rf results/*
```

---

## 👩‍💻 Author

**EIUM – FMU/OPC UA Integration Environment**  
Developed by *Lucia Royo-Pascual, Ph.D.*  

> Real-time FMU simulation environment with OPC UA communication and Streamlit visualization.  
> Fully modular and containerized for research, testing, and deployment.
