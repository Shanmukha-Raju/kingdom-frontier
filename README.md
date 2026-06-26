# Kingdom Frontier — Dynamic AI NPC Dialogue Engine

This repository contains the backend and frontend engine for **Kingdom Frontier**, a medieval fantasy RPG featuring dynamic, context-aware AI conversations, quest tracking, shop transactions, and relationship progression.

The dialogue engine runs using **FastAPI** and the cloud-hosted **Gemini API (gemini-2.5-flash)** causal language model, supported by a local FAISS vector search database and a deterministic Python/SQLite game logic layer.

---

## 📁 Project Directory Structure

```
generative-npc-dialogue/
│
├── api/                             # Backend Server & Game Systems
│   ├── data/
│   │   └── game_data.db             # SQLite game database (Dynamic state)
│   │
│   ├── main.py                      # FastAPI server & LLM generation endpoint
│   ├── game_logic.py                # Intent detection & deterministic RPG layer
│   ├── quest_engine.py              # Quest state tracker & relationship managers
│   ├── create_db.py                 # SQLite tables initialization and seeding
│   ├── build_vector_store.py        # FAISS vector store compiler & search logic
│   │
│   ├── index.html                   # HTML5/CSS3 client dashboard (Dashboard interface)
│   ├── world_facts.txt              # Static lore database for vector store searches
│   │
│   ├── test_db.py                   # SQLite tables inspector script
│   ├── test_api.py                  # API connectivity verification script
│   └── simulate_chat.py             # Multi-turn chat simulator script
│
├── data/
│   └── vector_store/                # FAISS vector store index files
│
├── game/                            # Godot Game Client assets
│   ├── Assets/                      # Knight, tileset, and sprite assets
│   ├── Scenes/                      # Godot scenes
│   └── Scripts/                     # DialogueManager.gd, PersistanceManager.gd, etc.
│
├── venv/                            # Local Python Virtual Environment
├── .gitignore
├── README.md                        # Project Guide (This file)
└── LICENSE
```

---

## ⚙️ Core Architecture & Control Flow

The architecture operates on a **hybrid pipeline**: game rules and values are resolved **deterministically in Python/SQLite**, while dialog is generated **generatively in the LLM**. This keeps transactions 100% accurate while allowing dialogs to remain dynamic.

```
                  ┌──────────────────┐
                  │   Player Input   │
                  └────────┬─────────┘
                           │
             ┌─────────────▼─────────────┐
             │       FastAPI API         │
             └─────────────┬─────────────┘
                           │
             ┌─────────────▼─────────────┐
             │   GameLogic.py            │
             │   - Intent Detection      │
             │   - SQLite state update   │
             └─────────────┬─────────────┘
                           │
       ┌───────────────────┴───────────────────┐
       ▼                                       ▼
┌──────────────┐                        ┌──────────────┐
│ Vector Store │                        │   History    │
│ (World Facts)│                        │ (Conversations)
└──────┬───────┘                        └──────┬───────┘
       │                                       │
       └───────────────────┬───────────────────┘
                           │
             ┌─────────────▼─────────────┐
             │   Chat Template Builder   │
             │   - [GAME STATE] outcome  │
             │   - Custom System Rules   │
             └─────────────┬─────────────┘
                           │
             ┌─────────────▼─────────────┐
             │      Gemini API           │
             │   (gemini-2.5-flash)      │
             └─────────────┬─────────────┘
                           │
             ┌─────────────▼─────────────┐
             │   Options Post-Cleaner    │
             │   - Exact 4 choices       │
             │   - Farewell at index 3   │
             └─────────────┬─────────────┘
                           │
                  ┌────────▼─────────┐
                  │  Response JSON   │
                  │  (Unity Ready)   │
                  └──────────────────┘
```

### 1. File Descriptions

#### 🖥️ API & Gemini Integration (`api/main.py`)
* **Endpoint /get_response**: The main communication route. Resolves intent in `game_logic.py`, queries recent chat history and vector search facts, formats messages for Gemini API, cleans option choices, and saves details in SQLite.
* **clean_player_options(options, fallbacks)**: Filters, trims, and deduplicates dialogue choices. Ensures exactly 4 unique options are presented to the player, with a farewell option always locked in the 4th position.
* **Parameters**: Runs Gemini text generation with `temperature=0.85` and `gemini-2.5-flash` model configuration to guarantee creative, fast, and structured dialogue.

