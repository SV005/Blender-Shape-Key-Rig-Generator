# --- START OF FILE New Shape Key Generator v1.3.5 ---

import bpy
import math
import mathutils
from bpy.props import (
    StringProperty,
    PointerProperty,
    CollectionProperty,
    BoolProperty,
    FloatProperty,
)
from bpy.types import (
    PropertyGroup,
    UIList,
    Operator,
    Panel,
    Scene,
)
from bpy.app.handlers import persistent

bl_info = {
    "name": "Shape Key Snapping Rig Generator (+Basis/Perimeter)",
    "author": "Assistant (Based on User Scripts)",
    "version": (1, 3, 5),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Tool Tab",
    "description": "Creates a controller rig that snaps to points representing shape keys (plus a Basis point), activating one key at a time. Boundary includes spokes and perimeter.",
    "warning": "Uses application handlers for snapping. Ensure cleanup.",
    "doc_url": "",
    "category": "Rigging",
}

# --- Constants ---
METADATA_TAG = "skc_snap_driver_tag"
DRIVEN_KEYS_PROP_NAME = f"{METADATA_TAG}_driven_keys"
HANDLER_TAG = "skc_snap_handler_tag"
RADIUS_PROP = "skc_radius"
NUM_SNAP_POINTS_PROP = "skc_num_snap_points"


# --- Snapping Handler ---
active_snap_handlers = {}

def get_boundary_vertex_positions(radius, num_snap_points):
    """Calculates the target Y, Z coordinates for ALL snap points (including Basis at origin)."""
    if num_snap_points <= 0:
        return []
    positions = [(0.0, 0.0)] # Always include the Basis point at the origin (Y=0, Z=0)
    num_shape_key_points = num_snap_points - 1
    if num_shape_key_points > 0:
        angle_step = 2 * math.pi / num_shape_key_points
        start_angle = 0 # Start at the top (positive Z axis)
        for i in range(num_shape_key_points):
            angle = start_angle + i * angle_step
            # Correct calculation: sin for Y, cos for Z if 0 degrees is +Z
            target_y = radius * math.sin(angle)
            target_z = radius * math.cos(angle)
            positions.append((target_y, target_z))
    return positions

@persistent
def snap_controller_to_boundary_handler(scene):
    """Application handler to snap controllers to their closest boundary point (including Basis)."""
    controllers_to_process = []
    # Check all objects in the scene efficiently
    for obj in scene.objects:
        # Check if the object is tagged and actively tracked by our handlers
        if obj.get(HANDLER_TAG) and obj.name in active_snap_handlers:
            # Check if it's parented correctly (optional, but good sanity check)
             if obj.parent and obj.parent.name == f"{obj.name}_Boundary":
                  controllers_to_process.append(obj)

    if not controllers_to_process:
        return # No relevant controllers found

    for controller in controllers_to_process:
        radius = controller.get(RADIUS_PROP)
        num_snap_points = controller.get(NUM_SNAP_POINTS_PROP)

        # Validate necessary custom properties
        if radius is None or num_snap_points is None or num_snap_points <= 0:
            continue # Skip if properties are missing or invalid

        current_loc = controller.location.copy()
        target_positions = get_boundary_vertex_positions(radius, num_snap_points)

        if not target_positions:
            continue # Skip if no target positions calculated

        min_dist_sq = float('inf')
        closest_y = 0.0
        closest_z = 0.0

        # Find the closest target position (Y, Z only)
        for target_y, target_z in target_positions:
            dist_sq = (current_loc.y - target_y)**2 + (current_loc.z - target_z)**2
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                closest_y = target_y
                closest_z = target_z

        # Target snapped location (X is always 0 in local space)
        snapped_location = mathutils.Vector((0.0, closest_y, closest_z))

        # Check if the controller is already at the snapped location (within tolerance)
        needs_update = not (
            math.isclose(current_loc.x, snapped_location.x, abs_tol=1e-5) and
            math.isclose(current_loc.y, snapped_location.y, abs_tol=1e-5) and
            math.isclose(current_loc.z, snapped_location.z, abs_tol=1e-5)
        )

        # Update location only if necessary to avoid redundant updates
        if needs_update:
            controller.location = snapped_location


def register_snap_handler(controller):
    """Registers the snapping handler for a specific controller."""
    if not controller:
        return

    # Register if not already tracked OR if the global handler isn't active
    if controller.name not in active_snap_handlers or snap_controller_to_boundary_handler not in bpy.app.handlers.depsgraph_update_post:
        # Add the global handler if it's not already present
        if snap_controller_to_boundary_handler not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(snap_controller_to_boundary_handler)
        # Track this controller specifically
        active_snap_handlers[controller.name] = snap_controller_to_boundary_handler
        controller[HANDLER_TAG] = True # Add custom property tag
        print(f"Registered snap handler for controller '{controller.name}'.")


