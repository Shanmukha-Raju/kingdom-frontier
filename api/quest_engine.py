"""
Kingdom Frontier — Quest Engine & Emotion Tracker
Lightweight quest state machine and NPC emotion/trust scoring system.
"""

import os
import sqlite3
import json
from datetime import datetime

from create_db import DB_PATH

# ─── Emotion constants ────────────────────────────────────────────────
EMOTION_STATES = ["hostile", "distrustful", "neutral", "friendly", "grateful"]

POSITIVE_KEYWORDS = [
    "help", "please", "thank", "kind", "honor", "protect", "save",
    "friend", "ally", "trust", "respect", "brave", "noble", "agree",
    "happy to", "glad to", "of course", "certainly", "yes"
]

NEGATIVE_KEYWORDS = [
    "threat", "kill", "steal", "lie", "hate", "demand", "fool",
    "idiot", "waste", "shut up", "don't care", "get lost", "leave me",
    "refuse", "no way", "never", "pathetic", "worthless"
]

NEUTRAL_KEYWORDS = [
    "goodbye", "farewell", "see you", "later", "maybe", "not sure",
    "tell me more", "what", "where", "how", "who", "why", "explain"
]


# ─── Quest Engine ──────────────────────────────────────────────────────

class QuestEngine:
    """Manages quest states for players in the Kingdom Frontier."""

    @staticmethod
    def get_quest_state(player_name: str, quest_id: str) -> dict | None:
        """Get the current state of a specific quest for a player."""
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT player_name, quest_id, status, current_step, flags, updated_at
                FROM QuestState
                WHERE player_name = ? AND quest_id = ?
            """, (player_name, quest_id))
            row = cursor.fetchone()

        if not row:
            return None

        return {
            "player_name": row[0],
            "quest_id": row[1],
            "status": row[2],
            "current_step": row[3],
            "flags": json.loads(row[4]) if row[4] else {},
            "updated_at": row[5]
        }

    @staticmethod
    def update_quest(player_name: str, quest_id: str, new_status: str, 
                     step: int, flags: dict | None = None) -> dict:
        """Update or create a quest state entry."""
        flags_json = json.dumps(flags or {})
        now = datetime.now().isoformat()

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO QuestState (player_name, quest_id, status, current_step, flags, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(player_name, quest_id) DO UPDATE SET
                    status = excluded.status,
                    current_step = excluded.current_step,
                    flags = excluded.flags,
                    updated_at = excluded.updated_at
            """, (player_name, quest_id, new_status, step, flags_json, now))
            
            try:
                cursor.execute("UPDATE Players SET quest_complete_alert = 1 WHERE player_name = ?", (player_name,))
            except Exception:
                pass
                
            conn.commit()

        return {
            "player_name": player_name,
            "quest_id": quest_id,
            "status": new_status,
            "current_step": step,
            "flags": flags or {},
            "updated_at": now
        }

    @staticmethod
    def get_active_quests(player_name: str) -> list[dict]:
        """Get all active quests for a player."""
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT player_name, quest_id, status, current_step, flags, updated_at
                FROM QuestState
                WHERE player_name = ? AND status != 'completed'
            """, (player_name,))
            rows = cursor.fetchall()

        return [{
            "player_name": row[0],
            "quest_id": row[1],
            "status": row[2],
            "current_step": row[3],
            "flags": json.loads(row[4]) if row[4] else {},
            "updated_at": row[5]
        } for row in rows]

    @staticmethod
    def get_all_quests(player_name: str) -> list[dict]:
        """Get all quests (any status) for a player."""
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT player_name, quest_id, status, current_step, flags, updated_at
                FROM QuestState
                WHERE player_name = ?
            """, (player_name,))
            rows = cursor.fetchall()

        return [{
            "player_name": row[0],
            "quest_id": row[1],
            "status": row[2],
            "current_step": row[3],
            "flags": json.loads(row[4]) if row[4] else {},
            "updated_at": row[5]
        } for row in rows]

    @staticmethod
    def get_quest_context_for_prompt(player_name: str) -> str:
        """Build a text summary of the player's quest state for LLM context injection."""
        quests = QuestEngine.get_all_quests(player_name)
        if not quests:
            return "No quests started yet. The adventurer is new to Kingdom Frontier."

        lines = []
        for q in quests:
            quest_names = {
                "main_frostbane": "Find the Frostbane Katana",
                "main_enter_keep": "Gain Entry to the Inner Keep",
                "side_shadow_guild": "Shadow Guild Initiation",
                "side_elder_relic": "The Ancient Relic",
                "side_boar_hunter": "The Boar Hunt",
                "side_castle_scavenger": "Castle Scavenger"
            }
            name = quest_names.get(q["quest_id"], q["quest_id"])
            lines.append(f"- Quest '{name}': {q['status']} (step {q['current_step']})")
            if q["flags"]:
                for k, v in q["flags"].items():
                    lines.append(f"    {k}: {v}")

        return "Player's quest progress:\n" + "\n".join(lines)


