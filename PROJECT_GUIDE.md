# Kingdom Frontier — Complete Project Guide & Architecture Spec

Welcome to the comprehensive guide for **Kingdom Frontier**, a hybrid deterministic/generative RPG dialogue and game logic engine. This document details the entire project structure, describes the roles and contents of all files, diagrams the architecture, and details the implementation plans executed to solve key conversational and functional challenges.

---

## 📁 Project Directory Tree

The workspace is organized into a backend FastAPI microservice (housing the LLM, vector store, and SQLite game databases) and a frontend client (including a web dashboard test interface and Godot Engine game client scripts).

```
generative-npc-dialogue/
│
├── api/                                # Backend Server & Game Systems
│   ├── data/
│   │   └── game_data.db                # SQLite game database (stores player & NPC state)
│   │
│   ├── main.py                         # FastAPI web server, LLM pipeline & API endpoints
│   ├── game_logic.py                   # Intent detection & deterministic RPG verification rules
│   ├── quest_engine.py                 # Quest state trackers, sentiment analysis & relationships
│   ├── create_db.py                    # SQLite tables initialization schema and seed data
│   ├── build_vector_store.py           # FAISS vector store compiler & search logic
│   │
│   ├── index.html                      # HTML5/CSS3 client testing dashboard
│   ├── world_facts.txt                 # Raw text database of lore, geography & legends
│   │
│   ├── test_db.py                      # SQLite database inspector script
│   ├── test_api.py                     # API connectivity test utility
│   └── simulate_chat.py                # Console-based multi-turn chat simulator script
│
├── data/
│   └── vector_store/                   # Compiled FAISS index files for lore search
│
├── game/                               # Godot Game Client assets
│   ├── Scenes/
│   │   └── UI/
│   │       ├── HUD.tscn                # Heads-up display UI scene
│   │       ├── dialogue_box.tscn       # Dialogue overlay UI scene
│   │       ├── dialogue_box.gd         # Dialogue typography, options rendering and focus script
│   │       └── hud.gd                  # HUD updates event listener
│   │
│   └── Scripts/
│       ├── DialogueManager.gd          # Godot dialogue client singleton (handles HTTP requests)
│       └── PersistanceManager.gd       # Local player state manager (gold, inventory, name)
│
├── venv/                               # Python Virtual Environment
├── .gitignore                          # Git file exclusion rules
├── README.md                           # Quick-start manual
└── PROJECT_GUIDE.md                    # Complete structural & architectural guide (this file)
```

---

## 📄 Complete File-by-File Explanation

### 🖥️ Backend API & Systems (`api/`)

#### 1. [main.py](file:///c:/Users/wwwSC/OneDrive/Desktop/generative-npc-dialogue/api/main.py)
* **Role**: The main entry point of the backend FastAPI service.
* **LLM Setup**: Initializes the Hugging Face text generation pipeline using the local `Qwen/Qwen2.5-0.5B-Instruct` model, loaded in auto precision on the available GPU/CPU devices. Generation parameters are tuned for maximum flow and repetition recovery (`temperature=0.85`, `top_p=0.9`, `repetition_penalty=1.05`).
* **Endpoints**:
  * `POST /get_response`: Processes player input. First calls `game_logic.py` to deterministically validate inventory, gold, or quest changes. Then searches the FAISS index for relevant lore. Next, it assembles a system prompt featuring strict rules, details about the NPC, lore facts, and a few-shot interaction. Crucially, it appends the actual conversational history (including options presented). Finally, it queries Qwen, runs the output through a fallback JSON regex parser and a post-generation choices cleaner, saves the turn to SQLite, and returns the response.
  * `POST /get_latest_response`: Returns the most recent line spoken by an NPC to allow clean dialogue resume operations.
  * `POST /register_player`: Inserts new player records and initializes relationship metrics.
  * `POST /update_character_class`: Updates the player's class (`warrior`, `mage`, `rogue`, or `cleric`), preventing validation errors.
  * `GET /conversations`, `/players`, `/npcs`, `/npc_info/{npc_name}`, `/quest_state/{player_name}`, `/player_inventory/{player_name}`: Database queries that feed status details to the dashboard.
  * `GET /`: Serves the glassmorphic client dashboard `index.html`.