def unregister_snap_handler(controller_or_name):
    """Unregisters the snapping handler related to a specific controller."""
    controller_name = controller_or_name if isinstance(controller_or_name, str) else controller_or_name.name
    controller = bpy.data.objects.get(controller_name)

    # Stop tracking this specific controller
    if controller_name in active_snap_handlers:
        del active_snap_handlers[controller_name]
        print(f"Stopped active handler tracking for controller '{controller_name}'.")

    # Clean up custom properties from the controller object if it exists
    if controller:
        props_to_remove = [HANDLER_TAG, RADIUS_PROP, NUM_SNAP_POINTS_PROP]
        for prop in props_to_remove:
            if prop in controller:
                try:
                    del controller[prop]
                except Exception: # Ignore potential errors during cleanup
                    pass

    # If no controllers are being tracked, remove the global handler
    if not active_snap_handlers and snap_controller_to_boundary_handler in bpy.app.handlers.depsgraph_update_post:
        try:
            bpy.app.handlers.depsgraph_update_post.remove(snap_controller_to_boundary_handler)
            print("Removed global snap handler as no controllers are active.")
        except ValueError:
            pass # Handler might have already been removed
        except Exception as e:
            print(f"Error removing global handler: {e}")


# --- Driver Function ---
# Ensure this function is available in the driver namespace

def get_snapped_shape_key_influence(cont_y, cont_z, sk_index, num_shape_keys, radius, tolerance):
    """
    Driver function: Returns 1.0 if the controller is snapped to this specific
    shape key's boundary point, 0.0 otherwise (including if snapped to Basis).

    Args:
        cont_y (float): Controller's current local Y location.
        cont_z (float): Controller's current local Z location.
        sk_index (int): The index (0-based) of the shape key this driver belongs to
                         within the list of *controlled* shape keys.
        num_shape_keys (int): The total number of shape keys being controlled (excluding Basis).
        radius (float): The radius of the boundary circle.
        tolerance (float): The tolerance for matching coordinates.
    """
    # Check if controller is at the Basis point (origin)
    is_at_basis = math.isclose(cont_y, 0.0, abs_tol=tolerance) and math.isclose(cont_z, 0.0, abs_tol=tolerance)
    if is_at_basis:
        return 0.0 # Basis active, this shape key should be 0

    if num_shape_keys <= 0:
        return 0.0 # No shape keys to compare against

    # Calculate the target Y, Z for *this* specific shape key index
    angle_step = 2 * math.pi / num_shape_keys
    # start_angle = 0 corresponds to +Z axis (cos=1, sin=0)
    target_angle = 0 + sk_index * angle_step # Angle for this shape key's point
    target_y = radius * math.sin(target_angle)
    target_z = radius * math.cos(target_angle)

    # Check if the controller's position matches this shape key's target position
    y_matches = math.isclose(cont_y, target_y, abs_tol=tolerance)
    z_matches = math.isclose(cont_z, target_z, abs_tol=tolerance)

    return 1.0 if (y_matches and z_matches) else 0.0

bpy.app.driver_namespace['sk_snap_influence'] = get_snapped_shape_key_influence

# --- Property Group ---
class ShapeKeySettingItem(PropertyGroup):
    name: StringProperty(name="Shape Key Name")
    use: BoolProperty(name="Use", description="Include this shape key in the control rig", default=False)


# --- UI List ---
class OBJECT_UL_shape_key_settings_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        # data is the Scene
        # item is the ShapeKeySettingItem
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "use", text="")
            row.label(text=item.name)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.prop(item, "use", text="")


