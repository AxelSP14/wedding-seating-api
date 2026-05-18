"""
db.py — Database connection helper
-----------------------------------
Think of this file like a water tap:
  - get_connection() turns the tap ON  → gives you a live connection to MySQL.
  - The "with" statement turns it OFF automatically when you're done,
    even if something crashes in the middle.

We use PyMySQL as the driver (the thing that actually "speaks MySQL").
The credentials come from the .env file via os.environ so they're never
hardcoded in source code.
"""

import os
import pymysql
import pymysql.cursors
from dotenv import load_dotenv

# load_dotenv() reads the .env file and puts every line into os.environ.
# It must run before we try to read any variable with os.getenv().
load_dotenv()


def get_connection() -> pymysql.connections.Connection:
    """
    Open and return a MySQL connection.

    DictCursor makes every row come back as a dictionary  {"id": 1, "name": "Axel"}
    instead of a plain tuple  (1, "Axel").
    Dictionaries are much easier to work with because you can access values
    by name instead of by position.
    """
    return pymysql.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 3306)),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        cursorclass=pymysql.cursors.DictCursor,  # rows as dicts, not tuples
        charset="utf8mb4",                        # supports accented characters (á, é, ñ…)
    )
