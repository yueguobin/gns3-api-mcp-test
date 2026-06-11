# GNS3 MCP Tool Test Plan

**Total Tools**: 82  
**Test Plan Coverage**: 78 tools (Phase 1-12, Phase 13 supplements 4 missing tools)

## Test Strategy
- ✅ **Safety First**: Start with read-only operations, gradually progress to modify/delete operations
- 🔄 **Dependency Management**: Create infrastructure (projects) first, then test specific features
- 📝 **Verifiable**: Each test has clear execution steps and expected results

---

## Phase 1: Server Information Query (Read-only, Safe)

### 1.1 Server Version and Status
**Tools**: `server_version`, `server_statistics`

**Test Steps**:
1. Get GNS3 server version information
2. Get server statistics (compute nodes, project count, etc.)

**Expected Results**:
- Successfully return server version number
- Display current statistics: project count, node count, link count, etc.

---

## Phase 2: Compute Node and Device Management (Mainly Read-only)

### 2.1 Compute Node Query
**Tools**: `compute_list`, `compute_get`

**Test Steps**:
1. List all available compute nodes
2. Get detailed information for the "local" compute node

**Expected Results**:
- Display at least one compute node (usually local)
- Return compute node configuration: CPU, memory, etc.

### 2.2 Device Library Browsing
**Tools**: `appliance_list`, `appliance_get`

**Test Steps**:
1. List all available device templates
2. Select a common device (e.g., Cisco IOS router) and get detailed information

**Expected Results**:
- Display device list including routers, switches, firewalls, etc.
- Return selected device details: description, image requirements, etc.

### 2.3 Device Installation
**Tools**: `appliance_install`

**Test Steps**:
1. Select a device template and version
2. Execute device installation operation
3. Verify installation status

**Expected Results**:
- Create template from local appliance definition (前提是镜像文件已存在)
- If image files don't exist, return clear error message
- Return installation progress and status information

### 2.4 Image Management
**Tools**: `image_list`, `image_get`, `compute_images`

**Test Steps**:
1. List all installed images on the server
2. Get image list for QEMU emulator
3. Select an image and get detailed information

**Expected Results**:
- Display various image types (QEMU, Docker, IOU, etc.)
- Return image path, size, version, and other information

---

## Phase 3: Symbol and Template Management (Read-only)

### 3.1 Symbol System
**Tools**: `symbol_list`, `symbol_get`, `symbol_defaults`, `symbol_dimensions`

**Test Steps**:
1. List all available topology icons
2. Get detailed information for router symbols
3. View default symbol mapping for each node type
4. Get dimension information for specific symbols

**Expected Results**:
- Display symbols for routers, switches, hosts, etc.
- Return symbol SVG path and dimension information
- Provide symbol width and height data

### 3.2 Template Query
**Tools**: `template_list`, `template_get`

**Test Steps**:
1. List all created templates
2. Get detailed configuration for a commonly used template

**Expected Results**:
- Display project template list
- Return template configuration parameters (CPU, memory, adapters, etc.)

---

## Phase 4: Project Management (Create and Modify)

### 4.1 Project Creation and Basic Operations
**Tools**: `project_create`, `project_list`, `project_get`, `project_update`

**Test Steps**:
1. Create a test project "MCP_Test_Project"
2. List all projects and verify successful creation
3. Get detailed information for the new project
4. Update project name and description

**Expected Results**:
- Project successfully created, returns project UUID
- Project list includes newly created project
- Can modify project properties

### 4.2 Project Operations
**Tools**: `project_duplicate`, `project_load`, `project_open`

**Test Steps**:
1. Duplicate an existing project to create a new project
2. Load project from file path
3. Open a closed project
4. Verify project status changes

**Expected Results**:
- Project successfully duplicated, get new project ID
- Project successfully loaded from file
- Project status correctly transitions (closed→open)

### 4.3 Project Metadata
**Tools**: `project_readme_update`, `project_readme_get`, `project_stats`

**Test Steps**:
1. Add README.md description to test project
2. Get project statistics (node count, link count, drawing count, etc.)

**Expected Results**:
- README content successfully saved and read
- Statistics accurately reflect current project state

### 4.4 Project Locking Mechanism
**Tools**: `project_lock`, `project_unlock`, `project_locked`

**Test Steps**:
1. Lock test project
2. Check project lock status
3. Unlock project
4. Check lock status again

**Expected Results**:
- Cannot modify nodes and drawings when locked
- Lock status query returns correct results

---

## Phase 5: Node Creation and Management

### 5.1 Node Creation
**Tools**: `node_create`, `node_list`, `node_get`

**Test Steps**:
1. Create a VPCS node (PC1) in the test project
2. Create a QEMU virtual machine node (if available)
3. List all nodes and verify successful creation
4. Get detailed configuration for each node

**Expected Results**:
- Node successfully created, assigned unique UUID
- Node list displays newly created nodes
- Return node information: ports, console port, etc.

### 5.2 Node Property Modification
**Tools**: `node_update`, `node_duplicate`

**Test Steps**:
1. Modify node name (e.g., PC1 to Client_PC)
2. Duplicate a node
3. Verify both nodes have identical configuration but different positions