# --- Helper Functions ---
def remove_shape_key_drivers(target_mesh):
    """Removes drivers previously added by this addon from the target mesh's shape keys."""
    if not target_mesh or not target_mesh.data or not hasattr(target_mesh.data, 'shape_keys') or not target_mesh.data.shape_keys:
        return

    mesh_data = target_mesh.data
    # Check if the tracking property exists
    if DRIVEN_KEYS_PROP_NAME not in mesh_data:
        return # Nothing to remove if the property isn't there

    # Get the dictionary of driven keys (handle ID property type)
    driven_keys_dict = mesh_data.get(DRIVEN_KEYS_PROP_NAME, {})
    if hasattr(driven_keys_dict, 'to_dict'): # Convert from IDProp if necessary
        driven_keys_dict = driven_keys_dict.to_dict()

    if not isinstance(driven_keys_dict, dict) or not driven_keys_dict:
        # If it's somehow not a dict or empty, remove the property and exit
        if DRIVEN_KEYS_PROP_NAME in mesh_data:
             try: del mesh_data[DRIVEN_KEYS_PROP_NAME]
             except: pass
        return

    print(f"Attempting to remove drivers for keys: {list(driven_keys_dict.keys())}")
    shape_keys_block = target_mesh.data.shape_keys
    keys_to_process = list(shape_keys_block.key_blocks) # Make a copy to iterate safely
    successfully_removed_keys = []

    # Iterate through all shape keys on the mesh
    for shape_key in keys_to_process:
        # If this shape key's name is in our tracked dictionary
        if shape_key.name in driven_keys_dict:
            try:
                # Check if it actually has animation data and a driver on 'value'
                if shape_key.animation_data and shape_key.animation_data.drivers and shape_key.animation_data.drivers.find('value'):
                     # Attempt to remove the driver
                     if shape_key.driver_remove('value'):
                         print(f"  Removed driver from shape key '{shape_key.name}'.")
                     else:
                         # This might happen if the driver was already gone or unremovable
                         print(f"  Note: Driver removal reported failure for '{shape_key.name}'.")
                # Mark as processed even if no driver was found/removed, to clean up dict
                successfully_removed_keys.append(shape_key.name)
            except Exception as e:
                # Log error but still mark for removal from dict
                print(f"  Error removing driver from '{shape_key.name}': {e}")
                successfully_removed_keys.append(shape_key.name)

    # Update the tracking property dictionary
    if successfully_removed_keys:
        # Get the current dictionary again (might have changed if run concurrently?)
        current_dict = mesh_data.get(DRIVEN_KEYS_PROP_NAME, {})
        if hasattr(current_dict, 'to_dict'):
            current_dict = current_dict.to_dict()

        if isinstance(current_dict, dict):
            changed = False
            # Remove the successfully processed keys from the dict
            for key_name in successfully_removed_keys:
                if key_name in current_dict:
                    del current_dict[key_name]
                    changed = True

            if changed:
                 # If the dictionary is now empty, remove the property entirely
                 if not current_dict:
                     if DRIVEN_KEYS_PROP_NAME in mesh_data:
                         try: del mesh_data[DRIVEN_KEYS_PROP_NAME]
                         except: pass
                         print(f"Removed empty '{DRIVEN_KEYS_PROP_NAME}'.")
                 # Otherwise, update the property with the modified dictionary
                 else:
                     mesh_data[DRIVEN_KEYS_PROP_NAME] = current_dict
                     print(f"Updated '{DRIVEN_KEYS_PROP_NAME}'.")


def remove_existing_controller_system(controller_name):
    """Removes the controller object, its boundary parent, and unregisters related handlers."""
    print(f"Attempting to remove existing system for controller '{controller_name}'...")
    controller = bpy.data.objects.get(controller_name)
    boundary_name = f"{controller_name}_Boundary"
    boundary = bpy.data.objects.get(boundary_name)

    # Always try to unregister the handler first, using name if object doesn't exist
    unregister_snap_handler(controller if controller else controller_name)

    # Remove the boundary object and its potential children (the controller)
    if boundary:
        try:
            # Unparent children explicitly first (especially the controller)
            children_to_remove = [child for child in boundary.children if child.name == controller_name]
            for child in children_to_remove:
                try:
                    # Remove child object if it still exists
                    if child.name in bpy.data.objects:
                        bpy.data.objects.remove(child, do_unlink=True)
                except ReferenceError:
                    pass # Object already gone
                except Exception as e:
                    print(f"  Error removing child object '{child.name}': {e}")

            # Now remove the boundary parent object itself
            if boundary.name in bpy.data.objects:
                bpy.data.objects.remove(boundary, do_unlink=True)
                print(f"Removed boundary '{boundary.name}'.")
        except ReferenceError:
            # This can happen if the object was deleted manually between get() and remove()
            print(f"Boundary '{boundary.name}' reference lost during cleanup (likely already removed).")
            pass
        except AttributeError:
             # Safety check if 'boundary' somehow became invalid
             if boundary:
                 print(f"Warning: Attribute error processing children of potential boundary '{boundary.name}'. It might be invalid.")
             pass
        except Exception as e:
            print(f"Error during boundary/children removal for '{boundary.name}': {e}")

    # Final check to remove the controller if it somehow wasn't parented or wasn't removed
    if controller and controller.name in bpy.data.objects:
         try:
             # Ensure it's unparented before removal
             if controller.parent:
                 controller.parent = None
             bpy.data.objects.remove(controller, do_unlink=True)
             print(f"Removed controller object '{controller_name}'.")
         except ReferenceError:
             pass # Already gone
         except Exception as e:
              print(f"Error during final removal of controller '{controller_name}': {e}")


