import urllib.request
import urllib.parse
import json
import sys

API_URL = "http://127.0.0.1:8001"

def call_post(endpoint, payload):
    req_url = f"{API_URL}{endpoint}"
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(req_url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read().decode('utf-8'))
    except Exception as e:
        print(f"Error calling POST {endpoint}: {e}")
        if hasattr(e, 'read'):
            print("Response detail:", e.read().decode('utf-8'))
        raise

def call_get(endpoint):
    req_url = f"{API_URL}{endpoint}"
    try:
        with urllib.request.urlopen(req_url) as res:
            return json.loads(res.read().decode('utf-8'))
    except Exception as e:
        print(f"Error calling GET {endpoint}: {e}")
        raise

def run_tests():
    player_name = "IntegrationTestHero"
    print(f"--- Starting Integration Tests for player: {player_name} ---")

    # 1. Register Player
    print("\n1. Testing /register_player...")
    reg_res = call_post("/register_player", {"player_name": player_name, "character_class": "mage"})
    print("Register Response:", reg_res)
    assert reg_res["success"] == True
    assert reg_res["player_name"] == player_name
    assert reg_res["character_class"] == "mage"

    # 2. Get Player Inventory and verify default HP/Max HP
    print("\n2. Testing /player_inventory (Default Stats)...")
    inv_res = call_get(f"/player_inventory/{urllib.parse.quote(player_name)}")
    print("Inventory/Stats Response:", inv_res)
    assert inv_res["gold"] == 100
    assert inv_res["hp"] == 100
    assert inv_res["max_hp"] == 100

    # 3. Test /update_hp (Deduct HP and check penalty)
    print("\n3. Testing /update_hp (Hp reduction + Gold change)...")
    hp_res = call_post("/update_hp", {"player_name": player_name, "hp": 45, "gold_change": -10})
    print("Update HP Response:", hp_res)
    assert hp_res["success"] == True

    inv_res2 = call_get(f"/player_inventory/{urllib.parse.quote(player_name)}")
    print("New Inventory/Stats:", inv_res2)
    assert inv_res2["hp"] == 45
    assert inv_res2["gold"] == 90

    # 4. Test /add_loot (Add Raw Meat and Diamond)
    print("\n4. Testing /add_loot...")
    loot_res = call_post("/add_loot", {
        "player_name": player_name,
        "gold_reward": 15,
        "items_reward": ["Raw Meat", "Raw Meat", "Raw Meat", "Diamond"]
    })
    print("Add Loot Response:", loot_res)
    assert loot_res["success"] == True

    inv_res3 = call_get(f"/player_inventory/{urllib.parse.quote(player_name)}")
    print("Inventory after loot:", inv_res3)
    assert inv_res3["gold"] == 105
    items = {item["name"]: item["quantity"] for item in inv_res3["items"]}
    assert items["Raw Meat"] == 3
    assert items["Diamond"] == 1

    # 5. Test /consume_item (Eat Raw Meat, +3-5 HP)
    print("\n5. Testing /consume_item...")
    consume_res = call_post("/consume_item", {"player_name": player_name, "item_name": "Raw Meat"})
    print("Consume Response:", consume_res)
    assert consume_res["success"] == True
    assert 48 <= consume_res["hp"] <= 50

    inv_res4 = call_get(f"/player_inventory/{urllib.parse.quote(player_name)}")
    print("Inventory after consumption:", inv_res4)
    items_after = {item["name"]: item["quantity"] for item in inv_res4["items"]}
    assert items_after["Raw Meat"] == 2

    # 6. Test /use_weapon (Weapon Durability)
    # Add a Frostbane Katana to test durability
    print("\n6. Testing /use_weapon (Frostbane Katana durability)...")
    call_post("/add_loot", {
        "player_name": player_name,
        "gold_reward": 0,
        "items_reward": ["Frostbane Katana"]
    })
    # Initial durability check
    inv_res5 = call_get(f"/player_inventory/{urllib.parse.quote(player_name)}")
    katana_item = next(item for item in inv_res5["items"] if item["name"] == "Frostbane Katana")
    print("Initial Katana Durability:", katana_item["durability"])
    assert katana_item["durability"] == 5

    # Use weapon 5 times until it breaks
    for i in range(1, 6):
        use_res = call_post("/use_weapon", {"player_name": player_name, "weapon_name": "Frostbane Katana"})
        print(f"Use {i}:", use_res)
        assert use_res["success"] == True
        if i < 5:
            assert use_res["broken"] == False
            assert use_res["durability"] == 5 - i
        else:
            assert use_res["broken"] == True
            assert use_res["durability"] == 0

    inv_res6 = call_get(f"/player_inventory/{urllib.parse.quote(player_name)}")
    print("Inventory after weapon broke:", inv_res6)
    assert not any(item["name"] == "Frostbane Katana" for item in inv_res6["items"])

    # 7. Test /craft_diamond_sword
    # Need 1 Diamond and 3 Raw Meats. We currently have 1 Diamond and 2 Raw Meats in inventory.
    # Craft should fail initially.
    print("\n7. Testing /craft_diamond_sword...")
    try:
        craft_fail = call_post("/craft_diamond_sword", {"player_name": player_name})
        print("Craft Fail Response (should fail):", craft_fail)
        assert craft_fail["success"] == False
    except Exception:
        # If server throws HTTP error instead, that's okay, but let's see.
        pass

    # Add 1 Raw Meat to make it 3
    call_post("/add_loot", {
        "player_name": player_name,
        "gold_reward": 0,
        "items_reward": ["Raw Meat"]
    })

    # Craft should succeed now
    craft_success = call_post("/craft_diamond_sword", {"player_name": player_name})
    print("Craft Success Response:", craft_success)
    assert craft_success["success"] == True

    inv_res7 = call_get(f"/player_inventory/{urllib.parse.quote(player_name)}")
    print("Inventory after craft:", inv_res7)
    items_after_craft = {item["name"]: item for item in inv_res7["items"]}
    assert "Diamond" not in items_after_craft
    assert "Raw Meat" not in items_after_craft
    assert "Diamond Greatsword" in items_after_craft
    assert items_after_craft["Diamond Greatsword"]["durability"] == 15

    # 8. Test /reset_castle_gate
    print("\n8. Testing /reset_castle_gate...")
    # First, initialize quest state by starting a quest
    # Simulate Aldric dialogue quest check
    call_post("/get_response", {
        "player_name": player_name,
        "npc_name": "Captain Aldric",
        "held_items": "100 Gold",
        "player_input": "What do I need to enter the keep?"
    })

    gate_res = call_post("/reset_castle_gate", {"player_name": player_name})
    print("Reset Castle Gate Response:", gate_res)
    assert gate_res["success"] == True

    quest_res = call_get(f"/quest_state/{urllib.parse.quote(player_name)}")
    print("Quest State Response:", quest_res)
    main_quest = next(q for q in quest_res["quests"] if q["quest_id"] == "main_enter_keep")
    assert main_quest["status"] == "in_progress"
    assert main_quest["current_step"] == 2

    # 9. Test /update_quest_progress (dynamic progress tracking)
    print("\n9. Testing /update_quest_progress...")
    # Seed a quest first so we can progress it
    call_post("/get_response", {
        "player_name": player_name,
        "npc_name": "Elder Thorn",
        "held_items": "100 Gold",
        "player_input": "I accept the boar hunt task."
    })
    progress_res = call_post("/update_quest_progress", {
        "player_name": player_name,
        "quest_id": "side_boar_hunter",
        "flag_key": "kills",
        "increment": 1
    })
    print("Quest Progress Response:", progress_res)
    assert progress_res["success"] == True
    assert progress_res["flags"]["kills"] == 1

    # 10. Test /craft_shadowflame_dagger
    print("\n10. Testing /craft_shadowflame_dagger...")
    # Add loot first
    call_post("/add_loot", {
        "player_name": player_name,
        "gold_reward": 50,
        "items_reward": ["Royal Scepter", "Ruby Ring"]
    })
    craft_dagger_res = call_post("/craft_shadowflame_dagger", {"player_name": player_name})
    print("Craft Dagger Response:", craft_dagger_res)
    assert craft_dagger_res["success"] == True

    inv_res_dagger = call_get(f"/player_inventory/{urllib.parse.quote(player_name)}")
    print("Inventory after dagger craft:", inv_res_dagger)
    items_after_dagger = {item["name"]: item for item in inv_res_dagger["items"]}
    assert "Royal Scepter" not in items_after_dagger
    assert "Ruby Ring" not in items_after_dagger
    assert "Shadowflame Dagger" in items_after_dagger
    assert items_after_dagger["Shadowflame Dagger"]["durability"] == 10

    print("\n--- ALL TESTS COMPLETED SUCCESSFULLY! ---")

if __name__ == "__main__":
    run_tests()
