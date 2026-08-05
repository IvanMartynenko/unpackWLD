@tool
extends Node3D

## Builds the game world directly in the editor from the raw unpacker
## output (world_tree.json / models_info.json / object_list.json) instead
## of a pre-baked web_scene.json. The previous version did everything for
## all ~52k instances synchronously in one call - loading ~2850 unique
## model scenes and filling their MultiMesh transforms back-to-back with
## no yielding - which is what crashed the editor. This one groups by
## file exactly the same way, but yields to the editor's main loop between
## each unique file (mirrors node_3d.gd's already-working runtime
## build_world(), which uses the same `await get_tree().process_frame`
## pattern without issue).

@export_category("World Generator")
@export_file("*.json") var world_tree_path: String = "/VaBankData/VaBank_unpack/world_tree.json"
@export_file("*.json") var models_info_path: String = "/VaBankData/VaBank_unpack/models_info.json"
@export_file("*.json") var object_list_path: String = "/VaBankData/VaBank_unpack/object_list.json"

@export var generate_world: bool = false :
	set = _on_generate_pressed

@export var clear_previous: bool = true

var _building: bool = false

func _on_generate_pressed(value: bool) -> void:
	# Только реагируем на переход в true - иначе deferred-сброс ниже сам
	# себя бесконечно переставляет в очередь (каждый вызов с value=false
	# заново вызывал set_deferred(..., false)), что мгновенно
	# переполняло MessageQueue вне зависимости от ее размера и было
	# настоящей причиной всех крашей выше, а не память/дерево сцены.
	if not value:
		return
	if is_inside_tree() and not _building:
		build_world_in_editor()
	set_deferred("generate_world", false)