* **JSON Parser Fallback**: Extracts JSON from the model's raw string output and falls back to string regex parsing to fetch the `npc_response` and `player_options` if Qwen output is cut off or malformed.
* **Options Cleaner**: Ensures exactly 4 unique choices are returned to the client, with a farewell option always locked in the 4th position (index 3).

#### 2. [game_logic.py](file:///c:/Users/wwwSC/OneDrive/Desktop/generative-npc-dialogue/api/game_logic.py)
* **Role**: The **Deterministic RPG Layer** of the game. It ensures that the LLM *describes* game states but *never decides* them.
* **Intent Detection**: Analyzes player input for keywords matching actions: `buy_item`, `sell_item`, `accept_quest`, `complete_quest`, `ask_quest`, `ask_inventory`, `ask_location`, `ask_about_npc`, `greeting`, and `goodbye` using priority ordering.
* **Game Verification Logic**:
  * `validate_purchase()`: Checks if the NPC shop has the item in stock and if the player has enough gold. If yes, it deducts gold, increments player inventory, decrements shop stock, updates quests (e.g. buying the *Frostbane Katana* advances the quest line), and updates relationships.
  * `validate_sale()`: Verifies the player owns the item, increases player gold, removes the item from inventory, and updates relationships.
  * `validate_accept_quest()`: Checks prerequisites and starts quest states in SQLite.
  * `validate_complete_quest()`: Checks if quest requirements are met (e.g. checks inventory for the *Frostbane Katana* for Captain Aldric, or trust metrics for Elder Thorn). If met, it gives rewards (gold, items) and writes database records.
* **Context Builder**: Formats the dynamic `[GAME STATE]` context block injected into the LLM prompt. This block lists the current inventory, gold, quest status, relationship scores, and NPC memories of the player.

#### 3. [quest_engine.py](file:///c:/Users/wwwSC/OneDrive/Desktop/generative-npc-dialogue/api/quest_engine.py)
* **Role**: Handles quest database interactions and maps player inputs to relationship and emotion adjustments.
* **Quest State Machine**: Manages the `QuestState` table schema. Handles query operations and maps internal quest IDs to readable text names (e.g. `main_frostbane` -> *Find the Frostbane Katana*).
* **Emotion Tracker**: Classifies player input sentiment (`positive`, `neutral`, `negative`) using keyword matching. Combines this with the player's selected dialogue choice option index to compute trust adjustments (`trust_delta`), then resolves the NPC's emotional state:
  * `trust >= 80` ➔ `grateful`
  * `trust >= 60` ➔ `friendly`
  * `trust >= 40` ➔ `neutral`
  * `trust >= 20` ➔ `distrustful`
  * `trust < 20` ➔ `hostile`

#### 4. [create_db.py](file:///c:/Users/wwwSC/OneDrive/Desktop/generative-npc-dialogue/api/create_db.py)
* **Role**: SQLite schema builder and seed manager.
* **Schema Definition**: Compiles database tables:
  * `Players`: Stores gold, class, creation timestamp.
  * `NPCs`: Stores name, personality lore, allowed actions, location, and emotional metrics.
  * `Conversations`: Stores chat history (with `player_options` JSON strings).
  * `QuestState`: Keeps status, step indices, and progress flags.
  * `Items`: Lore descriptions, prices, and categories.
  * `Inventory`: Maps items to players with quantities.
  * `ShopItems`: Shop inventories, sell prices, and buyback ratios.
  * `Relationships`: Connects players to NPCs with trust, friendship, respect, and suspicion metrics.
  * `Memories`: Natural language records of key transactions and greetings.
* **Seed Data**: Populates NPCs (Captain Aldric, Mira, Elder Thorn, Shade), items (Frostbane Katana, Steel Sword, Health Potion, Iron Shield, etc.), and pre-seeded initial options for starting greetings.

