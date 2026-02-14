# scripts/csv_to_sqlite.py

import pandas as pd
from sqlalchemy import create_engine

# List of CSV files and their corresponding table names
csv_files = [
    {'file': '/Users/kmaran3/Dropbox/Darkhorse/Models/Final Rankings/Full PPR Rankings with Weighted VBD.csv', 'table_name': 'Full_PPR'},
    {'file': '/Users/kmaran3/Dropbox/Darkhorse/Models/Final Rankings/Half PPR Rankings with Weighted VBD.csv', 'table_name': 'Half_PPR'},
    {'file': '/Users/kmaran3/Dropbox/Darkhorse/Models/Final Rankings/Non PPR Rankings with Weighted VBD.csv', 'table_name': 'Non_PPR'}
]

# Columns to pull from each CSV file
columns_to_use = ['Rank', 'Name', 'Team', 'Position', 'Bye Week', 'ESPN ADP']

# Create a SQLite engine
engine = create_engine('sqlite:///my_database.db')

# Iterate through the list of CSV files and save each to a separate table in the SQLite database
for csv_file in csv_files:
    # Load each CSV into a pandas DataFrame, selecting only the specified columns
    df = pd.read_csv(csv_file['file'], usecols=columns_to_use)
    
    # Save DataFrame to a table in the SQLite database
    df.to_sql(csv_file['table_name'], con=engine, if_exists='replace', index=False)

print("CSV files have been successfully converted to SQLite tables with specified columns.")