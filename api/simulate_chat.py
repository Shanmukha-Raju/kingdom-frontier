import sys
import os
sys.path.append(os.path.abspath("api"))

import json
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
from build_vector_store import load_or_build_vector_store
from game_logic import GameLogic
from main import clean_player_options  # Import the new option cleaning logic

print("Loading model and tokenizer...")
model_id = "Qwen/Qwen2.5-0.5B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    torch_dtype="auto",
    device_map="auto"
)

# Use the same parameters as updated in api/main.py
hf_pipeline = pipeline(
    "text-generation",
    model=model,
    tokenizer=tokenizer,
    max_new_tokens=200,
    temperature=0.85,
    top_p=0.9,
    repetition_penalty=1.05,
    do_sample=True,
    return_full_text=False,
    clean_up_tokenization_spaces=False
)

vector_store = load_or_build_vector_store(None)

def test_chat(player_name, npc_name, player_inputs):
    print(f"\n==================================================")
    print(f"SIMULATING CHAT: Player '{player_name}' with NPC '{npc_name}'")
    print(f"==================================================")
    
    # Clean history for this test player
    import sqlite3
    from create_db import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM Conversations WHERE player_name = ?", (player_name,))
        conn.commit()

    for step, player_input in enumerate(player_inputs):
        print(f"\n--- Turn {step+1}: Player says '{player_input}' ---")
        
        # Load player class
        char_class = "warrior"
        
        # Build context
        logic_res = GameLogic.process_intent(player_name, npc_name, player_input, char_class)
        
        # Build vector search
        search_text = player_input or npc_name
        world_facts = vector_store.similarity_search(search_text, k=3)
        
        # Get personality
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT personality, location, emotion_state, trust_level FROM NPCs WHERE npc_name = ?", (npc_name,))
            personality, location, emotion_state, trust_level = c.fetchone()
            
            # Fetch history (including player_options column)
            c.execute("SELECT player_name, player_input, npc_response, player_options FROM Conversations WHERE player_name = ? AND npc_name = ? ORDER BY timestamp ASC", (player_name, npc_name))
            chat_history = c.fetchall()

        system_instruction = f"""You are a conversational NPC in the medieval fantasy RPG "Kingdom Frontier".
Your task is to respond to the player IN CHARACTER and generate dialogue choices for them.

RULES:
1. Respond ONLY as the NPC — never speak as the player or make decisions on their behalf.
2. Keep responses concise (1-3 sentences), matching RPG dialogue style.
3. React dynamically to the player's character class (Warrior, Mage, Rogue, Cleric). For example, comment on their spells if they are a Mage, or their armor/strength if they are a Warrior.
4. Do NOT decide if an action succeeded or failed. Do NOT invent outcomes, item transfers, gold transactions, or quest completions. All game state decisions have already been made by the Game Logic Layer. For gameplay actions (buy, sell, quests), you must only describe the outcome listed in [GAME STATE]. For general greetings, conversations, or farewells, you have full creative freedom to chat in-character, share lore, and react to the player's class.
5. Generate exactly 4 player dialogue options that are contextually relevant. The 4th option should always be a farewell/goodbye option.
6. Avoid repeating phrases from previous turns or greetings. Express the NPC's mood, identity, and the game state in a fresh, natural way each time.
7. NEVER reference numerical stats, trust changes, gold values, or database terms in your dialogue. Keep all conversation entirely in-character and immersive. For example, instead of saying 'Your trust increased', say 'I appreciate your business' or 'I feel I can trust you more now'.

OUTPUT FORMAT — You MUST output valid JSON matching this exact schema:
{{
    "npc_response": "What the NPC says to the player describing the outcome and current state in character",
    "player_options": ["Option 1", "Option 2", "Option 3", "Goodbye option"]
}}

NPC IDENTITY:
Name: {npc_name}
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

        # Chat history with dynamic choices
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
                "content": f"PLAYER INFO:\nName: {player_name}\nClass: {char_class}\n\nPlayer says: {inp}"
            })
            messages.append({
                "role": "assistant",
                "content": json.dumps({
                    "npc_response": resp,
                    "player_options": opts[:4]
                })
            })

        current_user_content = f"""PLAYER INFO:
Name: {player_name}
Class: {char_class}

{logic_res["game_context"]}

Player says: {player_input}"""

        messages.append({"role": "user", "content": current_user_content})

        prompt_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        
        # Print prompt (only for first turn to keep output clean, unless requested)
        if step == 0:
            print("\nPROMPT SENT TO MODEL (TURN 1):")
            print(prompt_text)
            print("-" * 40)
            
        model_output = hf_pipeline(prompt_text)[0]["generated_text"]
        print(f"RAW MODEL OUTPUT:\n{model_output}")
        
        # Parse
        try:
            import re
            cleaned = model_output.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            parsed = json.loads(cleaned[start:end+1])
            npc_resp = parsed["npc_response"]
            raw_options = parsed["player_options"]
        except Exception as e:
            print(f"Parsing failed: {e}")
            npc_resp = "PARSING_FAILED_FALLBACK"
            raw_options = []

        # Clean options
        options = clean_player_options(raw_options, logic_res["player_options"])

        print(f"PARSED NPC RESPONSE: {npc_resp}")
        print(f"CLEANED OPTIONS: {options}")

        # Store in DB
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
            INSERT INTO Conversations 
                (player_name, npc_name, held_items, player_input, npc_response, 
                 npc_action, timestamp, player_choice_index, emotion_after, trust_after, player_options)
            VALUES (?, ?, '', ?, ?, ?, datetime('now'), -1, 'neutral', 50, ?)
            """, (player_name, npc_name, player_input, npc_resp, "none", json.dumps(options)))
            conn.commit()

test_chat("tester_mira", "Mira", ["What weapons do you have for sale?", "I want to buy the Steel Sword", "I'd like to sell something.", "Farewell."])
