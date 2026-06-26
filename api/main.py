"""
Kingdom Frontier — RPG NPC Dialogue Engine API
FastAPI backend with local Qwen2.5 LLM, quest tracking, and emotion system.
"""

import logging
import os
import sqlite3
import json
from contextlib import asynccontextmanager
from enum import Enum
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, Field, model_validator

from google import genai
from google.genai import types
from dotenv import load_dotenv

from langchain_core.prompts import PromptTemplate
from build_vector_store import load_or_build_vector_store
from create_db import initialize_database, DB_PATH
from quest_engine import QuestEngine, EmotionTracker
from game_logic import GameLogic

# ─── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)

# ─── Enums & Models ──────────────────────────────────────────────────

class NameCheckQuery(BaseModel):
    player_name: str


class NameCheckResponse(BaseModel):
    available: bool


class RegisterRequest(BaseModel):
    player_name: str
    character_class: str = "warrior"


class UpdateClassRequest(BaseModel):
    player_name: str
    character_class: str


class Query(BaseModel):
    player_name: str = "Adventurer"
    npc_name: str = "Mira"
    held_items: Optional[str] = ""
    player_input: Optional[str] = ""
    selected_option_index: Optional[int] = -1  # -1 = free text, 0-3 = choice

    @model_validator(mode='before')
    @classmethod
    def auto_decode_json_string(cls, value):
        if isinstance(value, (str, bytes)):
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="ignore")
            try:
                return json.loads(value)
            except Exception:
                pass
        return value


class RPGResponse(BaseModel):
    npc_response: str = Field(description="What the NPC says")
    player_options: list[str] = Field(description="Dialogue choices for the player")
    sentiment: str = Field(description="Detected player sentiment for tone", default="neutral")
    inventory_changes: dict = Field(description="Changes to player inventory", default_factory=dict)
    quest_updates: dict = Field(description="Changes to quests status", default_factory=dict)
    relationship_updates: dict = Field(description="Changes to NPC relationships", default_factory=dict)
    memory_updates: list[str] = Field(description="Memories recorded in this turn", default_factory=list)


# ─── Global Resources ────────────────────────────────────────────────
vector_store = None
gemini_client = None


class GeminiResponseSchema(BaseModel):
    npc_response: str = Field(description="What the NPC says to the player describing the outcome and current state in character")
    player_options: list[str] = Field(description="Exactly 4 dynamic player response options contextually relevant to the scene, with the 4th option always being a farewell/goodbye")


# ─── Lifespan ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global vector_store, gemini_client

    initialize_database()

    print("\n[INFO] Initializing Gemini API Client...")
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[WARNING] GEMINI_API_KEY is not set in environment or .env file!")
    else:
        print("[INFO] Gemini API Key loaded successfully.")
    
    gemini_client = genai.Client(api_key=api_key)

    vector_store = load_or_build_vector_store(None)

    print("[INFO] Kingdom Frontier NPC Engine is ready!\n")
    yield


