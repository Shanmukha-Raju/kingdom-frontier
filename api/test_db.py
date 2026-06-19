import sqlite3
import os

DB_PATH = "api/data/game_data.db"

if not os.path.exists(DB_PATH):
    print("Database not found at", DB_PATH)
    exit(1)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

print("=== NPCs ===")
c.execute("SELECT npc_name, allowed_actions, emotion_state, trust_level FROM NPCs")
for row in c.fetchall():
    print(row)

print("\n=== Conversations ===")
c.execute("SELECT id, player_name, npc_name, player_input, npc_response, npc_action, timestamp, player_options FROM Conversations")
for row in c.fetchall():
    print(row)

print("\n=== Players ===")
c.execute("SELECT player_name, character_class, gold FROM Players")
for row in c.fetchall():
    print(row)

conn.close()