**Expected Results**:
- Node name successfully updated
- Duplicated node configuration matches source node

### 5.3 Node File Operations
**Tools**: `node_file_list`, `node_file_write`, `node_file_get`, `node_file_delete`

**Test Steps**:
1. List files in node directory
2. Create a test configuration file
3. Read file content to verify successful write
4. Delete test file

**Expected Results**:
- Can browse node file system
- File read/write operations work normally

### 5.4 Node Isolation and Link Management
**Tools**: `node_isolate`, `node_links`, `node_unisolate`

**Test Steps**:
1. Isolate a node (suspend all connections)
2. List all links for the node
3. Verify node cannot communicate with other nodes
4. Unisolate and verify connection recovery

**Expected Results**:
- Node successfully isolated, network connections interrupted
- Can view node's connection list
- Connections recover normally after unisolation

---

## Phase 6: Links and Network Topology

### 6.1 Create Network Connections
**Tools**: `link_create`, `link_list`, `link_get`

**Test Steps**:
1. Create an Ethernet link between two nodes
2. List all links and verify successful creation
3. Get detailed link information (ports, adapter numbers)

**Expected Results**:
- Link successfully created, displays connected nodes and ports
- Returns link UUID and type

### 6.2 Link Filtering and Traffic Control
**Tools**: `link_update`, `link_reset`

**Test Steps**:
1. Add delay filter to link (100ms delay, 10ms jitter)
2. Add packet loss filter (5% loss rate)
3. Reset link to clear all filters

**Expected Results**:
- Filters successfully applied to link
- Returns to default state after reset

---

## Phase 7: Node Console and Configuration

### 7.1 Console Connection
**Tools**: `node_console`

**Test Steps**:
1. Get console WebSocket URL for a VPCS node
2. Verify returned connection parameters (port, type)

**Expected Results**:
- Returns WebSocket connection URL
- Displays console type (telnet/ssh)

### 7.2 Device Command Execution
**Tools**: `device_command_run`, `device_config_send`

**Test Steps**:
1. Start a node
2. Run read-only commands (e.g., `show version` or `ip config`)
3. Send configuration commands (e.g., set IP address)

**Expected Results**:
- Read-only commands return device status information
- Configuration commands successfully applied to device

### 7.3 VPCS Configuration
**Tools**: `vpcs_config_set`

**Test Steps**:
1. Set IP address and gateway for VPCS node
2. Save configuration
3. Test network connectivity

**Expected Results**:
- IP configuration successfully applied
- Network connection test passes

---

## Phase 8: Packet Capture

### 8.1 Traffic Capture
**Tools**: `link_capture_start`, `link_capture_stop`, `link_capture_download`

**Test Steps**:
1. Start packet capture on a link
2. Generate some network traffic (ping test)
3. Stop capture
4. Get download link and download capture file

**Expected Results**:
- Capture file successfully created
- Can download and analyze PCAP file

---

## Phase 9: Drawing and Visualization

### 9.1 Create Drawing Elements
**Tools**: `drawing_create`, `drawing_list`, `drawing_get`

**Test Steps**:
1. Create a text label on the canvas
2. Create a shape (e.g., rectangle)
3. List all drawing elements
4. Get detailed information for drawings

**Expected Results**:
- Drawings successfully created, displayed at specified coordinates
- Returns drawing SVG content and position information

### 9.2 Modify Drawings
**Tools**: `drawing_update`, `drawing_delete`

**Test Steps**:
1. Modify drawing SVG content (e.g., change text)
2. Move drawing position
3. Delete a test drawing

**Expected Results**:
- Drawing successfully updated
- No longer appears in list after deletion

---

## Phase 10: Node Lifecycle Management

### 10.1 Node Start and Control
**Tools**: `node_start`, `node_stop`, `node_suspend`, `node_reload`

**Test Steps**:
1. Start a node
2. Suspend node
3. Reload node
4. Stop node

**Expected Results**:
- Each command successfully executes
- Node status correctly changes

### 10.2 Batch Operations
**Tools**: `node_start_all`, `node_stop_all`, `node_suspend_all`, `node_reload_all`

**Test Steps**:
1. Create multiple nodes
2. Batch start all nodes
3. Batch suspend all nodes
4. Batch stop all nodes

**Expected Results**:
- All node statuses change synchronously

### 10.3 Node Isolation
**Tools**: `node_isolate`, `node_unisolate`

**Test Steps**:
1. Isolate a node (suspend all connections)
2. Verify node cannot communicate with other nodes
3. Unisolate
4. Verify connection recovery

**Expected Results**:
- Network connections interrupted during isolation
- Connections recover after unisolation

---

## Phase 11: Snapshot Management

### 11.1 Create and Restore Snapshots
**Tools**: `snapshot_create`, `snapshot_list`, `snapshot_restore`, `snapshot_delete`

**Test Steps**:
1. Create a project snapshot "Test_Snapshot_1"
2. Modify project (add nodes)
3. Create second snapshot "Test_Snapshot_2"
4. List all snapshots
5. Restore to first snapshot
6. Verify project restored to previous state
7. Delete test snapshots