func build_world_in_editor() -> void:
	if not Engine.is_editor_hint():
		return

	var edited_scene := get_tree().edited_scene_root
	if edited_scene == null:
		printerr("Ошибка: Не удалось получить корень сцены.")
		return

	_building = true

	print("[DBG] clear_previous start, child_count=", get_child_count())
	if clear_previous:
		for child in get_children():
			child.queue_free()
	print("[DBG] clear_previous done")

	print("[DBG] loading world_tree_path=", world_tree_path)
	var world_tree = _load_json(world_tree_path)
	print("[DBG] world_tree loaded, is_null=", world_tree == null)
	print("[DBG] loading models_info_path=", models_info_path)
	var models_info = _load_json(models_info_path)
	print("[DBG] models_info loaded, is_null=", models_info == null)
	print("[DBG] loading object_list_path=", object_list_path)
	var object_list = _load_json(object_list_path)
	print("[DBG] object_list loaded, is_null=", object_list == null)
	if world_tree == null or models_info == null or object_list == null:
		_building = false
		return

	print("[DBG] building folder hierarchy")
	var folder_info := _build_folder_hierarchy(world_tree)
	var folder_nodes: Dictionary = folder_info["folders"]
	var by_index: Dictionary = folder_info["by_index"]
	print("[DBG] folder hierarchy built, folders=", folder_nodes.size())

	print("Разбор world_tree.json (", world_tree.size(), " узлов)...")
	print("[DBG] calling _resolve_instances")
	var resolved := _resolve_instances(world_tree, models_info, object_list, folder_info)
	# file -> folder_index (-1 = нет папки/верхний уровень) -> Array[instance]
	var instances_by_file_folder: Dictionary = resolved["by_file"]
	# index -> {file_path, pos, rot, scale, parent_id} - см. _resolve_instances
	var special_instances: Dictionary = resolved["special"]
	print(
		"[DBG] _resolve_instances done, unique files=", instances_by_file_folder.size(),
		", special=", special_instances.size(),
	)
	# Отдаем память сырых JSON-массивов до того, как начнем грузить модели -
	# world_tree.json один держит в разобранном виде сотни MB.
	print("[DBG] nulling raw json refs")
	world_tree = null
	models_info = null
	object_list = null
	print("[DBG] nulled raw json refs")

	if instances_by_file_folder.is_empty():
		print("Нет объектов для генерации.")
		_building = false
		return

	var total_files := instances_by_file_folder.size()
	var total_instances := special_instances.size()
	for file_name: String in instances_by_file_folder:
		var by_folder: Dictionary = instances_by_file_folder[file_name]
		for folder_key in by_folder:
			total_instances += by_folder[folder_key].size()
	print("Начинаем генерацию MultiMesh. Файлов: ", total_files, ", инстансов: ", total_instances)

	# Строим весь мир под отдельным, НЕ прикрепленным к дереву узлом (в т.ч.
	# все папки из folder_nodes). add_child() на живую edited-сцену гоняет
	# SceneTreeDock/инспектор на передрав через MessageQueue на КАЖДЫЙ
	# вызов - тысячи add_child() подряд переполняют очередь ("Message
	# queue out of memory", "Object was deleted while awaiting a
	# callback") и в итоге роняют редактор. Пока world_root не в дереве,
	# add_child по нему - это просто дешевая операция в памяти, редактор
	# о ней не знает и никак на нее не реагирует. Прикрепляем весь готовый
	# поддерево одним add_child() в самом конце.
	var world_root := Node3D.new()
	world_root.name = "GeneratedWorld"
	# Папки верхнего уровня (чей родитель - не папка) вешаем сразу под
	# world_root; остальные уже связаны друг с другом внутри folder_nodes.
	for folder_index in folder_nodes:
		var fnode: Node3D = folder_nodes[folder_index]
		if fnode.get_parent() == null:
			world_root.add_child(fnode)

	var processed_files := 0
	var created_instances := 0
	# Общий на весь build: файл может встретиться и в обычной группировке,
	# и среди special_instances ниже - грузим/распаковываем каждый файл
	# максимум один раз за весь запуск.
	var mesh_cache: Dictionary = {}

	for file_name: String in instances_by_file_folder:
		var by_folder: Dictionary = instances_by_file_folder[file_name]
		var file_instance_count := 0
		for folder_key in by_folder:
			file_instance_count += by_folder[folder_key].size()

		var parts := _load_mesh_parts(file_name, mesh_cache)
		if parts.is_empty():
			processed_files += 1
			continue

		for folder_key in by_folder:
			var nodes_data: Array = by_folder[folder_key]
			var instance_count := nodes_data.size()
			var parent_node: Node3D = folder_nodes.get(folder_key, world_root)

			for part in parts:
				var mmi := MultiMeshInstance3D.new()
				mmi.name = file_name.get_file().get_basename() + "_" + String(part["name"])

				var mm := MultiMesh.new()
				mm.transform_format = MultiMesh.TRANSFORM_3D
				mm.use_custom_data = false
				mm.mesh = part["mesh"]
				mm.instance_count = instance_count
				mmi.multimesh = mm

				if part["material"]:
					mmi.material_override = part["material"]

				var internal_transform: Transform3D = part["internal_transform"]
				for i in range(instance_count):
					var data: Dictionary = nodes_data[i]
					var json_xform := _compute_instance_transform(
						data["pos"], float(data.get("rot", 0.0)), float(data.get("scale", 1.0))
					)
					mm.set_instance_transform(i, json_xform * internal_transform)

				parent_node.add_child(mmi)

		created_instances += file_instance_count
		processed_files += 1
		# Один компактный лог на файл - если упадет, последняя строка
		# перед крашем скажет, на каком именно файле и с какого номера.
		print("[DBG] #%d/%d %s (%d inst, %d parts, %d folders) total=%d" % [
			processed_files, total_files, file_name, file_instance_count,
			parts.size(), by_folder.size(), created_instances,
		])
		# Отдаем кадр редактору между файлами - без этого редактор виснет
		# и в итоге вылетает на ~2850 последовательных load()+instantiate().
		# Двойной await и доп. пауза каждые 50 файлов - на случай, если
		# фоновая подгрузка ресурсов (WorkerThreadPool) не успевает
		# разгрести свою очередь колбэков за один кадр.
		await get_tree().process_frame
		await get_tree().process_frame
		if processed_files % 50 == 0:
			for _i in range(10):
				await get_tree().process_frame

	# Особые инстансы - дети ДРУГИХ инстансов, не папок (см. коммент в
	# _resolve_instances) - строим индивидуальными узлами (MeshInstance3D
	# под общим Node3D-обёрткой на каждый), не MultiMesh, поскольку у
	# записи внутри MultiMesh не может быть child-а. Порядок важен: узел-
	# родитель должен существовать раньше своего инстанс-ребенка, поэтому
	# резолвим итеративно (в реальных данных цепочки не глубже 2 уровней,
	# но алгоритм этим не ограничен).
	if not special_instances.is_empty():
		print("[DBG] resolving ", special_instances.size(), " special (instance-child-of-instance) nodes")
		var special_folder_cache: Dictionary = {}
		var wrapper_nodes: Dictionary = {}
		var remaining: Array = special_instances.keys()
		var guard := 0
		while remaining.size() > 0 and guard < 20:
			guard += 1
			var still_remaining: Array = []
			for idx in remaining:
				var info: Dictionary = special_instances[idx]
				var parent_id: int = info["parent_id"]
				var container: Node3D

				if special_instances.has(parent_id):
					if not wrapper_nodes.has(parent_id):
						still_remaining.append(idx)
						continue
					container = wrapper_nodes[parent_id]
				else:
					var folder_key := _resolve_folder(
						parent_id, folder_nodes, by_index, special_folder_cache
					)
					container = folder_nodes.get(folder_key, world_root)

				var parts := _load_mesh_parts(info["file_path"], mesh_cache)
				var inst_xform := _compute_instance_transform(
					info["pos"], info["rot"], info["scale"]
				)

				var wrapper := Node3D.new()
				wrapper.name = info["file_path"].get_file().get_basename() + "_" + str(idx)
				for part in parts:
					var mi := MeshInstance3D.new()
					mi.name = String(part["name"])
					mi.mesh = part["mesh"]
					if part["material"]:
						mi.material_override = part["material"]
					mi.transform = inst_xform * part["internal_transform"]
					wrapper.add_child(mi)

				container.add_child(wrapper)
				wrapper_nodes[idx] = wrapper
				created_instances += 1

			remaining = still_remaining
			await get_tree().process_frame

		if remaining.size() > 0:
			printerr(
				"[DBG] could not resolve parent chain for special instances (cycle in parent_id?): ",
				remaining,
			)
		print("[DBG] special instances resolved: ", wrapper_nodes.size())

	print("[DBG] attaching world_root to edited scene, child_count=", world_root.get_child_count())
	add_child(world_root)
	print("[DBG] world_root attached")
	_set_owner_recursive(world_root, edited_scene)
	print("[DBG] owners set recursively")

	print("Генерация успешно завершена! Отрисовано инстансов: ", created_instances)
	_building = false

