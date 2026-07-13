"""
Kingdom Frontier — Database Initialization
Creates and seeds the SQLite database with full RPG schema.
"""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "game_data.db")


def initialize_database():
    """Create all tables and seed data. Safe to call multiple times."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        
        # Ensure database tables are verified
        try:
            c.execute("SELECT COUNT(*) FROM Items")
        except Exception:
            pass  # Tables don't exist yet

        # ═══════════════════════════════════════════════════════════════
        # TABLES
        # ═══════════════════════════════════════════════════════════════

        c.execute("""
        CREATE TABLE IF NOT EXISTS NPCs (
            npc_name TEXT PRIMARY KEY,
            personality TEXT,
            allowed_actions TEXT,
            location TEXT DEFAULT '',
            emotion_state TEXT DEFAULT 'neutral',
            trust_level INTEGER DEFAULT 50
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS Players (
            player_name TEXT PRIMARY KEY,
            creation_timestamp TEXT,
            character_class TEXT DEFAULT 'warrior',
            gold INTEGER DEFAULT 100
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS Conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_name TEXT, npc_name TEXT,
            held_items TEXT, player_input TEXT,
            npc_response TEXT, npc_action TEXT,
            timestamp TEXT,
            player_choice_index INTEGER DEFAULT -1,
            emotion_after TEXT DEFAULT 'neutral',
            trust_after INTEGER DEFAULT 50,
            player_options TEXT,
            FOREIGN KEY(player_name) REFERENCES Players(player_name)
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS QuestState (
            player_name TEXT, quest_id TEXT,
            status TEXT DEFAULT 'not_started',
            current_step INTEGER DEFAULT 0,
            flags TEXT DEFAULT '{}',
            updated_at TEXT,
            PRIMARY KEY (player_name, quest_id),
            FOREIGN KEY(player_name) REFERENCES Players(player_name)
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS Items (
            item_id TEXT PRIMARY KEY,
            item_name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            base_price INTEGER DEFAULT 0
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS Inventory (
            player_name TEXT,
            item_id TEXT,
            quantity INTEGER DEFAULT 1,
            PRIMARY KEY(player_name, item_id),
            FOREIGN KEY(player_name) REFERENCES Players(player_name),
            FOREIGN KEY(item_id) REFERENCES Items(item_id)
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS ShopItems (
            npc_name TEXT,
            item_id TEXT,
            stock INTEGER DEFAULT 10,
            sell_price INTEGER,
            buy_price INTEGER,
            PRIMARY KEY(npc_name, item_id),
            FOREIGN KEY(npc_name) REFERENCES NPCs(npc_name),
            FOREIGN KEY(item_id) REFERENCES Items(item_id)
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS Relationships (
            player_name TEXT,
            npc_name TEXT,
            trust INTEGER DEFAULT 50,
            friendship INTEGER DEFAULT 50,
            respect INTEGER DEFAULT 50,
            suspicion INTEGER DEFAULT 0,
            PRIMARY KEY(player_name, npc_name)
        )""")

        c.execute("""
        CREATE TABLE IF NOT EXISTS Memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_name TEXT,
            npc_name TEXT,
            memory_type TEXT,
            description TEXT,
            timestamp TEXT
        )""")

        # ═══════════════════════════════════════════════════════════════
        # SEED: NPCs
        # ═══════════════════════════════════════════════════════════════
        npcs = [
            ("Captain Aldric",
             "Stern, honorable, duty-bound warrior guarding the Castle Gate. Respects strength and courage. "
             "Only opens the gate if the adventurer has a katana and noble intent. Speaks formally.",
             "open_gate", "Castle Gate", "neutral", 50),
            ("Mira",
             "Shrewd but fair merchant at the Market Square. Sells weapons and potions. "
             "Drives a hard bargain but hints at gold locations if player is polite. Warm and charming.",
             "sell_katana", "Market Square", "friendly", 60),
            ("Elder Thorn",
             "Ancient Forest Warden elder who speaks in riddles. Guards the Sacred Grove. "
             "Knows the location of an ancient relic. Only shares secrets with trusted souls.",
             "reveal_secret", "Sacred Grove", "neutral", 45),
            ("Shade",
             "Mysterious Shadow Guild operative at the Dockside Tavern. Tests loyalty before offering missions. "
             "Speaks in hushed tones. Distrustful of do-gooders.",
             "offer_mission", "Dockside Tavern", "distrustful", 30),
        ]
        for npc in npcs:
            c.execute("INSERT OR IGNORE INTO NPCs VALUES (?,?,?,?,?,?)", npc)

        # ═══════════════════════════════════════════════════════════════
        # SEED: Items
        # ═══════════════════════════════════════════════════════════════
        items = [
            ("frostbane_katana", "Frostbane Katana", "weapon", "A legendary ice-forged blade that never dulls.", 50),
            ("steel_sword", "Steel Sword", "weapon", "A simple but reliable steel sword.", 15),
            ("hunting_knife", "Hunting Knife", "weapon", "A sharp steel knife, handy in a pinch.", 5),
            ("health_potion", "Health Potion", "consumable", "Restores vitality. Tastes like pine and honey.", 10),
            ("iron_shield", "Iron Shield", "weapon", "A sturdy shield bearing the crest of Ironhaven.", 30),
            ("shadow_cloak", "Shadow Cloak", "armor", "Woven from midnight silk. Grants stealth in darkness.", 40),
            ("thornwood_bow", "Thornwood Bow", "weapon", "Carved from ancient thornwood. Silent and deadly.", 75),
            ("ancient_map", "Ancient Map", "quest_item", "A faded map showing a path into the Thornwall Mountains.", 25),
            ("dragon_scale", "Dragon Scale", "quest_item", "An iridescent scale from a dragon. Extremely rare.", 200),
            ("diamond", "Diamond", "Loot", "A massive iridescent diamond harvested from the Red Dragon. Highly valuable.", 100),
            ("golden_chalice", "Golden Chalice", "Loot", "A royal chalice looted from the castle throne room.", 60),
            ("crown_jewels", "Crown Jewels", "Loot", "Precious jewels looted from the castle treasury.", 100),
            ("royal_scepter", "Royal Scepter", "Loot", "An ornate scepter looted from the castle keep.", 80),
            ("ruby_ring", "Ruby Ring", "Loot", "A ring set with a beautiful ruby.", 50),
            ("golden_candelabra", "Golden Candelabra", "Loot", "A heavy candelabra made of solid gold.", 40),
            ("elven_goblet", "Elven Goblet", "Loot", "A finely crafted elven drinking goblet.", 30),
            ("diamond_greatsword", "Diamond Greatsword", "weapon", "A massive sword forged from compressed dragon diamond. Deals 20 damage.", 150),
            ("shadowflame_dagger", "Shadowflame Dagger", "weapon", "A dark blade infused with shadow energy. Deals 18 damage.", 200)
        ]
        for item in items:
            c.execute("INSERT OR REPLACE INTO Items (item_id, item_name, category, description, base_price) VALUES (?,?,?,?,?)", item)

        # ═══════════════════════════════════════════════════════════════
        # SEED: Shop Items (what each NPC sells)
        # ═══════════════════════════════════════════════════════════════
        shop_items = [
            # Mira's Market
            ("Mira", "frostbane_katana", 3, 50, 25),
            ("Mira", "steel_sword", 5, 15, 7),
            ("Mira", "hunting_knife", 10, 5, 2),
            ("Mira", "health_potion", 20, 10, 5),
            ("Mira", "iron_shield", 5, 30, 15),
            ("Mira", "thornwood_bow", 2, 75, 35),
            ("Mira", "ancient_map", 1, 25, 10),
            # Shade's black market
            ("Shade", "shadow_cloak", 3, 40, 20),
            ("Shade", "health_potion", 10, 15, 5),  # Higher price in black market
        ]
        for si in shop_items:
            c.execute("INSERT OR IGNORE INTO ShopItems VALUES (?,?,?,?,?)", si)

        # ═══════════════════════════════════════════════════════════════
        # SEED: Initial NPC greetings
        # ═══════════════════════════════════════════════════════════════
        greetings = [
            ("Captain Aldric", "Halt, adventurer. State your business at the Castle Gate.", '["What do I need to enter the keep?", "Tell me about the threats beyond the mountains.", "Who commands the Royal Guard?", "Farewell."]'),
            ("Mira", "Welcome to Mira's Market! Looking for something special today?", '["What weapons do you have for sale?", "Do you have any potions?", "I\'d like to sell something.", "Farewell."]'),
            ("Elder Thorn", "The wind carries a new soul to the Grove... Speak, young one.", '["I seek your wisdom, Elder.", "What can you teach me about this land?", "How can I earn the forest\'s trust?", "Farewell."]'),
            ("Shade", "...You're not from around here. What do you want?", '["I\'m looking for work. Unconventional work.", "I\'ve heard rumors about the Shadow Guild.", "Can I buy you a drink?", "Farewell."]'),
        ]
        for npc_name, line, opts in greetings:
            c.execute("""
                INSERT OR IGNORE INTO Conversations 
                (player_name, npc_name, player_input, npc_response, npc_action, timestamp, emotion_after, trust_after, player_options)
                VALUES (?, ?, '', ?, 'none', datetime('now'), 'neutral', 50, ?)
            """, ("All", npc_name, line, opts))

        conn.commit()
    print("Kingdom Frontier database initialized successfully.")


if __name__ == "__main__":
    initialize_database()