#### ⚔️ RPG Logic Layer (`api/game_logic.py`)
* **detect_intent(player_input)**: Matches input triggers against keywords to identify actions like `buy_item`, `sell_item`, `accept_quest`, `complete_quest`, `greeting`, `goodbye`, `ask_location`, etc.
* **State Updates**: Code resolves purchases, sales, and quest progressions inside transactional checks (e.g. validating gold amounts or items present in inventory).
* **build_game_context(player, npc, intent, action)**: Builds the structured state block that is passed under `[GAME STATE]` in the prompt, telling the LLM exactly what occurred.

#### 🗄️ Database Setup (`api/create_db.py`)
* Compiles the schema tables: `NPCs`, `Players`, `Conversations` (with `player_options TEXT`), `QuestState`, `Items`, `Inventory`, `ShopItems`, `Relationships`, and `Memories`.
* Seeds NPCs (Captain Aldric, Mira, Elder Thorn, Shade), shops inventory (weapons, potions), and pre-seeded starting choices.

#### 🔍 World Lore Vector Store (`api/build_vector_store.py`)
* Uses `langchain-huggingface` to load the `all-MiniLM-L6-v2` embedding model.
* Splits `api/world_facts.txt` (detailing Ironhaven, the inner keep, Frostbane Katana, the forest wardens, etc.) into FAISS vector files for similarity-based factual context injection.

#### 🎨 Client Dashboard (`api/index.html`)
* A dynamic glassmorphic interface that handles registration (Warrior, Mage, Cleric, Rogue), Settings changes, real-time stats updates (gold, active quest count, inventory), and conversation feeds.
* Restores the exact choices of the last conversation turn when loading history or switching between NPCs to ensure players are never locked out of dialogue choices.

---

## ⚙️ Key Technical Features

### 1. Option Loop Resolution
In previous iterations, the chat history prompt structure hardcoded previous turns' options to `["Tell me more.", "What else?", "I see.", "Farewell."]`. The model learned this pattern and repeated them continually, preventing dynamic progression.
* **Fix**: The `Conversations` table now holds a `player_options` JSON column. The prompt history loop parses and restores these options exactly as they occurred, teaching the model the connection between NPC dialogue and player choices.

### 2. Immersion Guard (Rule 7)
Small models (0.5B) tend to output stats commentary when seeing relationship data in the prompt (e.g., *"Your trust increases with my purchases"*).
* **Fix**: Rule 7 was integrated into the system prompt:
  > *7. NEVER reference numerical stats, trust changes, gold values, or database terms in your dialogue. Keep all conversation entirely in-character and immersive. For example, instead of saying 'Your trust increased', say 'I appreciate your business' or 'I feel I can trust you more now'.*
* A second few-shot example was added detailing a purchase transaction to guide the tone of gameplay actions.

### 3. Click Selector Collision Resolution
The click event listener `document.querySelectorAll('.class-card')` was matching both the registration cards and settings modal cards. Settings modal cards lacked the `data-class` attribute, overriding selected class settings to `null` and raising validation exceptions.
* **Fix**: Scoped the click listener strictly to the registration overlay:
  `document.querySelectorAll('#registration-overlay .class-card')`

---

## 🔌 Unity Integration Specs

The API responses from `/get_response` are explicitly structured as a complete state delta JSON for easy deserialization in C# (e.g., inside Godot or Unity):

```json
{
  "npc_response": "A fine choice, warrior. This steel blade is sturdy and will keep you safe in battle. Here is your weapon.",
  "player_options": [
    "Thank you.",
    "What else do you have for sale?",
    "Do you need any help?",
    "Farewell."
  ],
  "inventory_changes": {
    "gold": -15,
    "items_added": ["Steel Sword"],
    "items_removed": []
  },
  "quest_updates": {},
  "relationship_updates": {
    "trust": 5,
    "friendship": 3
  },
  "memory_updates": [
    "Bought Steel Sword for 15 gold"
  ]
}
```

* Connect Unity web requests directly to `POST http://127.0.0.1:8001/get_response`.
* Update Unity local player states using `inventory_changes`, `quest_updates`, and `relationship_updates` parameters returned.