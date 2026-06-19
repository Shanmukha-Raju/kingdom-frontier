extends Node

@onready var text_box_scene = preload("res://Scenes/UI/dialogue_box.tscn")

var face_images = {
	"Merchant": "res://Assets/Ninja Adventure/Actor/Characters/OldMan/Faceset.png",
	"Sensei": "res://Assets/Ninja Adventure/Actor/Characters/OldMan3/Faceset.png",
	"Mother": "res://Assets/Ninja Adventure/Actor/Characters/OldWoman/Faceset.png",
	"Guard": "res://Assets/Ninja Adventure/Actor/Characters/RedNinja3/Faceset.png",
	"Statue": "res://Assets/Ninja Adventure/Actor/Characters/Boy/Faceset.png",
	"Player": "res://Assets/Ninja Adventure/Actor/Characters/Boy/Faceset.png",
	"Forest": "res://Assets/Ninja Adventure/Actor/Characters/Boy/Faceset.png"
}

var dialogue_lines: Array[String] = []
var current_line_index = 0

var text_box
var text_box_field
var npc_type
var player_options: Array[String] = []

var input_lock_timer: Timer
@export var input_locked: bool
var lock_time = 0.1

var is_dialogue_active = false
var can_advance_line = false
var editable = false

# New flag for monologue mode
var monologue_mode = false

signal dialogue_finished
signal request_finished

var messages = []
var request: HTTPRequest
var url = "http://127.0.0.1:8000/"

func _ready():
	input_lock_timer = Timer.new()
	input_lock_timer.one_shot = true
	add_child(input_lock_timer)
	input_lock_timer.connect("timeout", _on_timer_timeout)
	
	dialogue_lines.append("Hello World")
	request = HTTPRequest.new()
	add_child(request)
	request.connect("request_completed", _on_request_completed)

func start_dialogue(type):
	editable = false
	if is_dialogue_active:
		return
	
	npc_type = type
	
	# If the dialogue is for the Player, enter monologue mode:
	match npc_type:
		"Statue":
			monologue_mode = true
			dialogue_lines.clear()
			dialogue_lines.push_back("Statues don't talk.")
		"Forest":
			monologue_mode = true
			dialogue_lines.clear()
			dialogue_lines.push_back("Mom said, it's too dangerous to walk in the forest alone.")
		_:
			monologue_mode = false
			latest_dialogue_request()
			await request_finished
	
	_show_text_box()
	is_dialogue_active = true

func _show_text_box():
	text_box = text_box_scene.instantiate()
	text_box.faceset_path = face_images[npc_type]
	text_box.npc_name = npc_type
	text_box.finished_displaying.connect(_on_text_box_finished_displaying)
	text_box.option_selected.connect(_on_option_selected)
	get_tree().root.add_child(text_box)
	text_box.display_text(dialogue_lines.back())
	text_box.show_options(player_options)
	can_advance_line = false

func _on_text_box_finished_displaying():
	can_advance_line = true

func _input(event):
	if input_locked:
		get_viewport().set_input_as_handled()
		return

	# Handle Escape key to close dialogue
	if event.is_action_pressed("escape"):
		if is_dialogue_active:
			_close_dialogue()
			get_viewport().set_input_as_handled()
		return

	# Only process relevant input when dialogue is active
	if not (event.is_action_pressed("ui_accept") and is_dialogue_active):
		return

	get_viewport().set_input_as_handled()

	# Handle monologue mode
	if monologue_mode:
		return

	# Handle different dialogue states
	if not can_advance_line:
		_skip_typing()
		return

	if not editable:
		_advance_to_player_input()
		return

	_handle_player_response()

func _close_dialogue():
	is_dialogue_active = false
	monologue_mode = false
	current_line_index = 0
	dialogue_finished.emit()
	# FIX: Validate the instance exists before freeing to prevent double-free crashes
	if is_instance_valid(text_box):
		text_box.queue_free()

func _skip_typing():
	lock_input()
	text_box.skip_typing()

func _advance_to_player_input():
	lock_input()
	text_box.erase_text()
	current_line_index += 1
	call_deferred("_enable_player_input")

func _handle_player_response():
	if text_box.get_text().length() < 2:
		return # Optionally add feedback for short input

	if text_box.get_text() == dialogue_lines.back():
		lock_input()
		editable = false
		text_box.set_editable(false)
		return

	lock_input()
	editable = false
	text_box.set_editable(false)
	dialogue_request(text_box.get_text(), -1)
	
	# Defer the UI update to avoid await in input handler
	var _request_completed = await request_finished
	
	# FIX: Protect against a mid-air cancel if the player closed dialogue while the network thread slept
	if is_dialogue_active and is_instance_valid(text_box):
		text_box.queue_free()
		_show_text_box()