#### 5. [build_vector_store.py](file:///c:/Users/wwwSC/OneDrive/Desktop/generative-npc-dialogue/api/build_vector_store.py)
* **Role**: Compiles and searches the world lore vector database.
* **Embeddings**: Uses `langchain-huggingface` to load the local `all-MiniLM-L6-v2` transformer.
* **Lore Extraction**: Parses `world_facts.txt` into chunks and writes a FAISS vector database to `data/vector_store/`. When queried in `main.py`, it retrieves the top 3 most relevant sentences matching the player's prompt to insert into the LLM system prompt.

#### 6. [world_facts.txt](file:///c:/Users/wwwSC/OneDrive/Desktop/generative-npc-dialogue/api/world_facts.txt)
* **Role**: Textual repository of facts, history, geography, and legends of Kingdom Frontier. Includes descriptions of Ironhaven Town, the inner keep security rules, Frostbane Katana history, forest wardens, and the Shadow Guild faction.

#### 7. [index.html](file:///c:/Users/wwwSC/OneDrive/Desktop/generative-npc-dialogue/api/index.html)
* **Role**: A glassmorphic web dashboard for testing. Features character creation, live inventory lists, quest cards, relationship graphs, live chat bubbles, raw model prompt logs, and settings overlays.

#### 8. [test_db.py](file:///c:/Users/wwwSC/OneDrive/Desktop/generative-npc-dialogue/api/test_db.py), [test_api.py](file:///c:/Users/wwwSC/OneDrive/Desktop/generative-npc-dialogue/api/test_api.py), [simulate_chat.py](file:///c:/Users/wwwSC/OneDrive/Desktop/generative-npc-dialogue/api/simulate_chat.py)
* **Role**: Verification scripts. `simulate_chat.py` simulates multi-turn conversations through the CLI. `test_db.py` inspects tables, and `test_api.py` verifies endpoint responsiveness.

---

### 🎮 Godot Game Client Scripts (`game/Scripts/`)

#### 1. [DialogueManager.gd](file:///c:/Users/wwwSC/OneDrive/Desktop/generative-npc-dialogue/game/Scripts/DialogueManager.gd)
* **Role**: The Godot Autoload (singleton) orchestrating dialogue requests and parsing responses.
* **State Management**: Spawns dialogue box UI scenes, links player selection inputs back to the API, and applies inventory changes (e.g. updating gold or adding items) received in response payloads to the local client state.
* **Action Handlers**: Maps actions such as `open_door` to internal Godot event triggers (like signaling gates to open).

#### 2. [PersistanceManager.gd](file:///c:/Users/wwwSC/OneDrive/Desktop/generative-npc-dialogue/game/Scripts/PersistanceManager.gd)
* **Role**: Stores client-side player states (name, gold, inventory items, and quest flags) and emits signals to update the HUD whenever values change.

---

## 🏛️ System Architecture & Control Flow

The engine uses a **hybrid design** to combine deterministic gameplay rules with dynamic, open-ended conversational generations:

```
                                  +-------------------+
                                  |    Player Input   |
                                  +---------+---------+
                                            |
                                            v
                                  +---------+---------+
                                  |    FastAPI API    |
                                  |   (api/main.py)   |
                                  +---------+---------+
                                            |
                                            v
                                  +---------+---------+
                                  |   game_logic.py   |
                                  | - Intent Matcher  |
                                  | - DB Verification |
                                  +----+---------+----+
                                       |         |
                  +--------------------+         +--------------------+
                  |                                                   |
                  v                                                   v
        +---------+---------+                               +---------+---------+
        |   Vector Store    |                               |    Conversations  |
        |  (Lore Retrieval) |                               | (SQLite History)  |
        +---------+---------+                               +---------+---------+
                  |                                                   |
                  +--------------------+         +--------------------+
                                       |         |
                                       v         v
                                  +----+---------+----+
                                  |   Chat Template   |
                                  |  Prompt Builder   |
                                  +---------+---------+
                                            |
                                            v
                                  +---------+---------+
                                  |     Local LLM     |
                                  |  (Qwen2.5-0.5B)   |
                                  +---------+---------+
                                            |
                                            v
                                  +---------+---------+
                                  |   Output Cleaner  |
                                  |  - JSON Parser    |
                                  |  - Choices Trim   |
                                  +---------+---------+
                                            |
                                            v
                                  +---------+---------+
                                  |   Response JSON   |
                                  |   (Unity/Godot)   |
                                  +-------------------+
```