def create_spoked_boundary(name, num_shape_keys, radius):
    """
    Creates a boundary visualization mesh object with spokes from origin (Basis point)
    to each shape key point, AND connects the outer shape key points
    to form a closed perimeter polygon.
    """
    # Total points: Basis (at origin) + number of shape keys
    num_corners = num_shape_keys + 1
    if num_corners <= 1: # Need at least Basis + 1 key for a line, Basis + 2 for polygon
        print("Warning: Not enough points for a meaningful boundary (need Basis + >=1 key).")
        return None

    verts = [(0, 0, 0)] # Vertex 0: Basis point at origin
    edges = []

    if num_shape_keys > 0:
        angle_step = 2 * math.pi / num_shape_keys
        start_angle = 0 # Start at +Z axis

        # Add vertices for each shape key point and edges for spokes (Origin -> Point)
        for i in range(num_shape_keys):
            angle = start_angle + i * angle_step
            y = radius * math.sin(angle)
            z = radius * math.cos(angle)
            verts.append((0, y, z)) # Add vertex (index i+1)
            edges.append((0, i + 1)) # Add spoke edge (Basis to this point)

        # Add edges for the perimeter connecting the outer shape key points
        if num_shape_keys >= 2: # Need at least 2 points for a perimeter line segment
            for i in range(num_shape_keys):
                current_vertex_idx = i + 1
                # Connect to the *next* shape key point, wrapping around for the last one
                next_vertex_idx = ((i + 1) % num_shape_keys) + 1
                edges.append((current_vertex_idx, next_vertex_idx))

    # Create mesh and object
    mesh = bpy.data.meshes.new(name=f"{name}_Mesh")
    mesh.from_pydata(verts, edges, []) # No faces needed
    mesh.update()

    boundary_obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(boundary_obj)

    # Set display properties
    boundary_obj.display_type = 'WIRE' # Show as wireframe
    boundary_obj.hide_render = True    # Don't render it

    print(f"Created combined boundary object '{name}' ({num_corners} snap points: Basis + {num_shape_keys} keys, with spokes and perimeter).")
    return boundary_obj


def add_snapping_shape_key_drivers(controller_name, target_mesh, selected_keys_list, radius, tolerance):
    """Adds drivers to the selected shape keys on the target mesh."""
    controller = bpy.data.objects.get(controller_name)
    if not controller or not target_mesh or not target_mesh.data.shape_keys:
        print("Error: Cannot add drivers. Invalid controller, target mesh, or shape keys missing.")
        return False

    mesh_data = target_mesh.data
    num_shape_keys = len(selected_keys_list)
    if num_shape_keys == 0:
        print("Error: No shape keys selected for drivers.")
        return False

    print(f"Adding snapping drivers to {num_shape_keys} selected shape keys (plus Basis control)...")

    # Ensure driver function is registered (should be, but double-check)
    if 'sk_snap_influence' not in bpy.app.driver_namespace:
         print("Error: Driver function 'sk_snap_influence' not found in namespace!")
         # Try re-registering it - this might indicate an issue elsewhere
         try:
             bpy.app.driver_namespace['sk_snap_influence'] = get_snapped_shape_key_influence
             print("Re-registered driver function 'sk_snap_influence'.")
         except Exception as e:
             print(f"Failed to re-register driver function: {e}")
             return False

    # Initialize or get the tracking property on the mesh data
    if DRIVEN_KEYS_PROP_NAME not in mesh_data:
        mesh_data[DRIVEN_KEYS_PROP_NAME] = {}
    driven_keys_dict = mesh_data.get(DRIVEN_KEYS_PROP_NAME, {})
    # Convert ID prop dict if needed
    if hasattr(driven_keys_dict, 'to_dict'):
        driven_keys_dict = driven_keys_dict.to_dict()
    # Ensure it's actually a dictionary
    if not isinstance(driven_keys_dict, dict):
        print(f"Error: Mesh property '{DRIVEN_KEYS_PROP_NAME}' is not a dictionary. Resetting.")
        mesh_data[DRIVEN_KEYS_PROP_NAME] = {}
        driven_keys_dict = mesh_data[DRIVEN_KEYS_PROP_NAME]

    success = True
    keys_added_to_dict = []

    # Loop through the list of selected shape key settings (which maintain order)
    for i, sk_setting_item in enumerate(selected_keys_list):
        shape_key = target_mesh.data.shape_keys.key_blocks.get(sk_setting_item.name)
        if not shape_key:
            print(f"  Warning: Shape key '{sk_setting_item.name}' not found on mesh. Skipping.")
            continue

        try:
            # Remove any existing driver first
            shape_key.driver_remove('value')
            # Add a new driver
            driver = shape_key.driver_add('value').driver
            driver.type = 'SCRIPTED'

            # Add variable for Controller's Y Location
            var_y = driver.variables.new()
            var_y.name = 'var_y'
            var_y.type = 'TRANSFORMS'
            target_y = var_y.targets[0]
            target_y.id = controller # Link to the controller object
            target_y.transform_type = 'LOC_Y'
            # --- CHANGE THIS LINE ---
            target_y.transform_space = 'LOCAL_SPACE' # Use local space relative to parent boundary

            # Add variable for Controller's Z Location
            var_z = driver.variables.new()
            var_z.name = 'var_z'
            var_z.type = 'TRANSFORMS'
            target_z = var_z.targets[0]
            target_z.id = controller
            target_z.transform_type = 'LOC_Z'
            # --- CHANGE THIS LINE ---
            target_z.transform_space = 'LOCAL_SPACE' # Use local space relative to parent boundary

            # Set the driver expression using the namespace function
            # Pass the index 'i' for this specific key, total count, radius, tolerance
            driver.expression = f"sk_snap_influence(var_y, var_z, {i}, {num_shape_keys}, {radius:.6f}, {tolerance:.6f})"

            # Mark this key as driven in our tracking dictionary
            driven_keys_dict[shape_key.name] = True
            keys_added_to_dict.append(shape_key.name)

        except Exception as e:
            print(f"  Error adding driver to '{shape_key.name}': {e}")
            success = False
            # If adding failed, remove it from the dictionary if it was added
            if shape_key.name in driven_keys_dict:
                del driven_keys_dict[shape_key.name]

    # Update the mesh's custom property with the final dictionary of driven keys
    if keys_added_to_dict: # Only update if we actually added keys
        mesh_data[DRIVEN_KEYS_PROP_NAME] = dict(driven_keys_dict) # Ensure it's a plain dict
        print(f"Finished adding drivers. Tracking property '{DRIVEN_KEYS_PROP_NAME}' updated.")

    return success


