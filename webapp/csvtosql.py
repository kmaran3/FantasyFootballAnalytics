# scripts/csv_to_sqlite.py

import pandas as pd
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # Darkhorse/

# List of CSV files and their corresponding table names
csv_files = [
    {'file': ROOT / 'Models/PickleFiles/Full PPR Rankings with Weighted VBD.pkl', 'table_name': 'Full_PPR'},
    {'file': ROOT / 'Models/PickleFiles/Half PPR Rankings with Weighted VBD.pkl', 'table_name': 'Half_PPR'},
    {'file': ROOT / 'Models/PickleFiles/Non PPR Rankings with Weighted VBD.pkl', 'table_name': 'Non_PPR'}
]

# Columns to pull from each CSV file
columns_to_use = ['Rank', 'Name', 'Team', 'Position', 'Bye Week', 'ESPN ADP']

# Create a SQLite connection
conn = sqlite3.connect(ROOT / 'webapp/my_database.db')

# Iterate through the list of CSV files and save each to a separate table in the SQLite database
for csv_file in csv_files:
    # Load each pickle file into a pandas DataFrame, selecting only the specified columns
    df = pd.read_pickle(csv_file['file'])[columns_to_use]

    # Save DataFrame to a table in the SQLite database
    df.to_sql(csv_file['table_name'], con=conn, if_exists='replace', index=False)

conn.close()
print("CSV files have been successfully converted to SQLite tables with specified columns.")
