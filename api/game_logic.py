"""
Kingdom Frontier — Game Logic Layer
Intent detection, game state validation, and context building.
The LLM NEVER decides game outcomes — this module does.
"""

import re
import sqlite3
from datetime import datetime
from create_db import DB_PATH
from quest_engine import QuestEngine

# ═══════════════════════════════════════════════════════════════════════
# INTENT DETECTION
# ═══════════════════════════════════════════════════════════════════════

INTENT_PATTERNS = {
    "buy_item": {
        "keywords": ["buy", "purchase", "want to buy", "how much", "i want", "i need", "i'll take", "give me", "sell me"],
        "priority": 10
    },
    "sell_item": {
        "keywords": ["sell", "trade away", "get rid of", "i want to sell"],
        "priority": 9
    },
    "accept_quest": {
        "keywords": ["accept", "i'll do it", "count me in", "i accept", "sure i'll help", "yes i will", "i volunteer"],
        "priority": 8
    },
    "complete_quest": {
        "keywords": ["done", "finished", "completed", "here it is", "i did it", "task complete", "mission done", "turn in"],
        "priority": 8
    },
    "ask_quest": {
        "keywords": ["quest", "task", "mission", "job", "any work", "need help", "something to do", "assignment"],
        "priority": 7
    },
    "ask_inventory": {
        "keywords": ["what do you have", "show me", "browse", "stock", "wares", "what do you sell", "shop", "items", "trade"],
        "priority": 6
    },
    "ask_location": {
        "keywords": ["where", "location", "find", "directions", "how to get", "path to", "way to", "tell me about this place"],
        "priority": 5
    },
    "ask_about_npc": {
        "keywords": ["who is", "tell me about", "know about", "heard of", "what about", "who are you"],
        "priority": 5
    },
    "greeting": {
        "keywords": ["hello", "hi", "hey", "greetings", "good morning", "good day", "howdy", "hail"],
        "priority": 2
    },
    "goodbye": {
        "keywords": ["bye", "farewell", "goodbye", "see you", "leave", "go now", "i must go", "later"],
        "priority": 1
    },
    "general": {
        "keywords": [],
        "priority": 0
    }
}

# Item name extraction patterns
ITEM_NAMES = [
    "frostbane katana", "frostbane", "katana",
    "steel sword", "sword",
    "hunting knife", "knife",
    "health potion", "potion",
    "iron shield", "shield",
    "shadow cloak", "cloak",
    "thornwood bow", "bow",
    "ancient map", "map",
    "dragon scale", "scale"
]


def detect_intent(player_input: str) -> dict:
    """Detect player intent from their message text."""
    text = player_input.lower().strip()
    
    if not text:
        return {"intent": "greeting", "item": None, "confidence": 1.0}
    
    best_intent = "general"
    best_priority = -1
    
    for intent_name, config in INTENT_PATTERNS.items():
        for keyword in config["keywords"]:
            if keyword in text:
                if config["priority"] > best_priority:
                    best_intent = intent_name
                    best_priority = config["priority"]
                    break
    
    # Extract item name if relevant
    detected_item = None
    if best_intent in ("buy_item", "sell_item", "ask_inventory"):
        for item_name in ITEM_NAMES:
            if item_name in text:
                detected_item = item_name
                break
    
    return {
        "intent": best_intent,
        "item": detected_item,
        "confidence": 1.0 if best_priority > 0 else 0.5
    }


# ═══════════════════════════════════════════════════════════════════════
# GAME LOGIC — CODE DECIDES, LLM DESCRIBES
# ═══════════════════════════════════════════════════════════════════════