def create_controller_with_boundary(controller_name, target_mesh, selected_keys_list, boundary_radius, controller_size, driver_tolerance):
    """Main function to create the controller, boundary, set up parenting, and add drivers."""
    print("-" * 30)
    print(f"Creating snapping controller system '{controller_name}' for '{target_mesh.name}'")

    # 1. Clean up any previous drivers/systems associated with this mesh/controller name
    remove_shape_key_drivers(target_mesh) # Remove drivers based on mesh property
    remove_existing_controller_system(controller_name) # Remove objects based on name

    num_shape_keys = len(selected_keys_list)
    num_snap_points = num_shape_keys + 1 # Total points including Basis

    if num_shape_keys == 0:
        print("Error: No shape keys selected. Cannot create rig.")
        return False

    # 2. Create the boundary visualization object
    boundary_obj_name = f"{controller_name}_Boundary"
    boundary_obj = create_spoked_boundary(boundary_obj_name, num_shape_keys, boundary_radius)
    if not boundary_obj:
        print("Error: Failed to create boundary object.")
        return False

    # Position and orient the boundary to match the target mesh
    boundary_obj.location = target_mesh.location
    boundary_obj.rotation_euler = target_mesh.rotation_euler
    # --- Optional: Force an update here? Might help ensure boundary_obj.matrix_world is correct ---
    # bpy.context.view_layer.update() # Uncomment if issues persist

    # 3. Create the controller object (Empty Sphere)
    controller = None
    try:
        # Create empty at the boundary's location/rotation initially
        bpy.ops.object.empty_add(type='SPHERE', location=boundary_obj.location, rotation=boundary_obj.rotation_euler)
        controller = bpy.context.object # Newly created empty is active
        controller.name = controller_name
        controller.empty_display_size = controller_size
        controller.use_fake_user = True # Keep it even if unused
        print(f"Created controller empty '{controller.name}'.")
    except Exception as e:
        print(f"Error creating controller empty: {e}")
        # Clean up the boundary if controller creation failed
        if boundary_obj and boundary_obj.name in bpy.data.objects:
            print(f"  Cleaning up boundary '{boundary_obj.name}'.")
            try:
                bpy.data.objects.remove(boundary_obj, do_unlink=True)
            except Exception as remove_e:
                print(f"    Error during cleanup: {remove_e}")
        return False

    # --- REVISED STEP 4: PARENTING ---
    print(f"Parenting '{controller.name}' to '{boundary_obj.name}'...")
    # Simply parent the object. Blender will calculate the inverse matrix.
    controller.parent = boundary_obj

    # Reset controller's LOCAL transforms AFTER parenting.
    # This places the controller visually at the parent's origin in local space.
    controller.location = (0, 0, 0)
    controller.rotation_euler = (0, 0, 0)
    controller.scale = (1, 1, 1)
    print(f"Reset local transforms for '{controller.name}'. Controller should now be at boundary origin.")
    # --- END REVISED STEP 4 ---


    # Store radius and snap point count on the controller for the handler
    controller[RADIUS_PROP] = boundary_radius
    controller[NUM_SNAP_POINTS_PROP] = num_snap_points

    # 5. Reset initial values of shape keys being controlled BEFORE adding drivers
    print("Resetting initial values for selected shape keys...")
    if target_mesh.data.shape_keys:
        for sk_setting_item in selected_keys_list:
            shape_key = target_mesh.data.shape_keys.key_blocks.get(sk_setting_item.name)
            if shape_key:
                try:
                    # Remove any lingering driver just in case
                    shape_key.driver_remove('value')
                    # Set value to 0
                    shape_key.value = 0.0
                except Exception as e:
                     # Log warning but continue
                     print(f"  Warning: Could not reset value/remove driver for '{shape_key.name}': {e}")
                     pass # Don't stop the whole process for this

    # 6. Add drivers to the selected shape keys (Ensure this uses LOCAL_SPACE as per previous fix)
    drivers_added_ok = add_snapping_shape_key_drivers(
        controller_name=controller.name,
        target_mesh=target_mesh,
        selected_keys_list=selected_keys_list,
        radius=boundary_radius,
        tolerance=driver_tolerance
    )

    if not drivers_added_ok:
        print("Error: Failed to add drivers. Cleaning up created objects.")
        remove_existing_controller_system(controller_name) # Clean up controller and boundary
        return False

    # 7. Register the snapping handler for the new controller
    register_snap_handler(controller)

    # 8. Select the controller and make it active
    bpy.ops.object.select_all(action='DESELECT')
    if controller and controller.name in bpy.context.view_layer.objects:
        controller.select_set(True)
        bpy.context.view_layer.objects.active = controller

    print(f"Successfully created snapping controller system '{controller_name}'.")
    print("-" * 30)
    return True


