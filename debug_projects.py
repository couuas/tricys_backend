
import sqlite3
import os

DB_PATH = "tricys.db"

def list_projects():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        print("--- USERS ---")
        cursor.execute("SELECT id, username FROM user")
        users = cursor.fetchall()
        for u in users:
            print(f"User: {u[1]} (ID: {u[0]})")
        
        print("\n--- PROJECTS ---")
        cursor.execute("SELECT id, name, user_id, created_at FROM project")
        projects = cursor.fetchall()
        for p in projects:
            print(f"Project: {p[1]} (ID: {p[0]}) | Owner: {p[2]}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    list_projects()