func _on_option_selected(option_text: String, option_index: int) -> void:
	if not is_dialogue_active:
		return
	if not can_advance_line:
		return

	lock_input()
	editable = false
	text_box.set_editable(false)
	dialogue_request(option_text, option_index)

	var _request_completed = await request_finished
	if is_dialogue_active and is_instance_valid(text_box):
		text_box.queue_free()
		_show_text_box()

func _on_request_completed(_result, response_code, _headers, body):
	if response_code != 200:
		print("Error: Server returned status code", response_code)
		dialogue_lines.push_back("Oh no, there seems to be a problem with my mind... Could you please reach out to the developer and try again later?")
		request_finished.emit()
		return
		
	var json = JSON.new()
	json.parse(body.get_string_from_utf8())
	var response = json.get_data()
	
	var message = response.get("npc_response", response.get("response", ""))
	var action = response.get("action", response.get("npc_action", ""))
	player_options = response.get("player_options", [])
	var inventory_changes = response.get("inventory_changes", {})
	
	dialogue_lines.push_back(message)
	print("NPC says: ", message)
	
	_apply_inventory_changes(inventory_changes)
	
	# Process NPC actions
	match action:
		"sell_katana":
			print("Merchant sale action handled by inventory changes.")
		"open_door":
			InteractionManager.open_door.emit()
			print("Guard opened door")
		_:
			print("No special action taken")

	request_finished.emit()

func _apply_inventory_changes(changes: Dictionary) -> void:
	if changes == null or changes.empty():
		return

	if changes.has("gold"):
		var gold_change = int(changes["gold"])
		if gold_change > 0:
			PersistanceManager.add_gold(gold_change)
		elif gold_change < 0:
			PersistanceManager.remove_gold(-gold_change)

	if changes.has("items_added"):
		for item_name in changes["items_added"]:
			_add_item_by_name(str(item_name))

	if changes.has("items_removed"):
		for item_name in changes["items_removed"]:
			PersistanceManager.remove_inventory_item(str(item_name))

func _add_item_by_name(item_name: String) -> void:
	var item_resource: Resource = null
	match item_name.to_lower():
		"steel sword", "sword":
			item_resource = preload("res://Resources/Weapons/Sword/sword_inventory_item.tres")
		"frostbane katana":
			item_resource = preload("res://Resources/Weapons/Sword/sword_inventory_item.tres")
			# keep the same visual for now, but update the name
		"health potion":
			# fallback to a generic item if no dedicated resource exists
			item_resource = preload("res://Resources/Weapons/Sword/sword_inventory_item.tres")
		_:
			item_resource = preload("res://Resources/Weapons/Sword/sword_inventory_item.tres")

	if item_resource:
		var item_instance = item_resource.duplicate(true)
		if item_name != "Sword":
			item_instance.name = item_name
		PersistanceManager.add_inventory_item(item_instance)

func dialogue_request(player_dialogue, selected_option_index: int = -1):
	print("Player says: " + player_dialogue)
	var payload = JSON.stringify({
		"player_name": PersistanceManager.player_name,
		"npc_name": npc_type,
		"held_items": count_items(),
		"player_input": player_dialogue,
		"selected_option_index": selected_option_index
	})

	var send_request = request.request(
		url + "get_response", [], HTTPClient.METHOD_POST, payload)
	
	if send_request != OK:
		print("Error with request")

func latest_dialogue_request():
	var payload = JSON.stringify({
		"player_name": PersistanceManager.player_name,
		"npc_name": npc_type,
		"held_items": count_items(),
		"player_input": ""
	})
	var send_request = request.request(
		url + "get_latest_response", [], HTTPClient.METHOD_POST, payload)
	
	if send_request != OK:
		print("Error with request")

func count_items() -> String:
	var held = []
	for item in PersistanceManager.items:
		if item and item.name != "":
			held.append(item.name)

	if PersistanceManager.katana:
		held.append("Katana")

	if held.empty():
		return str(PersistanceManager.gold) + " Gold"
	return str(PersistanceManager.gold) + " Gold, " + ", ".join(held)

func lock_input():
	input_locked = true
	if input_lock_timer:
		input_lock_timer.start(lock_time)

func _on_timer_timeout():
	input_locked = false
	if input_lock_timer:
		input_lock_timer.stop()

func _enable_player_input():
	text_box.set_face(face_images["Player"], PersistanceManager.player_name)
	
	editable = true
	text_box.set_editable(true)
	text_box.set_focus()