# ─── Emotion Tracker ──────────────────────────────────────────────────

class EmotionTracker:
    """Tracks NPC emotion states and trust levels."""

    @staticmethod
    def get_npc_emotion(npc_name: str) -> dict:
        """Get the current emotion state and trust level for an NPC."""
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT emotion_state, trust_level
                FROM NPCs
                WHERE npc_name = ?
            """, (npc_name,))
            row = cursor.fetchone()

        if not row:
            return {"emotion_state": "neutral", "trust_level": 50}

        return {"emotion_state": row[0], "trust_level": row[1]}

    @staticmethod
    def _classify_sentiment(player_text: str) -> str:
        """Simple keyword-based sentiment classification."""
        text_lower = player_text.lower()

        pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in text_lower)
        neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text_lower)

        if neg_count > pos_count:
            return "negative"
        elif pos_count > neg_count:
            return "positive"
        return "neutral"

    @staticmethod
    def _compute_trust_delta(sentiment: str, choice_index: int) -> int:
        """Compute trust change based on sentiment and choice index.
        
        Choice index mapping:
          1 = typically positive/helpful
          2 = typically inquisitive/neutral  
          3 = typically risky/bold
          4 = goodbye/neutral (always 0)
          -1 = free text (use sentiment only)
        """
        base_deltas = {
            "positive": 8,
            "neutral": 0,
            "negative": -10
        }
        delta = base_deltas.get(sentiment, 0)

        # Modify based on choice pattern
        if choice_index == 1:
            delta = max(delta, 5)  # Positive floor for choice 1
        elif choice_index == 3:
            delta = min(delta, -3) if sentiment == "negative" else delta
        elif choice_index == 4:
            delta = 0  # Goodbye is always neutral

        return delta

    @staticmethod
    def _resolve_emotion(trust_level: int) -> str:
        """Map trust level to emotion state."""
        if trust_level >= 80:
            return "grateful"
        elif trust_level >= 60:
            return "friendly"
        elif trust_level >= 40:
            return "neutral"
        elif trust_level >= 20:
            return "distrustful"
        return "hostile"

    @staticmethod
    def update_emotion(npc_name: str, player_text: str, choice_index: int = -1) -> dict:
        """Update NPC emotion based on player's dialogue choice.
        
        Returns the new emotion state dict.
        """
        current = EmotionTracker.get_npc_emotion(npc_name)
        sentiment = EmotionTracker._classify_sentiment(player_text)
        trust_delta = EmotionTracker._compute_trust_delta(sentiment, choice_index)

        new_trust = max(0, min(100, current["trust_level"] + trust_delta))
        new_emotion = EmotionTracker._resolve_emotion(new_trust)

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE NPCs SET emotion_state = ?, trust_level = ?
                WHERE npc_name = ?
            """, (new_emotion, new_trust, npc_name))
            conn.commit()

        return {
            "emotion_state": new_emotion,
            "trust_level": new_trust,
            "trust_delta": trust_delta,
            "sentiment": sentiment
        }