func _set_owner_recursive(node: Node, owner_node: Node) -> void:
	node.owner = owner_node
	for child in node.get_children():
		_set_owner_recursive(child, owner_node)

func _load_json(path: String) -> Variant:
	if not FileAccess.file_exists(path):
		printerr("Файл не найден: ", path)
		return null
	var f := FileAccess.open(path, FileAccess.READ)
	var json := JSON.new()
	if json.parse(f.get_as_text()) != OK:
		printerr("Ошибка парсинга JSON: ", path)
		return null
	return json.data

## Rebuilds the folder hierarchy from world_tree.json's type:0 nodes
## (folder_name/parent_id) - the same collections world.py built for
## Blender. Purely organizational: type:0 nodes do carry their own
## x/y/z/rotation/scaling in the raw JSON, but the existing web_scene.json
## pipeline already discarded those for folders (kept only
## id/parent_id/type/name), so folders here stay at identity transform too
## - matches the reference behavior and means nesting depth never shifts
## an instance's absolute position.
## Returns {"folders": Dictionary[int, Node3D], "by_index": Dictionary[int, Dictionary]}.
## Folders are linked to their parent folder here (still off-tree); a
## folder with no folder parent is left unparented for the caller to
## attach under world_root.
func _build_folder_hierarchy(world_tree: Array) -> Dictionary:
	var by_index: Dictionary = {}
	var folder_nodes: Dictionary = {}

	for n: Dictionary in world_tree:
		by_index[int(n["index"])] = n
		if n.get("type") == 0:
			var fname: String = String(n.get("folder_name", ""))
			if fname.is_empty():
				fname = "Folder_%d" % int(n["index"])
			var fnode := Node3D.new()
			fnode.name = fname
			folder_nodes[int(n["index"])] = fnode

	for folder_index in folder_nodes:
		var n: Dictionary = by_index[folder_index]
		var parent_id := int(n.get("parent_id", -1))
		if folder_nodes.has(parent_id):
			folder_nodes[parent_id].add_child(folder_nodes[folder_index])

	return {"folders": folder_nodes, "by_index": by_index}