app = FastAPI(title="Kingdom Frontier NPC Engine", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def extract_json_block(text: str) -> str:
    """Find and extract the first valid JSON object from a string, handling nested braces."""
    start_idx = text.find("{")
    if start_idx == -1:
        return text
        
    brace_count = 0
    in_string = False
    escape = False
    
    for idx in range(start_idx, len(text)):
        char = text[idx]
        
        if escape:
            escape = False
            continue
            
        if char == "\\":
            escape = True
            continue
            
        if char == '"':
            in_string = not in_string
            continue
            
        if not in_string:
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    return text[start_idx:idx+1]
                    
    return text[start_idx:]


def parse_llm_response(raw_output: str) -> dict:
    """Extract structured JSON from the LLM's raw text output, falling back to robust regex if malformed."""
    if isinstance(raw_output, dict):
        text = str(raw_output.get("text", raw_output))
    elif hasattr(raw_output, "text"):
        text = str(raw_output.text)
    else:
        text = str(raw_output)

    # Clip at any "Player:" leakage
    for stop in ["Player:", "\nPlayer", "Player says:", "**Player response:**", "**NPC response:**"]:
        if stop in text:
            text = text.split(stop)[0]

    cleaned = text.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0].strip()

    # Extract clean JSON object bounds
    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx != -1 and end_idx != -1:
        json_str = cleaned[start_idx:end_idx+1]
    else:
        json_str = cleaned

    # 1. Try standard json loads
    try:
        parsed = json.loads(json_str)
        return {
            "npc_response": str(parsed.get("npc_response", "...")).strip('\'" '),
            "player_options": parsed.get("player_options", [])
        }
    except Exception:
        logging.warning(f"⚠️ LLM output was not valid JSON, running regex fallback. Raw: {text[:250]}")

    # 2. Regex Fallback Extraction
    import re
    npc_response = "..."
    player_options = []

    # Extract npc_response value
    match_resp = re.search(r'"npc_response"\s*:\s*"((?:[^"\\]|\\.)*)"', json_str)
    if match_resp:
        npc_response = match_resp.group(1).replace('\\"', '"')
    else:
        match_resp_s = re.search(r"'npc_response'\s*:\s*'((?:[^'\\]|\\.)*)'", json_str)
        if match_resp_s:
            npc_response = match_resp_s.group(1).replace("\\'", "'")
        else:
            match_lax = re.search(r'npc_response["\']?\s*:\s*["\']?(.*?)["\']?(?:,|\n|\})', json_str, re.IGNORECASE)
            if match_lax:
                npc_response = match_lax.group(1).strip('\'", ')

    # Clean up any leakage in npc_response due to escape failures (e.g. Qwen escaping closing quotes)
    for leakage_marker in [', "player_options"', ', \'player_options\'', '", "player_options"', '", \'player_options\'']:
        if leakage_marker in npc_response:
            npc_response = npc_response.split(leakage_marker)[0].strip()

    # Extract player_options list content
    match_opts = re.search(r'"player_options"\s*:\s*\[(.*?)\]', json_str, re.DOTALL)
    if not match_opts:
        match_opts = re.search(r"'player_options'\s*:\s*\[(.*?)\]", json_str, re.DOTALL)

    if match_opts:
        opts_content = match_opts.group(1)
        options_found = re.findall(r'"((?:[^"\\]|\\.)*)"', opts_content)
        if not options_found:
            options_found = re.findall(r"'((?:[^'\\]|\\.)*)'", opts_content)
        if not options_found:
            options_found = [o.strip('\'" ') for o in opts_content.split(",") if o.strip()]
        player_options = [opt.strip() for opt in options_found if opt.strip()]

    # Trim leading/trailing quotes/spaces
    npc_response = npc_response.strip('\'" ')
    if not npc_response or len(npc_response) < 3:
        npc_response = "Hmm... I'm not sure what to say about that."

    return {
        "npc_response": npc_response,
        "player_options": player_options
    }


def clean_player_options(options: list[str], fallback_options: list[str]) -> list[str]:
    """Ensure we return exactly 4 unique dialogue options, with a goodbye option at the end."""
    import re
    cleaned = []
    seen = set()

    for opt in (options or []):
        opt_str = str(opt).strip('\'" ').strip()
        if opt_str:
            # Clean LLM option numbers if any leaked
            opt_str = re.sub(r'^\d+[\.\)\-\s]+', '', opt_str).strip()
            if opt_str and opt_str not in seen:
                cleaned.append(opt_str)
                seen.add(opt_str)

    # If too few valid options, use fallback
    if len(cleaned) < 2:
        cleaned = []
        seen = set()
        for opt in fallback_options:
            opt_str = str(opt).strip()
            if opt_str and opt_str not in seen:
                cleaned.append(opt_str)
                seen.add(opt_str)

    # Pad if we have fewer than 4
    if len(cleaned) < 4:
        for opt in fallback_options:
            opt_str = str(opt).strip()
            if opt_str and opt_str not in seen:
                cleaned.append(opt_str)
                seen.add(opt_str)
                if len(cleaned) == 4:
                    break

    # General fallback padding
    generic_fallbacks = ["Tell me more.", "What else?", "I see.", "Farewell."]
    if len(cleaned) < 4:
        for opt in generic_fallbacks:
            if opt not in seen:
                cleaned.append(opt)
                seen.add(opt)
                if len(cleaned) == 4:
                    break

    cleaned = cleaned[:4]

    # Ensure goodbye is the 4th option
    goodbye_words = ["farewell", "goodbye", "bye", "leave", "exit", "say goodbye", "depart", "head out"]
    has_goodbye = any(any(w in opt.lower() for w in goodbye_words) for opt in cleaned)

    if not has_goodbye:
        cleaned[3] = "Farewell."
    else:
        # Move goodbye option to index 3
        goodbye_idx = -1
        for idx, opt in enumerate(cleaned):
            if any(w in opt.lower() for w in goodbye_words):
                goodbye_idx = idx
                break
        if goodbye_idx != 3 and goodbye_idx != -1:
            cleaned[goodbye_idx], cleaned[3] = cleaned[3], cleaned[goodbye_idx]

    return cleaned





