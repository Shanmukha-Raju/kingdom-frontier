extends CanvasLayer

@onready var texture_rect_9 = $NinePatchRect/MarginContainer/HBoxContainer/TextureRect9
@onready var gold_label = $NinePatchRect/MarginContainer/HBoxContainer/GoldLabel
@onready var help_button = $NinePatchRect/MarginContainer/HBoxContainer/HelpButton
@onready var help_dialog = $HelpDialog
@onready var close_button = $HelpDialog/MarginContainer/VBoxContainer/CloseButton

func _ready():
	PersistanceManager.refresh_hud.connect(refresh_hud)
	help_button.pressed.connect(_on_help_button_pressed)
	close_button.pressed.connect(_on_close_help)
	refresh_hud()

func _on_help_button_pressed():
	help_dialog.popup_centered_ratio(0.75)

func _on_close_help():
	help_dialog.hide()

func refresh_hud():
	gold_label.text = "Gold: " + str(PersistanceManager.gold)
	if PersistanceManager.katana == true:
		texture_rect_9.show()
		for i in PersistanceManager.existent_items:
			var node = "NinePatchRect/MarginContainer/HBoxContainer/TextureRect" + i
			get_node(node).hide()
		return
		
	for i in PersistanceManager.existent_items:
		var node = "NinePatchRect/MarginContainer/HBoxContainer/TextureRect" + i
		if PersistanceManager.existent_items[i] == false:
			get_node(node).show()
		else:
			get_node(node).hide()