## Walks up from start_parent_id until it hits a node that's a folder
## (mirrors world.py's cached_folders walk for the same reason: an
## instance's immediate parent_id is often another instance/task node, not
## a folder directly - keep walking until one is found). -1 = no folder
## found (attach directly under world_root). Memoized per parent_id since
## the same chains repeat across thousands of instances.
func _resolve_folder(start_parent_id: int, folder_nodes: Dictionary, by_index: Dictionary, cache: Dictionary) -> int:
	if cache.has(start_parent_id):
		return cache[start_parent_id]
	var pid := start_parent_id
	var result := -1
	var seen: Dictionary = {}
	while by_index.has(pid) and not seen.has(pid):
		seen[pid] = true
		if folder_nodes.has(pid):
			result = pid
			break
		pid = int(by_index[pid].get("parent_id", -1))
	cache[start_parent_id] = result
	return result

## Resolves the file for one world_tree node (type 1 via model_id, type 2
## via object_id -> object_list.json - see _resolve_instances' docstring
## for the full story), or "" if it can't be resolved. Extension swapped
## .nmf -> .fbx to match what nmf_to_fbx.py actually wrote into the
## project.
func _resolve_node_file(node: Dictionary, model_map: Dictionary, object_model_map: Dictionary) -> String:
	var node_type = node.get("type")
	var file_path: String = ""

	if node_type == 1:
		var mid = node.get("model_id")
		if mid != null and model_map.has(int(mid)):
			file_path = model_map[int(mid)]
	elif node_type == 2:
		var oid = node.get("object_id")
		if oid != null and object_model_map.has(int(oid)):
			file_path = object_model_map[int(oid)]

	if file_path.is_empty():
		return ""

	file_path = file_path.replace("\\", "/")
	if file_path.to_lower().ends_with(".nmf"):
		file_path = file_path.substr(0, file_path.length() - 4) + ".glb"
	return file_path

## Reproduces the (type, model_id/object_id) -> model file resolution that
## used to happen offline when web_scene.json was generated:
## - type 1: model_id indexes models_info.json directly.
## - type 2: object_id indexes object_list.json; its FIRST "models" entry
##   (regardless of "default_action" - verified against object 285
##   "Burglary Target", whose first entry is DUMMY/2726 but whose
##   default_action-flagged entry is INVISIBLE/model_3d_id 0, a sentinel
##   for "no model" - always picking default_action would silently drop
##   it) gives the model_3d_id, which then indexes models_info.json the
##   same way. See object_list.json's entry 336 ("Music") for a simpler
##   example: one model, STAND, model_3d_id 2732 -> feuerloescher_2732.nmf.
##
## Returns {"by_file": Dictionary, "special": Dictionary}:
## - "by_file": file -> folder_index (-1 = no folder) -> Array[{pos,rot,scale}],
##   for the normal MultiMesh-batched path (see the main loop).
## - "special": index -> {file_path, pos, rot, scale, parent_id} for
##   instances that are a DIRECT child of ANOTHER instance rather than a
##   folder (real, if rare - ~90 out of 58k in the actual data, verified
##   against world_tree.json; e.g. a task marker placed right next to the
##   specific machine it belongs to). Their own parent instance is pulled
##   in here too, even if that parent's own placement is otherwise
##   perfectly normal (folder-child) - it still needs to exist as an
##   individual node for its child to nest under, which MultiMesh can't
##   represent (an entry inside a MultiMesh's transform array isn't a
##   node - it can't have a child). See the main loop's special-instance
##   pass for how these get built/parented.
##
## Only x/y/z/rotation/scaling are kept per instance (not the full node
## dict, which for type 2/3 carries large unrelated info/task_list/light
## blobs).
func _resolve_instances(
	world_tree: Array, models_info: Array, object_list: Array, folder_info: Dictionary
) -> Dictionary:
	var model_map: Dictionary = {}
	for m in models_info:
		model_map[int(m["index"])] = String(m["system_filepath"])

	var object_model_map: Dictionary = {}
	for o in object_list:
		var models: Array = o.get("models", [])
		if models.is_empty():
			continue
		var chosen: Dictionary = models[0]
		var mid := int(chosen.get("model_3d_id", -1))
		if model_map.has(mid):
			object_model_map[int(o["index"])] = model_map[mid]

	var folder_nodes: Dictionary = folder_info["folders"]
	var by_index: Dictionary = folder_info["by_index"]
	var folder_cache: Dictionary = {}

	# First pass: which instances have a DIRECT instance (not folder)
	# parent? Both sides of such a pair (child AND parent) go to
	# "special" - see the docstring above.
	var special_indices: Dictionary = {}
	for node: Dictionary in world_tree:
		var t = node.get("type")
		if t != 1 and t != 2:
			continue
		var parent_id := int(node.get("parent_id", -1))
		var parent_node: Dictionary = by_index.get(parent_id, {})
		var parent_type = parent_node.get("type")
		if parent_type == 1 or parent_type == 2:
			special_indices[int(node["index"])] = true
			special_indices[parent_id] = true

	var instances_by_file: Dictionary = {}
	var special_instances: Dictionary = {}
	for node: Dictionary in world_tree:
		var file_path := _resolve_node_file(node, model_map, object_model_map)
		if file_path.is_empty():
			continue

		var idx := int(node["index"])
		var parent_id := int(node.get("parent_id", -1))

		if special_indices.has(idx):
			special_instances[idx] = {
				"file_path": file_path,
				"pos": [node["x"], node["y"], node["z"]],
				"rot": float(node.get("rotation", 0.0)),
				"scale": float(node.get("scaling", 1.0)),
				"parent_id": parent_id,
			}
			continue

		var folder_key := _resolve_folder(parent_id, folder_nodes, by_index, folder_cache)

		if not instances_by_file.has(file_path):
			instances_by_file[file_path] = {}
		var by_folder: Dictionary = instances_by_file[file_path]
		if not by_folder.has(folder_key):
			by_folder[folder_key] = []
		by_folder[folder_key].append({
			"pos": [node["x"], node["y"], node["z"]],
			"rot": float(node.get("rotation", 0.0)),
			"scale": float(node.get("scaling", 1.0)),
		})

	return {"by_file": instances_by_file, "special": special_instances}