# ─── API: Player Registration & Class Changes ───────────────────────────

@app.post("/register_player")
def register_player(req: RegisterRequest):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT character_class, gold FROM Players WHERE player_name = ?", (req.player_name,))
            row = c.fetchone()
            if row:
                return {
                    "success": True,
                    "message": f"Player '{req.player_name}' logged in.",
                    "player_name": req.player_name,
                    "character_class": row[0],
                    "gold": row[1]
                }
            
            # Create player
            c.execute("""
                INSERT INTO Players (player_name, creation_timestamp, character_class, gold)
                VALUES (?, datetime('now'), ?, 100)
            """, (req.player_name, req.character_class.lower()))
            
            # Seed default relationships
            npcs = ["Captain Aldric", "Mira", "Elder Thorn", "Shade"]
            for npc in npcs:
                c.execute("""
                    INSERT OR IGNORE INTO Relationships (player_name, npc_name, trust, friendship, respect, suspicion)
                    VALUES (?, ?, 50, 50, 50, 0)
                """, (req.player_name, npc))
                
            conn.commit()
            
        return {
            "success": True,
            "message": f"Player '{req.player_name}' registered successfully as a {req.character_class}.",
            "player_name": req.player_name,
            "character_class": req.character_class,
            "gold": 100
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/update_character_class")
def update_character_class(req: UpdateClassRequest):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM Players WHERE player_name = ?", (req.player_name,))
            if not c.fetchone():
                raise HTTPException(status_code=404, detail=f"Player '{req.player_name}' not found.")
                
            c.execute("UPDATE Players SET character_class = ? WHERE player_name = ?", (req.character_class.lower(), req.player_name))
            conn.commit()
            
        return {
            "success": True,
            "message": f"Character class updated to {req.character_class}.",
            "player_name": req.player_name,
            "character_class": req.character_class
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def format_messages_for_gemini(messages_list):
    gemini_messages = []
    system_instruction = None
    for msg in messages_list:
        role = msg["role"]
        content = msg["content"]
        if role == "system":
            system_instruction = content
        elif role == "user":
            gemini_messages.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=content)]
                )
            )
        elif role == "assistant" or role == "model":
            gemini_messages.append(
                types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=content)]
                )
            )
    return gemini_messages, system_instruction


# ─── API: Generate NPC Response ───────────────────────────────────────

