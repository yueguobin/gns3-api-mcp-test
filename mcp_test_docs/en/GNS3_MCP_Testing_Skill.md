# GNS3 MCP Tool Testing Skill

## Skill Description

This skill is used to guide systematic testing of GNS3 MCP tools, ensuring a standardized testing process, consistent documentation style, and comprehensive coverage.

## Skill Trigger Conditions

This skill is triggered when the user requests any of the following operations:
- "Start GNS3 MCP testing" or "Test GNS3 tools"
- "Execute Phase X testing" or "Test Phase X"
- "Supplement missing tests" or "Complete remaining tests"
- "Follow the test plan for testing"

## Testing Methodology

### Core Principles

1. **Safety First**: Start with read-only operations, gradually transition to modify/delete operations
2. **Dependency Management**: Create infrastructure (projects) first, then test specific features
3. **Verifiability**: Each test has clear execution steps and expected results
4. **Documentation Consistency**: Maintain the same professional style as Phase 1-3 test documentation

### Testing Process

#### Phase 1: Preparation Phase

1. **Read Test Plan**
   - Read `/home/yueguobin/claude-test/gns3_mcp_test_plan.md`
   - Understand current phase's testing objectives and tool list
   - Confirm testing type (read-only/modify/delete)

2. **Review Completed Tests**
   - Check existing test documentation: `阶段*_*.md`
   - Understand test status of completed tools
   - Identify missing or supplementary tests needed

3. **Prepare Test Environment**
   - Confirm GNS3 MCP server connection is normal
   - Check if there are prerequisites (e.g., existing projects)
   - Prepare test parameters and data

#### Phase 2: Execute Tests

1. **Tool Call Testing**
   - Test each tool one by one according to the test plan's tool list
   - Record each tool's call process and return results
   - Note exceptions and error handling

2. **Result Verification**
   - Verify the format and completeness of returned data
   - Check if response time is reasonable
   - Confirm functionality works as expected

3. **Problem Analysis**
   - Distinguish between "errors" and "designed behavior"
   - Analyze the scope and limitations of tools
   - Record important findings and notes

#### Phase 3: Documentation

1. **Create Test Documentation**
   - Use the same document structure as Phase 1-3
   - Maintain professional documentation style
   - Include detailed testing process and analysis

2. **Document Structure Requirements**

Each test document must contain the following sections:

```markdown
# Phase X: [Phase Name] - Test Record

## Test Basic Information

**Phase Number**: Phase X  
**Phase Name**: [Phase Name]  
**Test Date**: [Current Date]  
**Test Type**: [Test Type]  
**Tools Involved**: X tools  
**Test Status**: ✅ Complete/⚠️ Partially Complete/❌ Failed

---

## Test Objectives

Verify GNS3 MCP server's [function description], including:
- Feature 1
- Feature 2
- Feature 3

---

## Tool List

1. `mcp__My_GNS3_Server__tool_name1` - Tool description
2. `mcp__My_GNS3_Server__tool_name2` - Tool description

---

## Test Process

### Test X.1: [Test Item Name]

**Tool**: `mcp__My_GNS3_Server__tool_name`  
**Execution Time**: [DateTime]  
**Parameters**: [Parameter description]

#### Execution Command
```bash
Call tool_name(parameters)
```

#### Return Result
```json
{
  "result": "data"
}
```

#### Result Analysis

**✅ Verification Point 1**
- Specific verification content
- Data analysis
- Performance evaluation

#### Test Conclusion
✅ **Test Passed** - Function description

---

## Phase Test Summary

### Function Verification Results

| Test Item | Tool Name | Status | Response Time | Data Integrity |
|-----------|-----------|--------|---------------|----------------|
| Test 1    | tool_name | ✅ Success | <100ms | Complete |

### Success Rate Statistics
- ✅ **Success**: X/X (XX%)
- ❌ **Failure**: X/X (0%)

### Verified Features
- Function description 1
- Function description 2

### Issues Found
- Problem description and solution

### Key Findings
- 🟢 Positive findings
- 🟡 Needs attention
- 📋 Recommendations

---

## Test Signature

**Test Execution**: Claude  
**Test Supervision**: YueGuobin  
**Test Date**: [Date]  
**Test Status**: ✅ Passed  
**Next Phase**: [Next Phase Name]

---

**Document Created**: [Date]  
**Last Updated**: [Date]  
**Document Version**: 1.0
```

#### Phase 4: Quality Control

1. **Test Completeness Check**
   - Confirm all planned tools have been tested
   - Verify test document structure is complete
   - Check test conclusions are clear

2. **Data Consistency Verification**
   - Ensure statistical data is accurate
   - Verify tool count matches plan
   - Check logic of result analysis

3. **Documentation Style Consistency**
   - Compare with Phase 1-3 document styles
   - Maintain same format and markers
   - Use consistent professional terminology

## Supplementary Testing Guidelines

### When Missing Tests Are Found

