import psycopg2
import os
from dotenv import load_dotenv

# Load variables from the .env file
load_dotenv()

# Grab the cloud link from .env (it will be None if the file doesn't exist)
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if DATABASE_URL:
        # ☁️ Connect to the Neon Cloud Database
        conn = psycopg2.connect(DATABASE_URL)
    else:
        # 💻 Fallback: Connect to your local TablePlus database
        conn = psycopg2.connect(
            host="localhost",
            database="postgres",
            user="postgres",
            password="admin123",  
            port="5432"
        )
    return conn