@app.post("/get_response")
def get_response(query: Query):
    try:
        with sqlite3.connect(DB_PATH) as connection:
            cursor = connection.cursor()

            # Check if player exists, if not, create them
            cursor.execute("SELECT character_class FROM Players WHERE player_name = ?", (query.player_name,))
            p_row = cursor.fetchone()
            if not p_row:
                cursor.execute("""
                INSERT INTO Players (player_name, creation_timestamp, character_class, gold) 
                VALUES (?, datetime('now'), 'warrior', 100)
                """, (query.player_name,))
                
                npcs = ["Captain Aldric", "Mira", "Elder Thorn", "Shade"]
                for npc in npcs:
                    cursor.execute("""
                        INSERT OR IGNORE INTO Relationships (player_name, npc_name, trust, friendship, respect, suspicion)
                        VALUES (?, ?, 50, 50, 50, 0)
                    """, (query.player_name, npc))
                connection.commit()
                char_class = "warrior"
            else:
                char_class = p_row[0]

            # Fetch NPC personality and metadata
            cursor.execute("""
            SELECT personality, allowed_actions, location, emotion_state, trust_level
            FROM NPCs
            WHERE npc_name = ?
            """, (query.npc_name,))
            result = cursor.fetchone()
            if not result:
                raise HTTPException(status_code=404, detail=f"NPC '{query.npc_name}' not found.")
            personality, allowed_actions, location, emotion_state, trust_level = result

            # Fetch conversation history
            cursor.execute("""
            SELECT player_name, player_input, npc_response, player_options
            FROM Conversations
            WHERE player_name = ? AND npc_name = ?
            ORDER BY timestamp ASC
            """, (query.player_name, query.npc_name))
            chat_history = cursor.fetchall()

        # Get world facts from vector store
        search_text = query.player_input or query.npc_name
        world_facts = vector_store.similarity_search(search_text, k=3)

        # Run Game Logic Layer BEFORE calling LLM
        logic_res = GameLogic.process_intent(
            query.player_name, query.npc_name, query.player_input or "", char_class
        )

        # Build messages for Chat Template
        system_instruction = f"""You are a conversational NPC in the medieval fantasy RPG "Kingdom Frontier".
Your task is to respond to the player IN CHARACTER and generate dialogue choices for them.

RULES:
1. Respond ONLY as the NPC — never speak as the player or make decisions on their behalf.
2. Keep responses concise (1-3 sentences), matching RPG dialogue style.
3. React dynamically to the player's character class (Warrior, Mage, Rogue, Cleric). For example, comment on their spells if they are a Mage, or their armor/strength if they are a Warrior.
4. Do NOT decide if an action succeeded or failed. Do NOT invent outcomes, item transfers, gold transactions, or quest completions. All game state decisions have already been made by the Game Logic Layer. For gameplay actions (buy, sell, quests), you must only describe the outcome listed in [GAME STATE]. For general greetings, conversations, or farewells, you have full creative freedom to chat in-character, share lore, and react to the player's class.
5. Generate exactly 4 player dialogue options that are contextually relevant. The 4th option should always be a farewell/goodbye option.
6. Keep the conversation coherent and story-driven. Treat this as the next beat of an ongoing scene—connect the current reply to prior NPC lines, player choices, and the player's current tone.
7. If the player returns to the same NPC, acknowledge their return and mention the last shared scene or prior agreement naturally in-character.
8. Reflect the player's sentiment in your response: positive tone when the player is polite or encouraging, guarded tone when the player is frustrated, and steady tone when the player is neutral.
9. Avoid repeating phrases from previous turns or greetings. Express the NPC's mood, identity, and the game state in a fresh, natural way each time.
10. NEVER reference numerical stats, trust changes, gold values, or database terms in your dialogue. Keep all conversation entirely in-character and immersive. For example, instead of saying 'Your trust increased', say 'I appreciate your business' or 'I feel I can trust you more now'.

OUTPUT FORMAT — You MUST output valid JSON matching this exact schema:
{{
    "npc_response": "What the NPC says to the player describing the outcome and current state in character",
    "player_options": ["Option 1", "Option 2", "Option 3", "Goodbye option"]
}}

NPC IDENTITY:
Name: {query.npc_name}
Personality: {personality}
Location: {location or "Unknown"}
Current emotion: {emotion_state}
Trust level: {trust_level}/100

WORLD FACTS:
{"\n".join([doc.page_content for doc in world_facts])}
"""

        messages = [{"role": "system", "content": system_instruction}]

        # Always add a few-shot training example to guide the model's JSON structure and tone
        messages.append({
            "role": "user",
            "content": "PLAYER INFO:\nName: Adventurer\nClass: warrior\n\n[GAME STATE]\nInventory: Empty\nGold: 100\nRelationship — Trust: 50, Friendship: 50, Respect: 50, Suspicion: 0\nDetected intent: greeting\n\nPlayer says: Hello there."
        })
        messages.append({
            "role": "assistant",
            "content": json.dumps({
                "npc_response": "Greetings, traveler. I guard these gates. State your business.",
                "player_options": ["I want to enter.", "What is this place?", "Who are you?", "Farewell."]
            })
        })

        # Add a gameplay action few-shot example to show how to translate stats updates and outcomes into immersive dialogue
        messages.append({
            "role": "user",
            "content": "PLAYER INFO:\nName: Adventurer\nClass: warrior\n\n[GAME STATE]\nGold: 100\nInventory: Empty\nRelationship — Trust: 50, Friendship: 50, Respect: 50, Suspicion: 0\nDetected intent: buy_item\nAction result: purchase_complete\nDetail: Player bought Steel Sword for 15 gold. Remaining gold: 85.\n\nPlayer says: I want to buy the Steel Sword."
        })
        messages.append({
            "role": "assistant",
            "content": json.dumps({
                "npc_response": "A fine choice, warrior. This steel blade is sturdy and will keep you safe in battle. Here is your weapon.",
                "player_options": ["Thank you.", "What else do you have for sale?", "Do you need any help?", "Farewell."]
            })
        })

        # Add actual chat history (up to the last 4 turns)
        for _, inp, resp, opts_json in chat_history[-4:]:
            if not inp:
                continue
            try:
                opts = json.loads(opts_json) if opts_json else []
            except Exception:
                opts = []
            if not opts or len(opts) < 2:
                opts = ["Tell me more.", "What else?", "I see.", "Farewell."]
            messages.append({
                "role": "user",
                "content": f"PLAYER INFO:\nName: {query.player_name}\nClass: {char_class}\n\nPlayer says: {inp}"
            })
            messages.append({
                "role": "assistant",
                "content": json.dumps({
                    "npc_response": resp,
                    "player_options": opts[:4]
                })
            })

        sentiment = EmotionTracker._classify_sentiment(query.player_input or "")
        selected_choice = (str(query.selected_option_index)
            if query.selected_option_index is not None and query.selected_option_index >= 0
            else "free text")

        # Add current turn
        current_user_content = f"""PLAYER INFO:
Name: {query.player_name}
Class: {char_class}
Sentiment: {sentiment}
Selected option: {selected_choice}

{logic_res["game_context"]}

Player says: {query.player_input or "(Approaches the NPC)"}"""

        messages.append({"role": "user", "content": current_user_content})

        # Generate output using Gemini API
        gemini_messages, system_instruction = format_messages_for_gemini(messages)
        
        try:
            response = gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=gemini_messages,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=GeminiResponseSchema,
                    temperature=0.85,
                ),
            )
            model_output = response.text
            print(f"\n[DEBUG - GEMINI RAW OUTPUT]:\n{model_output}\n")
            parsed = json.loads(model_output)
        except Exception as e:
            logging.error(f"Gemini API generation failed: {e}. Attempting fallback...")
            try:
                response = gemini_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=gemini_messages,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.85,
                    ),
                )
                model_output = response.text
                print(f"\n[DEBUG - GEMINI FALLBACK RAW OUTPUT]:\n{model_output}\n")
                parsed = parse_llm_response(model_output)
            except Exception as fallback_e:
                logging.error(f"Gemini API fallback also failed: {fallback_e}")
                parsed = {
                    "npc_response": "I'm having trouble thinking straight right now. (Failed to contact the guide realm)",
                    "player_options": ["Let's try again.", "What happened?", "Understood.", "Farewell."]
                }

        # Update NPC emotion
        choice_idx = query.selected_option_index if query.selected_option_index is not None else -1
        emotion_result = EmotionTracker.update_emotion(
            query.npc_name, query.player_input or "", choice_idx
        )

        # Build final response. Clean and pad choices dynamically.
        player_options = clean_player_options(parsed.get("player_options", []), logic_res["player_options"])

        response = RPGResponse(
            npc_response=parsed["npc_response"],
            player_options=player_options,
            sentiment=sentiment,
            inventory_changes=logic_res["inventory_changes"],
            quest_updates=logic_res["quest_updates"],
            relationship_updates=logic_res["relationship_updates"],
            memory_updates=logic_res["memory_updates"]
        )

        # Store conversation in database
        with sqlite3.connect(DB_PATH) as connection:
            cursor = connection.cursor()
            cursor.execute("""
            INSERT INTO Conversations 
                (player_name, npc_name, held_items, player_input, npc_response, 
                 npc_action, timestamp, player_choice_index, emotion_after, trust_after, player_options)
            VALUES (?, ?, '', ?, ?, ?, datetime('now'), ?, ?, ?, ?)
            """, (
                query.player_name, query.npc_name,
                query.player_input or "", response.npc_response,
                logic_res["action_result"].get("reason", "none") if logic_res.get("action_result") else "none",
                choice_idx,
                emotion_result["emotion_state"], emotion_result["trust_level"],
                json.dumps(response.player_options)
            ))
            connection.commit()

        return response

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("❌ CRITICAL EXCEPTION IN GET_RESPONSE:")
        raise HTTPException(status_code=500, detail=f"Error generating response: {str(e)}")


