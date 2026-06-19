extends Node

signal refresh_hud

@export var gold: int
@export var katana: bool
var player_name = "DEBUG"
var items = []

var existent_items = {
	"1": true,
	"2": true,
	"3": true,
	"4": true,
	"5": true,
	"6": true,
	"7": true,
	"8": true
}

func _ready():
	gold = 0
	katana = false
	items = []

func remove_coins_and_gain_katana(price: int):
	gold = 0
	katana = true
	refresh_hud.emit()

func add_gold(amount: int):
	gold += amount
	refresh_hud.emit()

func remove_gold(amount: int):
	gold = max(gold - amount, 0)
	refresh_hud.emit()

func add_inventory_item(item: InventoryItem):
	items.append(item)
	refresh_hud.emit()

func remove_inventory_item(item_name: String):
	for i in items.size():
		if items[i] != null and items[i].name == item_name:
			items.remove_at(i)
			refresh_hud.emit()
			return

func pick_up_gold(id: String):
	existent_items[id] = false
	gold += 1
	refresh_hud.emit()
