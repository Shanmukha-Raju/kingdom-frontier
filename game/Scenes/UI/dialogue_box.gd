extends CanvasLayer

signal option_selected(selected_text, selected_index)

@onready var text_field = $DialogueBox/TextBox/MarginContainer/TextField
@onready var letter_display_timer = $DialogueBox/LetterDisplayTimer
@onready var punctuation_timer = $DialogueBox/PunctuationTimer
@onready var dialogue_box = $DialogueBox
@onready var face = $DialogueBox/TextBox/Face
@onready var name_or_title = $DialogueBox/TextBox/NameOrTitle
@onready var dialogue_sound = $DialogueSound
@onready var continue_indicator = $DialogueBox/TextBox/ContinueIndicator
@onready var options_container = $DialogueBox/TextBox/OptionsContainer
@onready var option_button_1 = $DialogueBox/TextBox/OptionsContainer/OptionButton1
@onready var option_button_2 = $DialogueBox/TextBox/OptionsContainer/OptionButton2
@onready var option_button_3 = $DialogueBox/TextBox/OptionsContainer/OptionButton3
@onready var option_button_4 = $DialogueBox/TextBox/OptionsContainer/OptionButton4

const MAX_WIDTH = 256

var text = ""
var letter_index = 0

var letter_time = 0.02
var space_time = 0.05
var punctuation_time = 0.25

var faceset_path
var npc_name

signal finished_displaying()

func _ready():
	set_face(faceset_path, npc_name)
	continue_indicator.hide()
	options_container.visible = false
	option_button_1.pressed.connect(func(): _on_option_button_pressed(0))
	option_button_2.pressed.connect(func(): _on_option_button_pressed(1))
	option_button_3.pressed.connect(func(): _on_option_button_pressed(2))
	option_button_4.pressed.connect(func(): _on_option_button_pressed(3))

func display_text(text_to_display: String):
	text = text_to_display
	
	text_field.text = ""
	_display_letter()

func _display_letter():
	# Check first: if letter_index is out-of-range, finish displaying.
	if letter_index >= text.length():
		finished_displaying.emit()
		continue_indicator.show()
		return
		
	text_field.text += text[letter_index]
	
	letter_index += 1
	if letter_index >= text.length():
		finished_displaying.emit()
		continue_indicator.show()
		return
	
	match text[letter_index]:
		"!", ".", ",", "?":
			punctuation_timer.start(punctuation_time)
		" ":
			letter_display_timer.start(space_time)
		_:
			letter_display_timer.start(letter_time)

func _on_letter_display_timer_timeout():
	if randi_range(0, 1) > 0:
		play_audio()
	_display_letter()

func _on_punctuation_timer_timeout():
	play_audio()
	_display_letter()
	
func set_editable(boolean):
	text_field.editable = boolean

func erase_text():
	text_field.text = ""
	continue_indicator.hide()

func get_text() -> String:
	return text_field.text

func set_focus():
	text_field.grab_focus()

func show_options(options: Array) -> void:
	option_button_1.visible = false
	option_button_2.visible = false
	option_button_3.visible = false
	option_button_4.visible = false
	options_container.visible = false

	if options.empty():
		return

	options_container.visible = true
	var buttons = [option_button_1, option_button_2, option_button_3, option_button_4]
	for i in buttons.size():
		if i < options.size():
			buttons[i].text = options[i]
			buttons[i].visible = true
		else:
			buttons[i].visible = false

func _on_option_button_pressed(index: int) -> void:
	if index < 0 or index > 3:
		return
	var button = [option_button_1, option_button_2, option_button_3, option_button_4][index]
	emit_signal("option_selected", button.text, index)

func play_audio():
	var audio_scene = load("res://Scenes/UI/dialogue_audio.tscn")
	var audio = audio_scene.instantiate()
	$".".add_child(audio)

func skip_typing():
	# Stop the timers so _display_letter() doesn't continue
	if letter_display_timer.is_stopped() == false:
		letter_display_timer.stop()
	if punctuation_timer.is_stopped() == false:
		punctuation_timer.stop()
	
	# Immediately display the complete text
	text_field.text = text
	letter_index = text.length()
	
	# Emit signal to let DialogueManager know we're done and show the indicator.
	finished_displaying.emit()
	continue_indicator.visible = true

func set_face(faceset_path, display_name):
	face.texture = load(faceset_path)
	name_or_title.text = display_name