## Computes the same absolute-position transform the main loop bakes into
## MultiMesh entries, for one instance built as an individual node - pos/
## rot/scale in world_tree.json are already absolute world values (not
## relative to parent_id - verified: a nested instance's position stays
## close to its instance-parent's position regardless of how different
## their own "rotation" values are, which wouldn't hold if rotation were
## meant to compose through the hierarchy), so this needs no parent
## transform folded in - identical math whether the result ends up in a
## MultiMesh array or a Node3D.transform.
func _compute_instance_transform(pos_arr: Array, rot: float, scale: float) -> Transform3D:
	var position := Vector3(pos_arr[0], pos_arr[1], -pos_arr[2])
	var scale_vec := Vector3(scale, scale, scale)
	var xform := Transform3D().scaled(scale_vec)
	xform = xform.rotated(Vector3.UP, -rot)
	xform.origin = position
	return xform

## Loads `file_path` (once per unique path via `cache`, shared across both
## the main per-file MultiMesh loop and the special-instance pass) and
## extracts its renderable parts as {name, mesh, internal_transform,
## material} dicts.
func _load_mesh_parts(file_path: String, cache: Dictionary) -> Array:
	if cache.has(file_path):
		return cache[file_path]

	var parts: Array = []
	var res_path: String = "res://" + file_path
	if not ResourceLoader.exists(res_path):
		printerr("Файл модели не найден: ", res_path)
		cache[file_path] = parts
		return parts

	var model_scene := load(res_path) as PackedScene
	if not model_scene:
		cache[file_path] = parts
		return parts

	var dummy_root := model_scene.instantiate()
	for mesh_instance in get_all_mesh_instances(dummy_root):
		var mesh: Mesh = mesh_instance.mesh
		if not mesh:
			continue

		var internal_transform := Transform3D.IDENTITY
		var current_node: Node = mesh_instance
		while current_node and current_node is Node3D:
			internal_transform = current_node.transform * internal_transform
			if current_node == dummy_root:
				break
			current_node = current_node.get_parent()

		var material: Material = null
		if mesh_instance.material_override:
			material = mesh_instance.material_override
		elif mesh_instance.get_surface_override_material(0):
			material = mesh_instance.get_surface_override_material(0)

		parts.append({
			"name": mesh_instance.name,
			"mesh": mesh,
			"internal_transform": internal_transform,
			"material": material,
		})
	dummy_root.queue_free()

	cache[file_path] = parts
	return parts

func get_all_mesh_instances(node: Node) -> Array[MeshInstance3D]:
	var result: Array[MeshInstance3D] = []
	if node is MeshInstance3D:
		result.append(node)
	for child in node.get_children():
		result.append_array(get_all_mesh_instances(child))
	return result
