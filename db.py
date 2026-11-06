import os
import sqlite3
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(APP_DIR / "school.db")))

def get_conn():
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            group_name TEXT DEFAULT '',
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            teacher_message_id INTEGER,
            forwarded_message_id INTEGER,
            direction TEXT NOT NULL CHECK(direction IN ('in', 'out')),
            content_type TEXT DEFAULT 'text',
            text TEXT,
            file_id TEXT,
            read_at TIMESTAMP,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_messages_student ON messages(student_id);
        CREATE INDEX IF NOT EXISTS idx_messages_forwarded ON messages(forwarded_message_id);
    """)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
    if "read_at" not in columns:
        conn.execute("ALTER TABLE messages ADD COLUMN read_at TIMESTAMP")
    conn.commit()
    conn.close()
