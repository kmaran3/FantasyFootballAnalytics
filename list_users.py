from webapp import create_app, db
from webapp import User  # Ensure this import points correctly to where the User class is defined
import pandas as pd

def export_users_to_excel():
    app = create_app()
    with app.app_context():  # Access the Flask application context
        # Fetch all user entries from the database
        users = User.query.all()
        # Create a list of dictionaries, each containing the user's email, username (id), and password
        data = [{'Email': user.email, 'Username': user.id, 'Password': user.password} for user in users]

        # Convert the data into a DataFrame
        df = pd.DataFrame(data)
        
        # Specify the filename
        filename = 'users.xlsx'
        
        # Export the DataFrame to an Excel file using the openpyxl engine
        df.to_excel(filename, index=False, engine='openpyxl')

        print(f"Data exported successfully to {filename}")

if __name__ == "__main__":
    export_users_to_excel()