# --- Operators ---
class OBJECT_OT_create_snap_controller_system(Operator):
    """Operator to generate the controller system based on UI settings."""
    bl_idname = "object.skc_create_snap_controller_system"
    bl_label = "Create Snapping Controller (+Basis/Perim)"
    bl_description = "Generate the shape key snapping controller rig (includes Basis point, spokes, and perimeter visualization)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        scene = context.scene
        # Check if a valid mesh with shape keys is selected and at least one key is chosen
        return (
            scene.skc_target_mesh and
            scene.skc_target_mesh.type == 'MESH' and
            scene.skc_target_mesh.data and
            hasattr(scene.skc_target_mesh.data, 'shape_keys') and
            scene.skc_target_mesh.data.shape_keys and
            any(item.use for item in scene.skc_shape_key_settings) # Check if any checkbox is ticked
        )

    def execute(self, context):
        scene = context.scene
        target_mesh = scene.skc_target_mesh

        # Double check conditions from poll (should be guaranteed, but good practice)
        if not target_mesh or not target_mesh.data or not hasattr(target_mesh.data, 'shape_keys') or not target_mesh.data.shape_keys:
            self.report({'ERROR'}, "Invalid target mesh or mesh has no shape keys.")
            return {'CANCELLED'}

        # Get the list of shape key names where the 'use' checkbox is ticked
        selected_keys_for_rig = [item for item in scene.skc_shape_key_settings if item.use]

        if not selected_keys_for_rig:
            self.report({'ERROR'}, "No shape keys selected in the list.")
            return {'CANCELLED'}

        print(f"Selected keys for rig generation: {[item.name for item in selected_keys_for_rig]}")

        # --- Dynamic Radius/Size Calculation (Attempt) ---
        boundary_radius = 0.75 # Default radius
        controller_size = 0.075 # Default size
        try:
            # Calculate world space bounding box corners
            world_bbox_corners = [target_mesh.matrix_world @ mathutils.Vector(corner) for corner in target_mesh.bound_box]
            if world_bbox_corners:
                # Find min/max in world Y and Z (plane of the controller)
                min_y = min(v.y for v in world_bbox_corners)
                max_y = max(v.y for v in world_bbox_corners)
                min_z = min(v.z for v in world_bbox_corners)
                max_z = max(v.z for v in world_bbox_corners)
                world_dim_y = max_y - min_y
                world_dim_z = max_z - min_z

                # Use average YZ dimension or max overall dimension as base size
                avg_yz_dim = (world_dim_y + world_dim_z) / 2.0
                # Fallback to max dimension if YZ is tiny or negative
                max_overall_dim = max(target_mesh.dimensions) if max(target_mesh.dimensions) > 0.001 else 1.0
                base_dim = avg_yz_dim if avg_yz_dim > 0.01 else max_overall_dim

                # Set radius relative to base dimension
                boundary_radius = base_dim * 0.75
                # Set controller size relative to radius/base, with a minimum size
                controller_size = max(boundary_radius * 0.1, max_overall_dim * 0.05, 0.05) # Ensure minimum size
        except Exception as e:
            print(f"Warning: Bounding box calculation failed ({e}). Using default radius/size.")

        print(f"Calculated Parameters: Radius={boundary_radius:.3f}, Controller Size={controller_size:.3f}, Driver Tolerance={scene.skc_driver_tolerance:.5f}")

        # --- Call the main creation function ---
        success = create_controller_with_boundary(
            controller_name=scene.skc_controller_name,
            target_mesh=target_mesh,
            selected_keys_list=selected_keys_for_rig, # Pass the list of PropertyGroup items
            boundary_radius=boundary_radius,
            controller_size=controller_size,
            driver_tolerance=scene.skc_driver_tolerance
        )

        if success:
            self.report({'INFO'}, f"Controller system '{scene.skc_controller_name}' created successfully.")
        else:
            # If creation failed, report error and ensure cleanup happened
            self.report({'ERROR'}, "Controller system creation failed. Check Blender Console for details.")
            # Attempt cleanup again just in case something was partially created
            remove_existing_controller_system(scene.skc_controller_name)
            remove_shape_key_drivers(target_mesh) # Also try to remove any partial drivers

        return {'FINISHED'} if success else {'CANCELLED'}


