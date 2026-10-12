"""Script to verify migration was applied correctly"""
import sqlite3

conn = sqlite3.connect('data/app.db')
cursor = conn.cursor()

# Check for matching tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'matching%'")
matching_tables = cursor.fetchall()
print(f"Matching tables: {matching_tables}")

# Check for question_type column
cursor.execute("PRAGMA table_info(question)")
cols = cursor.fetchall()
question_type_col = [c for c in cols if c[1] == 'question_type']
print(f"question_type column exists: {bool(question_type_col)}")

# Check existing questions have question_type='classic'
cursor.execute("SELECT COUNT(*) FROM question WHERE question_type='classic'")
classic_count = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM question")
total_count = cursor.fetchone()[0]
print(f"Questions with type 'classic': {classic_count}/{total_count}")

conn.close()
print("\n✅ Migration verification complete!")
