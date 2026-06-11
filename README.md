# GNS3 API MCP Test Documentation

This repository contains the complete test documentation for the GNS3 API MCP Server ([3.1 branch of gns3-server](https://github.com/yueguobin/gns3-server/tree/3.1)). It covers all 82 MCP tools across 13 test stages, from basic read-only queries to advanced features and cleanup operations.

## Project Overview

- **Total Tools Tested**: 82
- **Test Coverage**: 100%
- **Test Stages**: 13
- **License**: CC BY-NC-ND 4.0 (attribution, non-commercial, no derivatives)

## Directory Structure

```
mcp_test_docs/
├── zh/    Chinese documentation (15 files)
└── en/    English documentation (15 files)
```

## Test Stages

| Stage | Topic | Tools |
|-------|-------|-------|
| 1 | Server Information Query | `server_version`, `server_statistics` |
| 2 | Compute Node & Device Management | `compute_list`, `compute_get`, `compute_images` |
| 3 | Symbol & Template Management | `symbol_list`, `symbol_get`, `symbol_dimensions`, `template_list`, `template_get` |
| 4 | Project Management | `project_create`, `project_list`, `project_get`, `project_update`, `project_duplicate`, etc. |
| 5 | Node Creation & Management | `node_create`, `node_list`, `node_get`, `node_update`, `node_start`, `node_stop`, etc. |
| 6 | Links & Network Topology | `link_create`, `link_list`, `link_get`, `link_update`, `link_reset` |
| 7 | Node Console & Configuration | `node_console`, `device_command_run`, `device_config_send`, `vpcs_config_set` |
| 8 | Packet Capture | `link_capture_start`, `link_capture_stop`, `link_capture_download` |
| 9 | Drawing & Visualization | `drawing_create`, `drawing_list`, `drawing_get`, `drawing_update`, `drawing_delete` |
| 10 | Node Lifecycle Management | `node_start_all`, `node_stop_all`, `node_suspend`, `node_reload`, `node_isolate`, etc. |
| 11 | Snapshot Management | `snapshot_create`, `snapshot_list`, `snapshot_restore`, `snapshot_delete` |
| 12 | Advanced Features & Cleanup | `template_create`, `template_update`, `template_delete`, `symbol_upload`, `project_close`, `project_delete`, `image_prune` |
| 13 | Missing Tools Test | `image_install`, `image_delete`, `link_delete`, `node_delete` |

## Documentation Files

### English (`en/`)

| File | Description |
|------|-------------|
| [gns3_mcp_test_plan_en.md](mcp_test_docs/en/gns3_mcp_test_plan_en.md) | Full test plan |
| [GNS3_MCP_Testing_Skill.md](mcp_test_docs/en/GNS3_MCP_Testing_Skill.md) | Testing skill guide |
| [stage1_server_info_query_en.md](mcp_test_docs/en/stage1_server_info_query_en.md) | Stage 1 test record |
| [stage2_compute_and_device_management_en.md](mcp_test_docs/en/stage2_compute_and_device_management_en.md) | Stage 2 test record |
| [stage3_symbol_and_template_management_en.md](mcp_test_docs/en/stage3_symbol_and_template_management_en.md) | Stage 3 test record |
| [stage4_project_management_en.md](mcp_test_docs/en/stage4_project_management_en.md) | Stage 4 test record |
| [stage5_node_creation_and_management_en.md](mcp_test_docs/en/stage5_node_creation_and_management_en.md) | Stage 5 test record |
| [stage6_links_and_network_topology_en.md](mcp_test_docs/en/stage6_links_and_network_topology_en.md) | Stage 6 test record |
| [stage7_node_console_and_configuration_en.md](mcp_test_docs/en/stage7_node_console_and_configuration_en.md) | Stage 7 test record |
| [stage8_packet_capture_en.md](mcp_test_docs/en/stage8_packet_capture_en.md) | Stage 8 test record |
| [stage9_drawing_and_visualization_en.md](mcp_test_docs/en/stage9_drawing_and_visualization_en.md) | Stage 9 test record |
| [stage10_node_lifecycle_management_en.md](mcp_test_docs/en/stage10_node_lifecycle_management_en.md) | Stage 10 test record |
| [stage11_snapshot_management_en.md](mcp_test_docs/en/stage11_snapshot_management_en.md) | Stage 11 test record |
| [stage12_advanced_features_and_cleanup_en.md](mcp_test_docs/en/stage12_advanced_features_and_cleanup_en.md) | Stage 12 test record |
| [stage13_missing_tools_test_en.md](mcp_test_docs/en/stage13_missing_tools_test_en.md) | Stage 13 test record |

### Chinese (`zh/`)

See [mcp_test_docs/zh/](mcp_test_docs/zh/) for Chinese documentation.

## Related Projects

- [gns3-server (3.1 branch)](https://github.com/yueguobin/gns3-server/tree/3.1) - GNS3 server with MCP support
- [gns3-copilot](https://github.com/yueguobin/gns3-copilot) - AI-powered network automation assistant for GNS3

## License

This project is licensed under [CC BY-NC-ND 4.0](LICENSE). You are free to share the material with attribution, but not for commercial purposes and no modifications are allowed.