**Expected Results**:
- Snapshots successfully created and listed
- Project state matches snapshot state after restoration
- Snapshots successfully deleted

---

## Phase 12: Advanced Features and Cleanup

### 12.1 Template Creation
**Tools**: `template_create`, `template_update`, `template_delete`

**Test Steps**:
1. Create a custom template
2. Update template configuration
3. Delete test template

**Expected Results**:
- Template successfully created and modified
- No longer appears in template list after deletion

### 12.2 Symbol Upload
**Tools**: `symbol_upload`, `symbol_delete`

**Test Steps**:
1. Upload a custom symbol SVG
2. Use new symbol
3. Delete custom symbol

**Expected Results**:
- Custom symbol successfully uploaded and used
- Reverts to default symbol after deletion

### 12.3 Project Cleanup
**Tools**: `project_delete`, `project_close`

**Test Steps**:
1. Stop all running nodes
2. Close test project
3. Delete test project
4. List projects and verify successful deletion

**Expected Results**:
- Project successfully closed and deleted
- Test project no longer appears in project list

### 12.4 Image Cleanup
**Tools**: `image_prune`

**Test Steps**:
1. Run image cleanup command
2. Verify unused images are deleted

**Expected Results**:
- Disk space freed
- Only deletes images not referenced by projects

---

## Phase 13: Supplement Missing Critical Tools

After detailed comparison of the complete 82 GNS3 MCP tools, the following 4 critical tools were completely missing from the original test plan:

### 13.1 Image Management Supplement
**Missing Tools**: `image_install`, `image_delete`

**Background**: Original plan only had `image_list`, `image_get`, and `image_prune`, missing installation and deletion functions

**Test Steps**:
1. Check for pending image installation requests
2. Use `image_install` to trigger server installation of pending images
3. Select an unused test image
4. Use `image_delete` to delete that image
5. Verify image no longer appears in image list
6. Confirm disk space freed

**Expected Results**:
- Image installation request successfully submitted and executed
- Deletion operation correctly executed, image list immediately updated
- Disk space correspondingly freed

### 13.2 Link Deletion Function
**Missing Tool**: `link_delete`

**Background**: Original plan had `link_create` and various `link_*` operations, but missing deletion function

**Test Steps**:
1. Create a test link between two nodes
2. Verify link successfully created and traffic normal
3. Use `link_delete` to delete the link
4. Verify link no longer appears in link list
5. Check node port status correctly updated

**Expected Results**:
- Link successfully deleted, no residual connections
- Node port status correctly released
- Network topology accurately reflects deletion operation

### 13.3 Node Deletion Function
**Missing Tool**: `node_delete`

**Background**: Original plan had `node_create` and various node operations, but missing deletion function

**Test Steps**:
1. Create a VPCS test node
2. Configure IP address for that node
3. Use `node_delete` to delete that node
4. Verify node no longer appears in node list
5. Check if all links related to that node are automatically cleaned up
6. Verify project statistics (node count) correctly updated

**Expected Results**:
- Node successfully deleted, no state residue
- Related links automatically cleaned up or marked as invalid
- Project statistics correctly updated
- Ports used by node correctly released

### 13.4 Drawing Lock and Layer Enhanced Testing
**Supplemental Tools**: `locked` and `z` parameters in `drawing_update`

**Background**: Original plan had basic drawing operations, but missing lock and layer function tests

**Test Steps**:
1. Create two overlapping drawing elements
2. Modify first drawing's `z` value to make its layer higher
3. Verify higher-layer drawing obscures lower-layer drawing
4. Lock first drawing (`locked=true`)
5. Attempt to modify locked drawing (should fail)
6. Unlock drawing and successfully modify
7. Test `rotation` parameter to rotate drawing

**Expected Results**:
- Layer relationship correctly handled, display effect meets expectations
- Cannot modify when locked, returns to normal after unlock
- Rotation angle correctly applied to drawing display

---

## Test Execution Schedule Recommendations (Updated)

### Day 1: Basic Queries (Phase 1-3)
- Read-only operations, no risk
- Verify MCP connection and basic functionality

### Day 2: Project Creation (Phase 4)
- Create test environment
- Learn project management interface

### Day 3: Nodes and Topology (Phase 5-6)
- Build network topology
- Test node and link functionality

### Day 4: Device Interaction (Phase 7-8)
- Console operations
- Packet capture

### Day 5: Visualization and Control (Phase 9-10)
- Drawing functionality
- Node lifecycle management

### Day 6: Advanced Features (Phase 11-12)
- Snapshots and templates
- Clean up test environment

---

## Important Notes

⚠️ **Important Reminders**:
1. Deletion operations are irreversible, test `*_delete` type tools with caution
2. Batch operations may affect many resources, test on small projects first
3. Some operations require device support (e.g., snapshots, image management)
4. Isolate test environment from production environment
5. Record results and issues encountered for each test

📊 **Test Record Template**:
```
[Date] Phase X - Tool Name
- Status: ✅Success / ❌Failed / ⚠️Partially Successful
- Issues encountered: ...
- Verification results: ...
```
