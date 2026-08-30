import psycopg2
import os
from dotenv import load_dotenv

# Load variables from the .env file
load_dotenv()

# Grab the cloud link from .env
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL: 
    raise ValueError("🚨 DATABASE_URL is not set! Check your .env file or Vercel environment variables.")

def get_db_connection():
    # ☁️ Connect to the Neon Cloud Database
    conn = psycopg2.connect(DATABASE_URL)
    return conn