---

## 🛠️ Executed Implementation Plans

To resolve critical issues with conversational flow and state management, the following adjustments were implemented:

### 1. Resolving the Conversation Loop & Generic Options Loop
* **Issue**: The LLM prompt builder previously hardcoded the options of history turns in the tokenizer template to a static list (`["Tell me more.", "What else?", "I see.", "Farewell."]`). The model learned to imitate this pattern, resulting in repetitive greetings and generic choices.
* **Solution**:
  1. **Schema Migration**: Added the `player_options TEXT` (JSON string) column to the `Conversations` database table in `api/create_db.py`.
  2. **Initial Seed**: Seeded the greetings in SQLite with their corresponding initial dialogue choices.
  3. **History Extraction**: Refactored the prompt building loop in `api/main.py` to retrieve the actual options presented to the user at each turn and feed them back to the LLM assistant message templates.
  4. **Frontend Session Restoration**: Updated `loadConversationForNPC` in `api/index.html` to parse the options of the last conversation turn, allowing users to switch NPCs or refresh the page without getting locked out of dialogue choices.

### 2. Safeguarding Immersion (Rule 10 / Rule 7)
* **Issue**: Due to its small parameter count, the 0.5B model would sometimes output raw database stats or trust change comments (e.g. *"I trust you 5 points more now"*) when seeing game state variables.
* **Solution**:
  1. Integrated **Rule 10** into the prompt: *"NEVER reference numerical stats, trust changes, gold values, or database terms in your dialogue. Keep all conversation entirely in-character and immersive. For example, instead of saying 'Your trust increased', say 'I appreciate your business'."*
  2. Added a second, detailed transaction few-shot example to the prompt list. This shows the model how to translate gold transactions and item additions into natural character dialogue.

### 3. Settings Class Selector Collision
* **Issue**: The click listener on `.class-card` in the HTML client matched both the registration overlay and the settings modal overlay cards. Because settings modal cards lacked the `data-class` attribute, opening settings set the class to `null`, causing Pydantic validation errors during submissions.
* **Solution**: Scoped the event listener in `api/index.html` strictly to the registration overlay:
  `document.querySelectorAll('#registration-overlay .class-card')`

---

## 🔌 Game Client Integration Specifications

### 📤 API Request Schema
To retrieve a dialogue response, make a `POST` request to `/get_response` with the following JSON payload:

```json
{
  "player_name": "Adventurer",
  "npc_name": "Mira",
  "held_items": "100 Gold, Steel Sword",
  "player_input": "I'd like to buy the Frostbane Katana.",
  "selected_option_index": 1
}
```

### 📥 API Response Schema (State Delta Format)
The backend responds with a JSON object that describes the dialogue response and lists all state changes for client-side synchronization:

```json
{
  "npc_response": "A fine choice, warrior. This legendary blade has protected our frontier for generations. Take it, and let it guide your path.",
  "player_options": [
    "Thank you, Mira.",
    "What else do you sell?",
    "Do you know anything about the keep?",
    "Farewell."
  ],
  "sentiment": "positive",
  "inventory_changes": {
    "gold": -50,
    "items_added": ["Frostbane Katana"],
    "items_removed": []
  },
  "quest_updates": {
    "quest_id": "main_frostbane",
    "status": "completed",
    "step": 2
  },
  "relationship_updates": {
    "trust": 5,
    "friendship": 3
  },
  "memory_updates": [
    "Bought Frostbane Katana for 50 gold"
  ]
}
```

### 🤖 Godot client parsing code example (from `DialogueManager.gd`)
```gdscript
func _on_request_completed(_result, response_code, _headers, body):
	if response_code != 200:
		return
		
	var json = JSON.new()
	json.parse(body.get_string_from_utf8())
	var response = json.get_data()
	
	var message = response.get("npc_response", "")
	player_options = response.get("player_options", [])
	var inventory_changes = response.get("inventory_changes", {})
	
	dialogue_lines.push_back(message)
	_apply_inventory_changes(inventory_changes)
	request_finished.emit()
```