# --- Panel ---
class OBJECT_PT_snap_controller_panel(Panel):
    """UI Panel in the 3D View Sidebar."""
    bl_label = "Shape Key Snapping Controller (+Basis/Perim)"
    bl_idname = "OBJECT_PT_skc_snap_controller_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Tool' # Appears in the 'Tool' tab of the N-Panel

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # --- Settings Box ---
        settings_box = layout.box()
        settings_box.label(text="Settings", icon='SETTINGS')
        col = settings_box.column(align=True)
        col.prop(scene, "skc_controller_name") # Controller Name field
        col.prop(scene, "skc_target_mesh")     # Target Mesh selector
        col.prop(scene, "skc_driver_tolerance") # Driver tolerance slider

        # --- Shape Key Selection Box ---
        keys_box = layout.box()
        row = keys_box.row()
        row.label(text="Select Shape Keys to Control", icon='SHAPEKEY_DATA')

        target_mesh = scene.skc_target_mesh
        # Check conditions to draw the list
        can_draw_list = (
            target_mesh and
            target_mesh.data and
            hasattr(target_mesh.data, 'shape_keys') and
            target_mesh.data.shape_keys and
            target_mesh.data.shape_keys.key_blocks # Check key_blocks exist
        )

        if not target_mesh:
            keys_box.label(text="1. Select Target Mesh Above", icon='INFO')
        elif not target_mesh.data or not hasattr(target_mesh.data, 'shape_keys') or not target_mesh.data.shape_keys:
            keys_box.label(text="Selected mesh has no Shape Key data block", icon='ERROR')
        elif not target_mesh.data.shape_keys.key_blocks:
             # This state might occur if the data block exists but is empty
            keys_box.label(text="Mesh has no actual Shape Keys (only Basis?)", icon='INFO')
        else:
            # Draw the UI List
            keys_box.template_list(
                "OBJECT_UL_shape_key_settings_list", # UIList class name
                "",                                  # List ID (optional)
                scene,                               # Data source (scene)
                "skc_shape_key_settings",            # Collection property name on data source
                scene,                               # Active index property data source
                "skc_active_shape_key_setting_index" # Active index property name
            )
            # Display count of selected keys
            num_selected = sum(1 for item in scene.skc_shape_key_settings if item.use)
            keys_box.label(text=f"{num_selected} key(s) selected (+ Basis point)")

        layout.separator() # Spacer

        # --- Action Button ---
        row = layout.row()
        # Enable button only if poll() conditions are met
        row.enabled = OBJECT_OT_create_snap_controller_system.poll(context)
        row.scale_y = 1.5 # Make button larger
        row.operator(OBJECT_OT_create_snap_controller_system.bl_idname) # Add the button


# --- Registration ---

def poll_mesh_object(self, object):
    """Poll function for the Target Mesh PointerProperty."""
    return object and object.type == 'MESH'

def update_target_mesh(self, context):
    """Callback when the Target Mesh PointerProperty changes."""
    print("Target mesh updated. Repopulating shape key list.")
    # 'self' here refers to the Scene
    self.skc_shape_key_settings.clear() # Clear the existing list items
    obj = self.skc_target_mesh

    if obj and obj.data and hasattr(obj.data, 'shape_keys') and obj.data.shape_keys and obj.data.shape_keys.key_blocks:
        count = 0
        # Iterate through actual shape keys on the mesh
        for sk in obj.data.shape_keys.key_blocks:
            if sk.name == 'Basis':
                continue # Skip the Basis key
            # Add a new item to the collection property for each non-Basis key
            item = self.skc_shape_key_settings.add()
            item.name = sk.name # Store the shape key name
            item.use = False    # Default to not used
            count += 1
        # Correctly indented print statement after the loop
        print(f"Populated list with {count} shape key(s).")


# List of classes to register/unregister
classes = (
    ShapeKeySettingItem,
    OBJECT_UL_shape_key_settings_list,
    OBJECT_OT_create_snap_controller_system,
    OBJECT_PT_snap_controller_panel,
)

