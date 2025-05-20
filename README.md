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

Use the following command to install UniFMU via pip in the correct environment:

```bash
"C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python312\python.exe" -m pip install --upgrade pip
"C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python312\python.exe" -m pip install unifmu
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
project_folder/
├── model.py
└── (your FMU logic class)
```

---

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

---

## 🆘 Troubleshooting

- If `unifmu` is not recognized, always use the full path.
- Use `--help` to see available commands:
  ```bash
  "C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python312\Scripts\unifmu.exe" --help
  ```
  - Add path to the environmental variables in which unifmu.exe is installed in order to be able to execute the tool
  ```bash
  "C:\Users\<YourUsername>\AppData\Local\Programs\Python\Python312\Scripts"
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