1. **Analyze Missing Reason**
   - Was the tool planned but omitted
   - Is the tool new or not covered in the plan
   - Does the tool require special conditions for testing

2. **Supplementary Test Strategy**
   - Evaluate tool importance and testing priority
   - Determine testing method (full test vs. function verification)
   - Prepare test environment and parameters

3. **Supplementary Test Documentation**
   - Add "Supplementary Test" section at the end of original test document
   - Maintain same style and depth as original test
   - Update test statistics and success rate

### Supplementary Test Document Format

```markdown
---

## Supplementary Test: tool_name (DateTime)

### Supplementary Test Reason
[Describe why this test was missed or needs supplementation]

### Test Tool: `tool_name`

**Tool Purpose**: [Tool function description]

#### Test X.X: [Test Item Name]

**Tool**: `mcp__My_GNS3_Server__tool_name`  
**Execution Time**: [DateTime]

##### Test Step 1: [Step Description]

**Execution Command**:
```bash
Call tool_name(parameters)
```

**Return Result**:
```json
{...}
```

**Result Analysis**:
- ✅ **Verification Point**: Specific analysis

##### Test Conclusion

✅ **Test Passed** - Function verification complete

#### Updated Test Statistics

**Phase X Tool Test Completion**:
- **Planned Tools**: X tools
- **Actual Tests**: X tools (100%)
- **Function Verification**: Complete

**Tested Tool List**:
1. ✅ tool1 - Test status
2. ✅ tool2 - Test status

---

**Document Created**: [Date]  
**Last Updated**: [Date] (Supplementary test time)  
**Document Version**: X.X
```

## Testing Tool Inventory

### Completed Tests (Phase 1-3)

**Phase 1: Server Information Query** ✅
- server_version, server_statistics

**Phase 2: Compute Nodes and Device Management** ✅
- compute_list, compute_get, appliance_list, appliance_get, appliance_install
- image_list, image_get, compute_images

**Phase 3: Symbols and Templates Management** ✅
- symbol_list, symbol_get, symbol_defaults, symbol_dimensions
- template_list, template_get

### Pending Tests (Phase 4-13)

**Phase 4: Project Management** (11 tools)
- project_create, project_list, project_get, project_update
- project_duplicate, project_load, project_open
- project_readme_update, project_readme_get, project_stats
- project_lock, project_unlock, project_locked

**Phase 5: Node Creation and Management** (12 tools)
- node_create, node_list, node_get, node_update, node_duplicate
- node_file_list, node_file_write, node_file_get, node_file_delete
- node_isolate, node_links, node_unisolate

**Phase 6: Links and Network Topology** (5 tools)
- link_create, link_list, link_get, link_update, link_reset

**Phase 7: Node Console and Configuration** (4 tools)
- node_console, device_command_run, device_config_send, vpcs_config_set

**Phase 8: Packet Capture** (3 tools)
- link_capture_start, link_capture_stop, link_capture_download

**Phase 9: Drawing and Visualization** (5 tools)
- drawing_create, drawing_list, drawing_get, drawing_update, drawing_delete

**Phase 10: Node Lifecycle Management** (8 tools)
- node_start, node_stop, node_suspend, node_reload
- node_start_all, node_stop_all, node_suspend_all, node_reload_all

**Phase 11: Snapshot Management** (4 tools)
- snapshot_create, snapshot_list, snapshot_restore, snapshot_delete

**Phase 12: Advanced Functions and Cleanup** (7 tools)
- template_create, template_update, template_delete
- symbol_upload, symbol_delete
- project_delete, project_close, image_prune

**Phase 13: Supplementary Missing Tools** (4 tools)
- image_install, image_delete, link_delete, node_delete

## Notes

### Tool Usage Understanding

1. **Compute Node Tools**: Specifically for remote compute nodes, local nodes use server_statistics
2. **Device Installation**: Requires version parameters, large files not suitable for test environment
3. **Delete Operations**: Irreversible, requires careful testing
4. **Batch Operations**: May affect many resources, test on small projects first

### Test Environment Considerations

1. **Disk Space**: Some operations require large amounts of storage space
2. **Network Dependency**: Some operations require external network connections
3. **Time Cost**: Large file operations may take a long time
4. **Resource Cleanup**: Clean up test data promptly after testing

### Documentation Quality Standards

1. **Professionalism**: Use professional technical terminology and expressions
2. **Completeness**: Include all necessary sections and data
3. **Accuracy**: Ensure statistical data and analysis results are accurate
4. **Readability**: Clear format, easy for future reference

## Skill Usage Example

When the user says "Start Phase 4 testing", this skill should:

1. Automatically read the test plan file
2. Review existing test documentation to understand progress
3. Execute the 11 project management tools of Phase 4 according to the test plan
4. Create `阶段4_项目管理.md` document
5. Maintain the same documentation style and professionalism as Phases 1-3
6. Include detailed testing process, result analysis, and summary
7. Provide complete test statistics and findings

Through this skill, ensure systematic and consistent GNS3 MCP testing, providing a reliable verification foundation for subsequent tool usage.