# ─── API: Latest Response ─────────────────────────────────────────────

@app.post("/get_latest_response")
def get_latest_response(query: Query):
    try:
        with sqlite3.connect(DB_PATH) as connection:
            cursor = connection.cursor()
            cursor.execute("""
            SELECT npc_response
            FROM Conversations
            WHERE (player_name = ? OR player_name = 'All') AND npc_name = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """, (query.player_name, query.npc_name))
            result = cursor.fetchone()

        if result:
            return {"npc_name": query.npc_name, "action": "", "response": result[0]}
        else:
            raise HTTPException(
                status_code=404,
                detail=f"No conversations found for player '{query.player_name}' and NPC '{query.npc_name}'."
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── API: Name Check ──────────────────────────────────────────────────

@app.post("/check_name_availability")
def check_name_availability(query: NameCheckQuery):
    try:
        with sqlite3.connect(DB_PATH) as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT 1 FROM Players WHERE player_name = ?", (query.player_name,))
            result = cursor.fetchone()

            if not result:
                cursor.execute("""
                INSERT INTO Players (player_name, creation_timestamp, character_class, gold) 
                VALUES (?, datetime('now'), 'warrior', 100)
                """, (query.player_name,))
                
                npcs = ["Captain Aldric", "Mira", "Elder Thorn", "Shade"]
                for npc in npcs:
                    cursor.execute("""
                        INSERT OR IGNORE INTO Relationships (player_name, npc_name, trust, friendship, respect, suspicion)
                        VALUES (?, ?, 50, 50, 50, 0)
                    """, (query.player_name, npc))
                connection.commit()

        return NameCheckResponse(available=(result is None))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── API: Data Retrieval ──────────────────────────────────────────────

@app.get("/conversations")
def get_conversations():
    """Retrieve all stored conversations."""
    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM Conversations ORDER BY timestamp DESC")
        rows = cursor.fetchall()

    return {"conversations": [
        {
            "id": row[0], "player_name": row[1], "npc_name": row[2],
            "held_items": row[3], "player_input": row[4], "npc_response": row[5],
            "npc_action": row[6], "timestamp": row[7],
            "player_choice_index": row[8] if len(row) > 8 else -1,
            "emotion_after": row[9] if len(row) > 9 else "neutral",
            "trust_after": row[10] if len(row) > 10 else 50,
            "player_options": json.loads(row[11]) if len(row) > 11 and row[11] else []
        }
        for row in rows
    ]}


@app.get("/players")
def get_players():
    """Retrieve all registered players."""
    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM Players")
        rows = cursor.fetchall()

    return {"players": [
        {"player_name": row[0], "creation_timestamp": row[1], "character_class": row[2], "gold": row[3]}
        for row in rows
    ]}


@app.get("/npcs")
def get_npcs():
    """Retrieve all NPCs with full metadata."""
    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT npc_name, personality, allowed_actions, location, emotion_state, trust_level FROM NPCs")
        rows = cursor.fetchall()

    return {"npcs": [
        {
            "npc_name": row[0],
            "personality": row[1],
            "allowed_actions": row[2],
            "location": row[3],
            "emotion_state": row[4],
            "trust_level": row[5]
        }
        for row in rows
    ]}


@app.get("/npc_info/{npc_name}")
def get_npc_info(npc_name: str):
    """Get detailed NPC info including emotion and trust."""
    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.cursor()
        cursor.execute("""
        SELECT npc_name, personality, allowed_actions, location, emotion_state, trust_level
        FROM NPCs WHERE npc_name = ?
        """, (npc_name,))
        row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"NPC '{npc_name}' not found.")

    return {
        "npc_name": row[0], "personality": row[1], "allowed_actions": row[2],
        "location": row[3], "emotion_state": row[4], "trust_level": row[5]
    }


