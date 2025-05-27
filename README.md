# UniFMU Setup and FMU Generation on Windows (Python 3.12)

This guide explains how to install UniFMU in your standalone Python 3.12 environment and use it to generate an FMU from a Python model.

---

## ✅ Requirements

- Python 3.12 installed at:
  ```
  C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python312
  ```

- Admin or user terminal access (CMD, PowerShell, or terminal inside VS Code)

---

## 📦 Step 1: Install `unifmu` for Python 3.12

Use the following command to install UniFMU and the rest of dependencies via pip in the correct environment:

```bash
"C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python312\python.exe" -m pip install --upgrade pip
"C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python312\python.exe" -m pip install unifmu
"C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python312\python.exe" -m pip install "unifmu[python-backend]"
"C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python312\python.exe" -m pip install protobuf==3.20.3
```

---

## 🔍 Step 2: Verify the Installation

To confirm that UniFMU is installed:

```bash
"C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python312\python.exe" -m pip show unifmu
```

You should see output showing the package name, version, and install location.

---

## ⚙️ Step 3: Generate the FMU

Once installed, you can generate your FMU using the UniFMU CLI:

```bash
"C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python312\Scripts\unifmu.exe" generate python python_adder.fmu
```

- `python_adder.fmu` is the name of the FMU that will be created.
- This assumes you have a valid Python class that inherits from `PythonModel` in your script (e.g. `model.py`).

---

## ✅ Optional: Add to PATH

To use `unifmu` globally without the full path, add this folder to your system `PATH`:

```
C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python312\Scripts
```

---

## 📁 Project Example Structure

```
python_adder_model_eium.fmu/
├── binaries/
│   ├── darwin64/
│   │   └── model.dylib         # macOS shared library (placeholder or real binary)
│   ├── linux64/
│   │   └── model.so            # Linux shared object (placeholder or real binary)
│   └── win64/
│       └── model.dll           # Windows DLL (placeholder or real binary)
├── resources/
│   ├── schemas/
│   │   ├── unifmu_fmi2_pb2.py
│   │   └── unifmu_fmi2_pb2_grpc.py
│   ├── backend_grpc.py
│   ├── backend_schemaless_rpc.py
│   ├── fmi2.py
│   ├── launch.toml             # Updated to point to Python 3.12 interpreter
│   └── model.py                # Your Python FMU model logic
├── modelDescription.xml        # Describes inputs, outputs, and structure
└── README.md                   # Documentation (optional)
```

- The `binaries/` directory contains native shared libraries for different operating systems (required even if empty or mocked).
- The `resources/` directory contains the actual Python backend and model implementation.
- `modelDescription.xml` must be at the root of the FMU.
- `launch.toml` controls how the backend is started based on OS.

---

## 🧩 FMU Configuration: `launch.toml` Setup for Python 3.12

To ensure that UniFMU uses the correct Python interpreter when launching the FMU backend on Windows, update your `resources/launch.toml` file as follows if using `zmq` or `gprc`:

```toml

backend = "grpc"

[grpc]
linux = ["python3", "backend_grpc.py"]
macos = ["python3", "backend_grpc.py"]
windows = ["C:/Users/Lucia/AppData/Local/Programs/Python/Python312/python.exe", "backend_grpc.py"]

[zmq]
linux = ["python3", "backend_schemaless_rpc.py"]
macos = ["python3", "backend_schemaless_rpc.py"]
serialization_format = "Pickle"
windows = ["C:/Users/Lucia/AppData/Local/Programs/Python/Python312/python.exe", "backend_schemaless_rpc.py"]

```

This guarantees that your FMU will run using the correct interpreter and avoid errors with missing modules or backend startup. In this case we are using backend "grpc", but we add the correct adress in both sections

---

## 🆘 Troubleshooting

- If `unifmu` is not recognized, always use the full path.
- Use `--help` to see available commands:
  ```bash
  "C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python312\Scripts\unifmu.exe" --help
  ```
- Add path to the environmental variables in which `unifmu.exe` is installed in order to be able to execute the tool:
  ```bash
  C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python312\Scripts
  ```

---

## 🔄 Step 4: Update and Package FMU from Source Code

Once you have the FMU template structure generated (including `model.py`, `modelDescription.xml`, and folder layout inside `python_adder_model_eium.fmu`), you can regenerate and update the contents using the script `update_and_package_fmu.py`.

### 📌 Purpose:
This script:
- Regenerates the logic in `model.py` and `modelDescription.xml` using the function defined in `fmu_psycrometry.py`.
- Saves these files into the `resources/` subfolder of the FMU template.
- Compresses the FMU folder and renames it as a `.fmu` file (instead of `.zip`).

### ▶️ To run it:

```bash
python update_and_package_fmu.py
```

### 📁 Result:

You will get an updated FMU file:

```
python_adder_model_eium_generated.fmu
```

This can now be used for testing or simulation.
---

Very important! The name of the dll inside the folders of binaries should be the same as the name of the model.py in this case `model.dll`, `model.so` and `model.dylib`

## ▶️ Step 5: Execute the FMU with FMPy

To run your generated FMU in a graphical environment using [FMPy GUI](https://github.com/CATIA-Systems/FMPy), you must first install the necessary packages.

### ✅ Install FMPy and GUI dependencies

Use your Python 3.12 environment to install:

```bash
"C:/Users/Lucia/AppData/Local/Programs/Python/Python312/python.exe" -m pip install fmpy
"C:/Users/Lucia/AppData/Local/Programs/Python/Python312/python.exe" -m pip install PySide6
```

---

### ▶️ Launch FMUGUI

To launch the graphical interface:

```bash
"C:/Users/Lucia/AppData/Local/Programs/Python/Python312/python.exe" -m fmpy.gui
```

A window like the one below will open.

---

### 📂 Load and Run the FMU

1. Click **File > Open** and select your `.fmu` file (e.g., `python_adder_model_eium_generated.fmu`).
2. Use the **Start** column to initialize inputs.
3. Press the **Play** ▶️ button to simulate.
4. Check the **Plot** boxes for outputs you'd like to visualize.

---

### 📊 Example Output

Below is an example plot obtained by loading the FMU and simulating it over 5 seconds:

![alt text](image.png)


## 🔗 References

- 🔧 Official UniFMU repository and installation instructions:  
  https://github.com/INTO-CPS-Association/unifmu/tree/master?tab=readme-ov-file#getting-the-tool

- 🖥 How to use the CLI:  
  https://github.com/INTO-CPS-Association/unifmu/tree/master?tab=readme-ov-file#how-can-i-execute-the-launch-command-through-a-shell

- 📄 Reference article:  
  Legaard, C. M., Tola, D., Schranz, T., Macedo, H. D., & Larsen, P. G. (2021).  
  *A Universal Mechanism for Implementing Functional Mock-up Units*.  
  In G. Wagner et al. (Eds.), Proceedings of the 11th International Conference on Simulation and Modeling Methodologies, Technologies and Applications, SIMULTECH 2021, pp. 121–129. SCITEPRESS.  
  https://doi.org/10.5220/0010577601210129