def register():
    print("Registering SK Snapping Controller (+Basis/Perimeter)...")

    # Ensure driver function is in namespace (idempotent)
    try:
        if 'sk_snap_influence' not in bpy.app.driver_namespace:
            bpy.app.driver_namespace['sk_snap_influence'] = get_snapped_shape_key_influence
            print("Registered driver function 'sk_snap_influence'.")
        # Clean up old function name if present
        if 'sk_influence' in bpy.app.driver_namespace:
            del bpy.app.driver_namespace['sk_influence']
    except Exception as e:
        print(f"Error managing driver function registration: {e}")

    # Register classes
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
             pass # Class already registered (e.g., during development reloads)
        except Exception as e:
            print(f"Error registering class {cls.__name__}: {e}")

    # Register Scene properties
    Scene.skc_controller_name = StringProperty(
        name="Controller Name",
        default="SK_Snap_Controller",
        description="Name for the generated controller object"
    )
    Scene.skc_target_mesh = PointerProperty(
        type=bpy.types.Object,
        name="Target Mesh",
        poll=poll_mesh_object,
        update=update_target_mesh, # Function to call when changed
        description="The mesh object containing the shape keys to control"
    )
    Scene.skc_shape_key_settings = CollectionProperty(
        type=ShapeKeySettingItem,
        name="Shape Key Settings",
        description="List of available shape keys on the target mesh"
    )
    Scene.skc_active_shape_key_setting_index = bpy.props.IntProperty(
        name="Active SK Index",
        description="Internal index for the UI list selection"
    )
    Scene.skc_driver_tolerance = FloatProperty(
        name="Snap Tolerance",
        default=0.001,
        min=0.00001, # Very small minimum
        max=0.1,     # Reasonable maximum
        step=1,      # Step size (use precision for finer control)
        precision=5, # Number of decimal places
        description="How close the controller must be to a point to activate the shape key driver"
    )

    # Clean up any potentially lingering handlers from previous sessions/crashes
    try:
        handler_removed = False
        while snap_controller_to_boundary_handler in bpy.app.handlers.depsgraph_update_post:
            print("Note: Found leftover snap handler during registration. Removing.")
            bpy.app.handlers.depsgraph_update_post.remove(snap_controller_to_boundary_handler)
            handler_removed = True
        # Clear the tracking dictionary as well
        active_snap_handlers.clear()
        if handler_removed:
             print("Leftover handler cleanup complete.")
    except Exception as e:
        print(f"Error during initial handler cleanup on registration: {e}")

    print("Registration complete.")


def unregister():
    print("Unregistering SK Snapping Controller (+Basis/Perimeter)...")

    # 1. Clean up active handlers and related controller properties
    try:
        # Get a list of names to avoid modifying dict while iterating
        controllers_to_cleanup_names = list(active_snap_handlers.keys())
        print(f"Cleaning up handlers for controllers: {controllers_to_cleanup_names}")
        for controller_name in controllers_to_cleanup_names:
            unregister_snap_handler(controller_name) # This removes from dict and cleans props

        # 2. Ensure the global handler function is removed if it exists
        removed_global = False
        # Use a loop in case it was somehow added multiple times
        while snap_controller_to_boundary_handler in bpy.app.handlers.depsgraph_update_post:
            try:
                bpy.app.handlers.depsgraph_update_post.remove(snap_controller_to_boundary_handler)
                removed_global = True
            except ValueError:
                break # Not found, loop should terminate
            except Exception as e:
                print(f"Error removing handler instance during unregister: {e}")
                break # Avoid infinite loop on persistent error
        if removed_global:
            print("Removed global snap handler function.")

        # 3. Clear the tracking dictionary (should be empty now, but good practice)
        active_snap_handlers.clear()

    except Exception as e:
        print(f"Error during handler cleanup on unregistration: {e}")

    # 4. Remove the driver function from the namespace
    if 'sk_snap_influence' in bpy.app.driver_namespace:
        try:
            del bpy.app.driver_namespace['sk_snap_influence']
            print("Unregistered driver function 'sk_snap_influence'.")
        except Exception as e:
            print(f"Error removing driver function: {e}")
    # Clean up old name too
    if 'sk_influence' in bpy.app.driver_namespace:
        try:
            del bpy.app.driver_namespace['sk_influence']
        except Exception:
            pass

    # 5. Delete Scene properties
    props_to_del = [
        "skc_controller_name",
        "skc_target_mesh",
        "skc_shape_key_settings",
        "skc_active_shape_key_setting_index",
        "skc_driver_tolerance"
    ]
    for prop in props_to_del:
        if hasattr(Scene, prop):
            try:
                delattr(Scene, prop)
            except Exception as e:
                print(f"Error deleting scene property '{prop}': {e}")

    # 6. Unregister classes in reverse order
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass # Class not registered
        except Exception as e:
            print(f"Error unregistering class {cls.__name__}: {e}")

    print("Unregistration complete.")


# Standard Blender addon entry point for testing/direct execution
if __name__ == "__main__":
    # Encapsulate unregister/register for clean testing
    try:
        print("\n--- Unregistering Addon (direct run) ---")
        unregister()
    except Exception as e:
        print(f"Error during unregister call in main block: {e}")
    finally:
        # Always try to register, even if unregister failed
        print("\n--- Registering Addon (direct run) ---")
        register()

# --- END OF FILE ---