@app.get("/quest_state/{player_name}")
def get_quest_state(player_name: str):
    """Get all quest states for a player."""
    quests = QuestEngine.get_all_quests(player_name)
    return {"player_name": player_name, "quests": quests}


@app.get("/player_inventory/{player_name}")
def get_player_inventory_api(player_name: str):
    """Get dynamic player inventory details."""
    try:
        inv = GameLogic.get_player_inventory(player_name)
        return inv
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── API: Dashboard ───────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    index_file = os.path.join("api", "index.html")
    if not os.path.exists(index_file):
        index_file = "index.html"

    try:
        with open(index_file, "r", encoding="utf-8") as file:
            return HTMLResponse(content=file.read(), status_code=200)
    except Exception as e:
        return HTMLResponse(content=f"<h3>Error loading page: {str(e)}</h3>", status_code=500)


# ─── Error Handler ────────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print("\n[ERROR] 422 VALIDATION ERROR DETECTED!")
    raw_body = await request.body()
    decoded_body = raw_body.decode("utf-8", errors="ignore")
    print(f"The frontend sent: {decoded_body}")

    safe_errors = []
    for err in exc.errors():
        err_dict = dict(err)
        if "input" in err_dict and isinstance(err_dict["input"], bytes):
            err_dict["input"] = err_dict["input"].decode("utf-8", errors="ignore")
        safe_errors.append(err_dict)

    print(f"The backend is complaining about: {safe_errors}\n")
    return JSONResponse(status_code=422, content={"detail": safe_errors})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=False)