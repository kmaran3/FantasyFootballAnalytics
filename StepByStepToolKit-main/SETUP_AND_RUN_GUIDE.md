# Fantasy Football Model - Setup & Run Guide

## ✅ Virtual Environment Setup Complete!

Your virtual environment is located at: `.\venv\`

All required packages have been installed:
- Flask (Web framework)
- pandas (Data processing)
- nflreadpy (NFL data access)
- Jupyter (Notebook environment)
- And all other dependencies

---

## 1️⃣ Activate the Virtual Environment

### PowerShell:
```powershell
.\venv\Scripts\Activate.ps1
```

### Command Prompt:
```cmd
venv\Scripts\activate.bat
```

### Git Bash:
```bash
source venv/Scripts/activate
```

Once activated, you'll see `(venv)` at the start of your terminal prompt.

---

## 2️⃣ Running the Data Pipeline

The project has two data pipelines that must be run in order:

### **Pipeline 1: NewModel (Powers Main Rankings & Mock Draft)**

Run these notebooks in order:

1. **Build Dataset**
   ```powershell
   cd Models/NewModel
   jupyter notebook Phase1_BuildDataset.ipynb
   ```
   - Produces: `PickleFiles/NewModel/qb_dataset.pkl`, `rb_dataset.pkl`, `wr_dataset.pkl`, `te_dataset.pkl`

2. **Feature Engineering**
   ```powershell
   jupyter notebook Phase2_FeatureEngineering.ipynb
   ```
   - Produces: `PickleFiles/NewModel/qb_features.pkl`, `rb_features.pkl`, `wr_features.pkl`, `te_features.pkl`

3. **Train Models**
   ```powershell
   jupyter notebook Phase3_TrainModels.ipynb
   ```
   - Produces: `PickleFiles/NewModel/combined_predictions_ppr.pkl` (used by rankings page)

### **Pipeline 2: Classic Pipeline (Powers Player Profiles & Saved Rankings)**

Run these in order (from project root):

1. **Positional Data**
   ```powershell
   cd "Models/final position group data"
   jupyter notebook PositionalData.ipynb
   ```
   - Produces: `PickleFiles/final_qb_data.pkl`, `final_rb_data.pkl`, `final_wrte_data.pkl`

2. **Rosters**
   ```powershell
   cd ../Roster Creation
   jupyter notebook Rosters.ipynb
   ```
   - Produces: `PickleFiles/currYearRoster.pkl`, `PickleFiles/teamsPastRoster.pkl`

3. **ML Model**
   ```powershell
   cd ..
   jupyter notebook MLModel.ipynb
   ```
   - Produces: PPR/Half-PPR/Non-PPR model dataframes

4. **Prediction Code**
   ```powershell
   jupyter notebook PredictionCode.ipynb
   ```
   - Produces: Player predictions for all formats

5. **Rankings Creation**
   ```powershell
   cd "Final Rankings"
   jupyter notebook RankingCSVCreation.ipynb
   ```
   - Produces: Ranking pickles

6. **VBD Rankings** (Optional - Weighted rankings)
   ```powershell
   jupyter notebook VBD.ipynb
   ```
   - Produces: Weighted VBD rankings

---

## 3️⃣ Running the Web Application

### Step 1: Database Setup
From the project root directory:
```powershell
python webapp/csvtosql.py
```
This creates the database and populates it with initial data.

### Step 2: Start the Flask App
```powershell
python app.py
```

The app will start on: **http://localhost:5001**

### Features Available:
- 📊 **Rankings Page** - Player rankings powered by NewModel pipeline
- 🎯 **Mock Draft** - Interactive draft simulator
- 👤 **Player Profiles** - Detailed stats powered by Classic pipeline
- 💾 **Saved Rankings** - Create and manage custom rankings
- 📋 **Rosters** - Team roster information
- 🔐 **User Accounts** - Register and login

---

## 4️⃣ Quick Command Reference

### Full Setup from Scratch (One-Time)
```powershell
# Activate environment
.\venv\Scripts\Activate.ps1

# Run both data pipelines (long process!)
# ... (follow Pipeline 1 & 2 above)

# Setup database
python webapp/csvtosql.py

# Start app
python app.py
```

### Daily Startup (After Restart)
```powershell
# Activate environment
.\venv\Scripts\Activate.ps1

# Start app
python app.py
```

---

## ⚠️ Important Notes

- **Python Version**: Python 3.13 is required (especially for nflreadpy)
- **Data Synchronization**: Ensure both pipelines' year ranges match in:
  - `Models/final position group data/PositionalData.ipynb` 
  - `Models/NewModel/Phase1_BuildDataset.ipynb`
  - Currently both use: `range(2016, 2026)` (2016-2025)

- **Full Functionality**: Both pipelines must be run for the app to work properly
  - NewModel runs the **main rankings page and mock draft**
  - Classic pipeline runs **player profiles and saved rankings**

- **Debug Mode**: The Flask app runs in debug mode by default (auto-reload on code changes)
  - Change `debug=True` to `debug=False` in `app.py` if needed

---

## 🔧 Troubleshooting

### Module Not Found Errors
```powershell
# Reinstall dependencies
pip install -r requirements.txt
```

### Database Errors
```powershell
# Delete old database and recreate
rm my_database.db
python webapp/csvtosql.py
```

### Port Already in Use
Edit `app.py` and change the port number:
```python
app.run(debug=True, port=5002, use_reloader=False)  # Change 5001 to 5002
```

### Notebook Kernel Issues
```powershell
# Restart Jupyter and select the correct Python kernel
# Choose: "venv\Scripts\python.exe" as the kernel
```

---

## 📊 Project Structure

```
StepByStepToolKit-main/
├── app.py                          # Flask app entry point
├── venv/                           # Virtual environment
├── requirements.txt                # Python dependencies
│
├── Models/
│   ├── NewModel/                   # Main ML pipeline (Phase 1-3)
│   ├── final position group data/  # Player stats (PositionalData.ipynb)
│   ├── Roster Creation/            # Roster data (Rosters.ipynb)
│   ├── Final Rankings/             # Rankings generation
│   ├── MLModel.ipynb               # Classic ML model
│   ├── PredictionCode.ipynb        # Player predictions
│   └── PickleFiles/                # Cached data outputs
│
├── webapp/
│   ├── csvtosql.py                 # Database initialization
│   ├── views.py                    # Flask routes
│   ├── forms.py                    # User input forms
│   ├── templates/                  # HTML pages
│   ├── static/                     # CSS, JS, images
│   └── data/                       # Supporting data files
│
└── instance/                       # Flask instance folder
```

---

## 🚀 Next Steps

1. ✅ Activate the virtual environment
2. ✅ Run the data pipelines (start with NewModel for quick testing)
3. ✅ Initialize the database with `python webapp/csvtosql.py`
4. ✅ Start the app with `python app.py`
5. ✅ Open http://localhost:5001 in your browser

Happy drafting! 📈