class GameLogic:
    """Validates all game actions before the LLM generates dialogue."""

    # ── Shop / Purchase ────────────────────────────────────────────────
    @staticmethod
    def validate_purchase(player_name: str, item_keyword: str, npc_name: str) -> dict:
        """Check if player can buy an item. Returns result for LLM context."""
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            
            # Get player gold
            c.execute("SELECT gold FROM Players WHERE player_name = ?", (player_name,))
            row = c.fetchone()
            player_gold = row[0] if row else 0
            
            # Find item in shop
            c.execute("""
                SELECT si.item_id, i.item_name, si.sell_price, si.stock, i.description, i.category
                FROM ShopItems si
                JOIN Items i ON si.item_id = i.item_id
                WHERE si.npc_name = ? AND (LOWER(i.item_name) LIKE ? OR LOWER(si.item_id) LIKE ?)
            """, (npc_name, f"%{item_keyword}%", f"%{item_keyword.replace(' ', '_')}%"))
            shop_item = c.fetchone()
            
            if not shop_item:
                return {
                    "success": False,
                    "reason": "item_not_found",
                    "message": f"This shop doesn't sell anything matching '{item_keyword}'.",
                    "player_gold": player_gold,
                    "inventory_changes": {},
                    "gold_change": 0
                }
            
            item_id, item_name, price, stock, description, category = shop_item
            
            if stock <= 0:
                return {
                    "success": False,
                    "reason": "out_of_stock",
                    "message": f"{item_name} is out of stock.",
                    "item_name": item_name,
                    "player_gold": player_gold,
                    "inventory_changes": {},
                    "gold_change": 0
                }
            
            if player_gold < price:
                return {
                    "success": False,
                    "reason": "insufficient_gold",
                    "message": f"{item_name} costs {price} gold but player only has {player_gold} gold.",
                    "item_name": item_name,
                    "price": price,
                    "player_gold": player_gold,
                    "shortfall": price - player_gold,
                    "inventory_changes": {},
                    "gold_change": 0
                }
            
            # SUCCESS — Execute purchase
            c.execute("UPDATE Players SET gold = gold - ? WHERE player_name = ?", (price, player_name))
            c.execute("""
                INSERT INTO Inventory (player_name, item_id, quantity) VALUES (?, ?, 1)
                ON CONFLICT(player_name, item_id) DO UPDATE SET quantity = quantity + 1
            """, (player_name, item_id))
            c.execute("UPDATE ShopItems SET stock = stock - 1 WHERE npc_name = ? AND item_id = ?", (npc_name, item_id))
            conn.commit()
            
            # Check quest progression if Frostbane Katana was bought
            quest_updates = {}
            if item_id == "frostbane_katana" and npc_name == "Mira":
                QuestEngine.update_quest(
                    player_name, "main_frostbane", "completed", 2,
                    {"item_acquired": "Frostbane Katana", "gold_spent": price}
                )
                QuestEngine.update_quest(
                    player_name, "main_enter_keep", "in_progress", 1,
                    {"requirement": "Present Frostbane to Captain Aldric"}
                )
                quest_updates = {"quest_id": "main_frostbane", "status": "completed", "step": 2}
            
            return {
                "success": True,
                "reason": "purchase_complete",
                "message": f"Player bought {item_name} for {price} gold. Remaining gold: {player_gold - price}.",
                "item_name": item_name,
                "price": price,
                "player_gold": player_gold - price,
                "inventory_changes": {"gold": -price, "items_added": [item_name], "items_removed": []},
                "gold_change": -price,
                "quest_updates": quest_updates
            }

    # ── Shop / Sell ───────────────────────────────────────────────────
    @staticmethod
    def validate_sale(player_name: str, item_keyword: str, npc_name: str) -> dict:
        """Check if player can sell an item. Returns result for LLM context."""
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            
            # Find item in player inventory
            c.execute("""
                SELECT inv.item_id, i.item_name, i.base_price, inv.quantity, i.category
                FROM Inventory inv
                JOIN Items i ON inv.item_id = i.item_id
                WHERE inv.player_name = ? AND (LOWER(i.item_name) LIKE ? OR LOWER(inv.item_id) LIKE ?)
            """, (player_name, f"%{item_keyword}%", f"%{item_keyword.replace(' ', '_')}%"))
            row = c.fetchone()
            
            if not row:
                return {
                    "success": False,
                    "reason": "item_not_in_inventory",
                    "message": f"Player does not have any item matching '{item_keyword}' in inventory.",
                    "inventory_changes": {},
                    "gold_change": 0
                }
                
            item_id, item_name, base_price, quantity, category = row
            buyback_price = max(1, int(base_price * 0.5))
            
            # Deduct 1 item from player inventory
            if quantity > 1:
                c.execute("""
                    UPDATE Inventory SET quantity = quantity - 1
                    WHERE player_name = ? AND item_id = ?
                """, (player_name, item_id))
            else:
                c.execute("""
                    DELETE FROM Inventory WHERE player_name = ? AND item_id = ?
                """, (player_name, item_id))
                
            # Add gold to player
            c.execute("UPDATE Players SET gold = gold + ? WHERE player_name = ?", (buyback_price, player_name))
            
            # Increase shop stock
            c.execute("""
                INSERT OR IGNORE INTO ShopItems (npc_name, item_id, stock, sell_price, buy_price)
                VALUES (?, ?, 0, ?, ?)
            """, (npc_name, item_id, base_price, buyback_price))
            c.execute("""
                UPDATE ShopItems SET stock = stock + 1
                WHERE npc_name = ? AND item_id = ?
            """, (npc_name, item_id))
            
            conn.commit()
            
            return {
                "success": True,
                "reason": "sale_complete",
                "message": f"Player sold {item_name} to {npc_name} for {buyback_price} gold.",
                "item_name": item_name,
                "price": buyback_price,
                "inventory_changes": {"gold": buyback_price, "items_added": [], "items_removed": [item_name]},
                "gold_change": buyback_price
            }

    # ── Quest Accept / Complete ────────────────────────────────────────
    @staticmethod
    def validate_accept_quest(player_name: str, npc_name: str) -> dict:
        """Process accepting a quest from an NPC."""
        quest_id = None
        quest_name = None
        
        if npc_name == "Mira":
            quest_id = "main_frostbane"
            quest_name = "Find the Frostbane Katana"
        elif npc_name == "Captain Aldric":
            quest_id = "main_enter_keep"
            quest_name = "Gain Entry to the Inner Keep"
        elif npc_name == "Elder Thorn":
            quest_id = "side_elder_relic"
            quest_name = "The Ancient Relic"
        elif npc_name == "Shade":
            quest_id = "side_shadow_guild"
            quest_name = "Shadow Guild Initiation"
            
        if not quest_id:
            return {
                "success": False,
                "reason": "no_quest_available",
                "message": f"{npc_name} has no quests to offer.",
                "quest_updates": {}
            }
            
        # Check current state
        state = QuestEngine.get_quest_state(player_name, quest_id)
        if state and state["status"] in ("in_progress", "completed"):
            return {
                "success": False,
                "reason": "already_started_or_completed",
                "message": f"Quest '{quest_name}' is already {state['status']}.",
                "quest_updates": {}
            }
            
        # Specific check for Captain Aldric
        if quest_id == "main_enter_keep":
            fb_state = QuestEngine.get_quest_state(player_name, "main_frostbane")
            if not fb_state or fb_state["status"] != "completed":
                return {
                    "success": False,
                    "reason": "prerequisite_missing",
                    "message": "Captain Aldric will not permit you to accept this quest until you obtain the Frostbane Katana first.",
                    "quest_updates": {}
                }
                
        # Accept quest
        QuestEngine.update_quest(player_name, quest_id, "in_progress", 1, {"started": True})
        
        return {
            "success": True,
            "reason": "quest_accepted",
            "message": f"Player accepted quest '{quest_name}' from {npc_name}.",
            "quest_updates": {"quest_id": quest_id, "status": "in_progress", "step": 1}
        }

    @staticmethod
    def validate_complete_quest(player_name: str, npc_name: str) -> dict:
        """Process completing a quest with an NPC."""
        quest_id = None
        quest_name = None
        
        if npc_name == "Mira":
            quest_id = "main_frostbane"
            quest_name = "Find the Frostbane Katana"
        elif npc_name == "Captain Aldric":
            quest_id = "main_enter_keep"
            quest_name = "Gain Entry to the Inner Keep"
        elif npc_name == "Elder Thorn":
            quest_id = "side_elder_relic"
            quest_name = "The Ancient Relic"
        elif npc_name == "Shade":
            quest_id = "side_shadow_guild"
            quest_name = "Shadow Guild Initiation"
            
        if not quest_id:
            return {
                "success": False,
                "reason": "no_quest_associated",
                "message": f"{npc_name} does not manage any quests.",
                "quest_updates": {}
            }
            
        state = QuestEngine.get_quest_state(player_name, quest_id)
        if not state or state["status"] != "in_progress":
            return {
                "success": False,
                "reason": "quest_not_in_progress",
                "message": f"Quest '{quest_name}' is not currently in progress.",
                "quest_updates": {}
            }
            
        # Completion conditions
        if quest_id == "main_frostbane":
            inv = GameLogic.get_player_inventory(player_name)
            has_katana = any("katana" in i["name"].lower() or "frostbane" in i["name"].lower() for i in inv["items"])
            if has_katana:
                QuestEngine.update_quest(player_name, quest_id, "completed", 2, {"completed": True})
                QuestEngine.update_quest(player_name, "main_enter_keep", "in_progress", 1, {"requirement": "Present Frostbane to Captain Aldric"})
                return {
                    "success": True,
                    "reason": "quest_completed",
                    "message": f"Quest '{quest_name}' completed. You acquired the Frostbane Katana!",
                    "quest_updates": {"quest_id": quest_id, "status": "completed", "step": 2}
                }
            else:
                return {
                    "success": False,
                    "reason": "requirements_not_met",
                    "message": "You must buy the Frostbane Katana from Mira to complete this quest.",
                    "quest_updates": {}
                }
                
        elif quest_id == "main_enter_keep":
            inv = GameLogic.get_player_inventory(player_name)
            has_katana = False
            for item in inv["items"]:
                if "katana" in item["name"].lower() or "frostbane" in item["name"].lower():
                    has_katana = True
                    break
            
            if has_katana:
                with sqlite3.connect(DB_PATH) as conn:
                    c = conn.cursor()
                    c.execute("DELETE FROM Inventory WHERE player_name = ? AND item_id = 'frostbane_katana'", (player_name,))
                    c.execute("UPDATE Players SET gold = gold + 50 WHERE player_name = ?", (player_name,))
                    conn.commit()
                    
                QuestEngine.update_quest(player_name, quest_id, "completed", 2, {"gate_opened": True})
                return {
                    "success": True,
                    "reason": "quest_completed",
                    "message": f"Quest '{quest_name}' completed. Captain Aldric opened the gates and rewarded you with 50 Gold!",
                    "quest_updates": {"quest_id": quest_id, "status": "completed", "step": 2},
                    "inventory_changes": {"gold": 50, "items_added": [], "items_removed": ["Frostbane Katana"]},
                    "gold_change": 50
                }
            else:
                return {
                    "success": False,
                    "reason": "requirements_not_met",
                    "message": "You need to show the Frostbane Katana to Captain Aldric to gain entry.",
                    "quest_updates": {}
                }
                
        elif quest_id == "side_elder_relic":
            rel = GameLogic.get_relationship(player_name, npc_name)
            if rel["trust"] >= 70:
                with sqlite3.connect(DB_PATH) as conn:
                    c = conn.cursor()
                    c.execute("""
                        INSERT OR IGNORE INTO Inventory (player_name, item_id, quantity)
                        VALUES (?, 'dragon_scale', 1)
                        ON CONFLICT(player_name, item_id) DO UPDATE SET quantity = quantity + 1
                    """, (player_name,))
                    conn.commit()
                QuestEngine.update_quest(player_name, quest_id, "completed", 2, {"relic_revealed": True})
                return {
                    "success": True,
                    "reason": "quest_completed",
                    "message": f"Quest '{quest_name}' completed. Elder Thorn shared the relic location and rewarded you with a Dragon Scale!",
                    "quest_updates": {"quest_id": quest_id, "status": "completed", "step": 2},
                    "inventory_changes": {"gold": 0, "items_added": ["Dragon Scale"], "items_removed": []}
                }
            else:
                return {
                    "success": False,
                    "reason": "requirements_not_met",
                    "message": f"Elder Thorn does not trust you enough yet (Trust: {rel['trust']}/70 required).",
                    "quest_updates": {}
                }
                
        elif quest_id == "side_shadow_guild":
            rel = GameLogic.get_relationship(player_name, npc_name)
            if rel["trust"] >= 60:
                with sqlite3.connect(DB_PATH) as conn:
                    c = conn.cursor()
                    c.execute("UPDATE Players SET gold = gold + 40 WHERE player_name = ?", (player_name,))
                    conn.commit()
                QuestEngine.update_quest(player_name, quest_id, "completed", 2, {"joined_guild": True})
                return {
                    "success": True,
                    "reason": "quest_completed",
                    "message": f"Quest '{quest_name}' completed. Shade welcomes you to the guild and hands you 40 Gold!",
                    "quest_updates": {"quest_id": quest_id, "status": "completed", "step": 2},
                    "inventory_changes": {"gold": 40, "items_added": [], "items_removed": []},
                    "gold_change": 40
                }
            else:
                return {
                    "success": False,
                    "reason": "requirements_not_met",
                    "message": f"Shade does not trust your loyalty yet (Trust: {rel['trust']}/60 required).",
                    "quest_updates": {}
                }
                
        return {
            "success": False,
            "reason": "unknown_quest",
            "message": "This quest cannot be completed at this time.",
            "quest_updates": {}
        }

    # ── Inventory Query ────────────────────────────────────────────────
    @staticmethod
    def get_shop_inventory(npc_name: str) -> list[dict]:
        """Get what an NPC shop currently sells."""
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT i.item_name, i.category, i.description, si.sell_price, si.stock
                FROM ShopItems si
                JOIN Items i ON si.item_id = i.item_id
                WHERE si.npc_name = ? AND si.stock > 0
            """, (npc_name,))
            rows = c.fetchall()
        
        return [{"name": r[0], "category": r[1], "description": r[2], "price": r[3], "stock": r[4]} for r in rows]

    @staticmethod
    def get_player_inventory(player_name: str) -> dict:
        """Get player's full inventory."""
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT gold, character_class FROM Players WHERE player_name = ?", (player_name,))
            player = c.fetchone()
            gold = player[0] if player else 0
            char_class = player[1] if player else "warrior"
            
            c.execute("""
                SELECT i.item_name, i.category, inv.quantity
                FROM Inventory inv
                JOIN Items i ON inv.item_id = i.item_id
                WHERE inv.player_name = ?
            """, (player_name,))
            items = [{"name": r[0], "category": r[1], "quantity": r[2]} for r in c.fetchall()]
        
        return {"gold": gold, "character_class": char_class, "items": items}

    # ── Relationship ───────────────────────────────────────────────────
    @staticmethod
    def get_relationship(player_name: str, npc_name: str) -> dict:
        """Get relationship scores between player and NPC."""
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT trust, friendship, respect, suspicion
                FROM Relationships
                WHERE player_name = ? AND npc_name = ?
            """, (player_name, npc_name))
            row = c.fetchone()
        
        if row:
            return {"trust": row[0], "friendship": row[1], "respect": row[2], "suspicion": row[3]}
        return {"trust": 50, "friendship": 50, "respect": 50, "suspicion": 0}

    @staticmethod
    def update_relationship(player_name: str, npc_name: str, 
                           trust_delta: int = 0, friendship_delta: int = 0,
                           respect_delta: int = 0, suspicion_delta: int = 0) -> dict:
        """Update relationship values."""
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO Relationships (player_name, npc_name, trust, friendship, respect, suspicion)
                VALUES (?, ?, 50, 50, 50, 0)
                ON CONFLICT(player_name, npc_name) DO NOTHING
            """, (player_name, npc_name))
            
            c.execute("""
                UPDATE Relationships SET
                    trust = MIN(100, MAX(0, trust + ?)),
                    friendship = MIN(100, MAX(0, friendship + ?)),
                    respect = MIN(100, MAX(0, respect + ?)),
                    suspicion = MIN(100, MAX(0, suspicion + ?))
                WHERE player_name = ? AND npc_name = ?
            """, (trust_delta, friendship_delta, respect_delta, suspicion_delta, player_name, npc_name))
            conn.commit()
        
        return GameLogic.get_relationship(player_name, npc_name)

    # ── Memory ─────────────────────────────────────────────────────────
    @staticmethod
    def add_memory(player_name: str, npc_name: str, memory_type: str, description: str):
        """Store a memory for NPC recall."""
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO Memories (player_name, npc_name, memory_type, description, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (player_name, npc_name, memory_type, description, datetime.now().isoformat()))
            conn.commit()

    @staticmethod
    def get_memories(player_name: str, npc_name: str, limit: int = 5) -> list[str]:
        """Retrieve recent memories for LLM context."""
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT description FROM Memories
                WHERE player_name = ? AND npc_name = ?
                ORDER BY timestamp DESC LIMIT ?
            """, (player_name, npc_name, limit))
            return [r[0] for r in c.fetchall()]

    @staticmethod
    def get_visit_count(player_name: str, npc_name: str) -> int:
        """Count how many times the player has spoken with this NPC."""
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM Conversations WHERE player_name = ? AND npc_name = ?", (player_name, npc_name))
            row = c.fetchone()
            return row[0] if row else 0

    @staticmethod
    def get_recent_interactions(player_name: str, npc_name: str, limit: int = 3) -> list[dict]:
        """Return a short summary of the most recent player/NPC exchanges."""
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT player_input, npc_response FROM Conversations WHERE player_name = ? AND npc_name = ? AND player_input != '' ORDER BY timestamp DESC LIMIT ?", (player_name, npc_name, limit))
            rows = c.fetchall()
        return [{"player": r[0], "npc": r[1]} for r in rows]

    # ── NPC Options Generator ──────────────────────────────────────────
    @staticmethod
    def get_npc_options(npc_name: str, player_name: str, intent_result: dict = None) -> list[str]:
        """Generate contextual dialogue options for the player. ALWAYS returns options."""
        inv = GameLogic.get_player_inventory(player_name)
        rel = GameLogic.get_relationship(player_name, npc_name)
        
        # Get NPC type
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT allowed_actions FROM NPCs WHERE npc_name = ?", (npc_name,))
            row = c.fetchone()
        npc_action = row[0] if row else "none"
        
        # Base options per NPC type
        if npc_action == "sell_katana":
            options = [
                "What weapons do you have for sale?",
                "How much gold do I need for the Frostbane Katana?",
                "Do you have any potions?",
            ]
            if inv["gold"] >= 50:
                options.insert(1, "I'd like to buy the Frostbane Katana.")
            if any(item["name"] for item in inv["items"]):
                options.insert(-1, "I'd like to sell something.")
                
        elif npc_action == "open_gate":
            has_katana = any("katana" in i["name"].lower() or "frostbane" in i["name"].lower() for i in inv["items"])
            if has_katana:
                options = [
                    "I have the Frostbane Katana. May I enter?",
                    "What lies beyond the gate?",
                    "Tell me about the Royal Guard.",
                ]
            else:
                options = [
                    "What do I need to enter the keep?",
                    "Tell me about the threats beyond the mountains.",
                    "Who commands the Royal Guard?",
                ]
                
        elif npc_action == "reveal_secret":
            if rel["trust"] >= 70:
                options = [
                    "Will you share the secret of the ancient relic?",
                    "What wisdom do the forest spirits offer?",
                    "Tell me about the Thornwall Mountains.",
                ]
            else:
                options = [
                    "I seek your wisdom, Elder.",
                    "What can you teach me about this land?",
                    "How can I earn the forest's trust?",
                ]
                
        elif npc_action == "offer_mission":
            if rel["trust"] >= 40:
                options = [
                    "Do you have a job for someone with... discretion?",
                    "What's the Shadow Guild really about?",
                    "I can keep a secret. Try me.",
                ]
            else:
                options = [
                    "I'm looking for work. Unconventional work.",
                    "I've heard rumors about the Shadow Guild.",
                    "Can I buy you a drink?",
                ]
        else:
            options = [
                "Tell me about yourself.",
                "What's happening in Kingdom Frontier?",
                "Do you need any help?",
            ]
        
        # Always add goodbye
        options.append("Farewell.")
        return options[:5]  # Max 5 options

    # ── Context Builder for LLM ────────────────────────────────────────
    @staticmethod
    def build_game_context(player_name: str, npc_name: str, intent_result: dict,
                           action_result: dict = None) -> str:
        """Build a structured context string that tells the LLM what happened.
        The LLM must ONLY describe what's in this context, never invent outcomes."""
        
        inv = GameLogic.get_player_inventory(player_name)
        rel = GameLogic.get_relationship(player_name, npc_name)
        memories = GameLogic.get_memories(player_name, npc_name)
        
        lines = []
        lines.append(f"[GAME STATE - The LLM must describe ONLY what is stated here]")
        lines.append(f"Player '{player_name}' (Class: {inv['character_class']})")
        lines.append(f"Gold: {inv['gold']}")
        
        if inv['items']:
            item_list = ", ".join(f"{i['name']} x{i['quantity']}" for i in inv['items'])
            lines.append(f"Inventory: {item_list}")
        else:
            lines.append("Inventory: Empty")
        
        lines.append(f"Relationship — Trust: {rel['trust']}, Friendship: {rel['friendship']}, "
                     f"Respect: {rel['respect']}, Suspicion: {rel['suspicion']}")
        
        visit_count = GameLogic.get_visit_count(player_name, npc_name)
        if visit_count > 1:
            lines.append(f"Visit count with {npc_name}: {visit_count}")
            recent = GameLogic.get_recent_interactions(player_name, npc_name, limit=2)
            if recent:
                lines.append("Recent shared scenes:")
                for turn in recent:
                    lines.append(f"  - Player: {turn['player']} | NPC: {turn['npc']}")
        
        lines.append(f"Detected intent: {intent_result['intent']}")
        
        if action_result:
            if action_result.get("reason") not in ("greeting", "conversation", "farewell"):
                lines.append(f"Action result: {action_result['reason']}")
                lines.append(f"Detail: {action_result['message']}")
            else:
                lines.append(f"Action result: {action_result['reason']} (general conversation, feel free to chat)")
        
        if memories:
            lines.append("NPC memories of this player:")
            for m in memories:
                lines.append(f"  - {m}")
        
        return "\n".join(lines)

    # ── Process Full Intent ────────────────────────────────────────────
    @staticmethod
    def process_intent(player_name: str, npc_name: str, player_input: str,
                       character_class: str = "warrior") -> dict:
        """Main entry point: detect intent → validate → build context → return everything."""
        
        intent = detect_intent(player_input)
        action_result = None
        inventory_changes = {}
        quest_updates = {}
        relationship_updates = {}
        memory_updates = []
        
        # ── Handle each intent ──────────────────────────────────────
        if intent["intent"] == "buy_item" and intent["item"]:
            action_result = GameLogic.validate_purchase(player_name, intent["item"], npc_name)
            inventory_changes = action_result.get("inventory_changes", {})
            quest_updates = action_result.get("quest_updates", {})
            
            if action_result["success"]:
                GameLogic.update_relationship(player_name, npc_name, trust_delta=5, friendship_delta=3)
                memory_desc = f"Bought {action_result['item_name']} for {action_result['price']} gold"
                GameLogic.add_memory(player_name, npc_name, "purchase", memory_desc)
                memory_updates.append(memory_desc)
                relationship_updates = {"trust": 5, "friendship": 3}
            else:
                GameLogic.update_relationship(player_name, npc_name, trust_delta=1)
                relationship_updates = {"trust": 1}
        
        elif intent["intent"] == "buy_item" and not intent["item"]:
            shop = GameLogic.get_shop_inventory(npc_name)
            if shop:
                item_list = "\n".join(f"  - {i['name']}: {i['price']} gold ({i['description']})" for i in shop)
                action_result = {
                    "success": False,
                    "reason": "show_shop",
                    "message": f"Available items:\n{item_list}"
                }
            else:
                action_result = {
                    "success": False,
                    "reason": "no_shop",
                    "message": "This NPC doesn't sell items."
                }
                
        elif intent["intent"] == "sell_item" and intent["item"]:
            action_result = GameLogic.validate_sale(player_name, intent["item"], npc_name)
            inventory_changes = action_result.get("inventory_changes", {})
            
            if action_result["success"]:
                GameLogic.update_relationship(player_name, npc_name, trust_delta=3, respect_delta=4)
                memory_desc = f"Sold {action_result['item_name']} for {action_result['price']} gold"
                GameLogic.add_memory(player_name, npc_name, "sale", memory_desc)
                memory_updates.append(memory_desc)
                relationship_updates = {"trust": 3, "respect": 4}
            else:
                GameLogic.update_relationship(player_name, npc_name, suspicion_delta=2)
                relationship_updates = {"suspicion": 2}
                
        elif intent["intent"] == "sell_item" and not intent["item"]:
            inv = GameLogic.get_player_inventory(player_name)
            if inv["items"]:
                item_list = "\n".join(f"  - {i['name']} (Quantity: {i['quantity']})" for i in inv["items"])
                action_result = {
                    "success": False,
                    "reason": "list_selling_possibilities",
                    "message": f"You have these items to sell:\n{item_list}"
                }
            else:
                action_result = {
                    "success": False,
                    "reason": "empty_inventory",
                    "message": "You have no items in your inventory to sell."
                }
        
        elif intent["intent"] in ("ask_inventory", "trade"):
            shop = GameLogic.get_shop_inventory(npc_name)
            if shop:
                item_list = "\n".join(f"  - {i['name']}: {i['price']} gold" for i in shop)
                action_result = {
                    "success": True,
                    "reason": "shop_listing",
                    "message": f"Shop inventory:\n{item_list}"
                }
            else:
                action_result = {
                    "success": True,
                    "reason": "no_shop",
                    "message": "This NPC doesn't operate a shop."
                }
        
        elif intent["intent"] == "greeting":
            GameLogic.update_relationship(player_name, npc_name, friendship_delta=2)
            relationship_updates = {"friendship": 2}
            GameLogic.add_memory(player_name, npc_name, "greeting", "Player greeted the NPC")
            action_result = {"success": True, "reason": "greeting", "message": "Player greeted the NPC."}
        
        elif intent["intent"] == "goodbye":
            action_result = {"success": True, "reason": "farewell", "message": "Player said goodbye."}
            GameLogic.add_memory(player_name, npc_name, "goodbye", "Player said farewell")
        
        elif intent["intent"] == "ask_quest":
            action_result = {"success": True, "reason": "quest_inquiry", "message": "Player is asking about available quests or tasks."}
            GameLogic.update_relationship(player_name, npc_name, respect_delta=2)
            relationship_updates = {"respect": 2}
            
        elif intent["intent"] == "accept_quest":
            action_result = GameLogic.validate_accept_quest(player_name, npc_name)
            quest_updates = action_result.get("quest_updates", {})
            if action_result["success"]:
                GameLogic.update_relationship(player_name, npc_name, trust_delta=4, respect_delta=5)
                memory_desc = f"Accepted quest from {npc_name}"
                GameLogic.add_memory(player_name, npc_name, "quest", memory_desc)
                memory_updates.append(memory_desc)
                relationship_updates = {"trust": 4, "respect": 5}
                
        elif intent["intent"] == "complete_quest":
            action_result = GameLogic.validate_complete_quest(player_name, npc_name)
            quest_updates = action_result.get("quest_updates", {})
            inventory_changes = action_result.get("inventory_changes", {})
            
            if action_result["success"]:
                GameLogic.update_relationship(player_name, npc_name, trust_delta=10, friendship_delta=8, respect_delta=10)
                memory_desc = f"Completed quest for {npc_name}"
                GameLogic.add_memory(player_name, npc_name, "quest", memory_desc)
                memory_updates.append(memory_desc)
                relationship_updates = {"trust": 10, "friendship": 8, "respect": 10}
            else:
                GameLogic.update_relationship(player_name, npc_name, trust_delta=-2)
                relationship_updates = {"trust": -2}
                
        elif intent["intent"] == "ask_location":
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                c.execute("SELECT location FROM NPCs WHERE npc_name = ?", (npc_name,))
                loc_row = c.fetchone()
                loc_name = loc_row[0] if loc_row else "Unknown"
            
            action_result = {
                "success": True,
                "reason": "location_info",
                "message": f"The NPC is located at {loc_name}. It's a key hub in Kingdom Frontier."
            }
            GameLogic.add_memory(player_name, npc_name, "inquiry", f"Player asked about location {loc_name}")
            
        elif intent["intent"] == "ask_about_npc":
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                c.execute("SELECT personality FROM NPCs WHERE npc_name = ?", (npc_name,))
                p_row = c.fetchone()
                personality = p_row[0] if p_row else "Unknown"
            
            action_result = {
                "success": True,
                "reason": "npc_lore",
                "message": f"This is {npc_name}. Personality profile: {personality}"
            }
            GameLogic.add_memory(player_name, npc_name, "inquiry", f"Player asked about NPC background")
        
        else:
            # General conversation
            GameLogic.update_relationship(player_name, npc_name, friendship_delta=1)
            relationship_updates = {"friendship": 1}
            action_result = {"success": True, "reason": "conversation", "message": "General conversation."}
        
        # Build game context for LLM
        game_context = GameLogic.build_game_context(player_name, npc_name, intent, action_result)
        
        # Generate options for next turn
        options = GameLogic.get_npc_options(npc_name, player_name, intent)
        
        return {
            "intent": intent,
            "action_result": action_result,
            "game_context": game_context,
            "player_options": options,
            "inventory_changes": inventory_changes,
            "quest_updates": quest_updates,
            "relationship_updates": relationship_updates,
            "memory_updates": memory_updates
        }
