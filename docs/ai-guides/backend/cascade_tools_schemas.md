# Cascade (My) Available Tools

This document lists all tools available to me (Cascade) in the current conversation harness.

## File System Tools

### read_file
- **Description**: Reads a file at the specified relative path
- **Parameters**: 
  - `file_path` (string, required): Absolute path to the file
  - `offset` (integer, optional): 1-indexed line number to start reading from
  - `limit` (integer, optional): Number of lines to read

### write_to_file
- **Description**: Creates new files. The file and any parent directories will be created
- **Parameters**:
  - `TargetFile` (string, required): Target file path (absolute)
  - `CodeContent` (string, required): Code contents to write
  - `EmptyFile` (boolean, optional): Set to true to create an empty file

### edit
- **Description**: Performs exact string replacements in files
- **Parameters**:
  - `file_path` (string, required): Path to modify
  - `old_string` (string, required): Text to replace
  - `new_string` (string, required): Text to replace with
  - `explanation` (string, required): Description of change
  - `replace_all` (boolean, optional): Replace all occurrences

### multi_edit
- **Description**: Makes multiple edits to a single file in one operation
- **Parameters**:
  - `file_path` (string, required): Path to modify
  - `edits` (array, required): Array of edit operations
  - `explanation` (string, required): Description of changes

### find_by_name
- **Description**: Searches for files and subdirectories using fd
- **Parameters**:
  - `SearchDirectory` (string, required): Directory to search within
  - `Pattern` (string, required): Pattern to search for (glob format)
  - `Type` (enum, optional): file, directory, or any
  - `Extensions` (array, optional): File extensions to include
  - `MaxDepth` (integer, optional): Maximum search depth
  - `FullPath` (boolean, optional): Whether full path must match

### list_dir
- **Description**: Lists files and directories in a given path
- **Parameters**:
  - `DirectoryPath` (string, required): Absolute path to directory

## Search Tools

### Grep
- **Description**: A powerful search tool built on ripgrep
- **Parameters**:
  - `pattern` (string, required): Regex pattern to search
  - `path` (string, required): File or directory to search
  - `glob` (string, optional): Glob pattern to filter files
  - `output_mode` (enum, optional): content, files_with_matches, or count
  - `type` (string, optional): File type (js, py, rust, etc.)
  - `case_sensitive` (boolean, optional): Case-sensitive search
  - `head_limit` (integer, optional): Limit results
  - `-A`, `-B`, `-C` (integer, optional): Context lines

## Command Execution

### bash
- **Description**: Executes terminal commands on the user's machine
- **Parameters**:
  - `CommandLine` (string, required): Command to execute
  - `Cwd` (string, required): Current working directory
  - `Background` (boolean, optional): Run in background
  - `WaitMsBeforeAsync` (integer, optional): Wait time before async
  - `SafeToAutoRun` (boolean, optional): Auto-run without approval

## CodeDB MCP Tools

### mcp1_codedb_context
- **Description**: Task-shaped composer for code intelligence
- **Parameters**:
  - `task` (string, required): Natural-language task description
  - `project` (string, optional): Absolute path to project

### mcp1_codedb_search
- **Description**: Substring full-text search across the index
- **Parameters**:
  - `query` (string, required): Text to search for
  - `path_glob` (string, optional): Filter by path pattern
  - `regex` (boolean, optional): Treat as regex pattern
  - `scope` (boolean, optional): Annotate with symbol scope
  - `max_results` (integer, optional): Maximum results

### mcp1_codedb_symbol
- **Description**: Find where a named symbol is defined
- **Parameters**:
  - `name` (string, required): Symbol name to search
  - `project` (string, optional): Project path
  - `body` (boolean, optional): Include source body

### mcp1_codedb_read
- **Description**: Read file contents, optionally a line range
- **Parameters**:
  - `path` (string, required): File path relative to project root
  - `line_start` (integer, optional): Start line (1-indexed)
  - `line_end` (integer, optional): End line (1-indexed)
  - `compact` (boolean, optional): Skip comment/blank lines

### mcp1_codedb_outline
- **Description**: Symbol outline of one file
- **Parameters**:
  - `path` (string, required): File path
  - `project` (string, optional): Project path
  - `compact` (boolean, optional): Condensed format

### mcp1_codedb_tree
- **Description**: Whole-repo file tree with per-file metadata
- **Parameters**:
  - `project` (string, optional): Project path

## Context7 MCP Tools

### mcp2_resolve-library-id
- **Description**: Resolves package name to Context7-compatible library ID
- **Parameters**:
  - `libraryName` (string, required): Library name to search
  - `query` (string, required): Question/task for relevance ranking

### mcp2_query-docs
- **Description**: Queries documentation and code examples from Context7
- **Parameters**:
  - `libraryId` (string, required): Context7-compatible library ID
  - `query` (string, required): Question or task

## Slack MCP Tools

### mcp4_send_message
- **Description**: Send a message to a Slack channel
- **Parameters**:
  - `channel` (string, required): Channel name or ID
  - `text` (string, required): Message text
  - `workspace` (string, optional): Workspace name
  - `thread_ts` (string, optional): Thread timestamp
  - `unfurl_links` (boolean, optional): Unf URLs

### mcp4_read_channel
- **Description**: Read recent messages from a Slack channel
- **Parameters**:
  - `channel` (string, required): Channel name or ID
  - `workspace` (string, optional): Workspace name
  - `limit` (integer, optional): Max messages to return

## Web Tools

### search_web
- **Description**: Performs web search for relevant documents
- **Parameters**:
  - `query` (string, required): Search query
  - `domain` (string, optional): Domain to prioritize

### read_url_content
- **Description**: Reads content from HTTP/HTTPS URL
- **Parameters**:
  - `Url` (string, required): URL to read

### browser_preview
- **Description**: Spins up browser preview for web server
- **Parameters**:
  - `Url` (string, required): URL of web server
  - `Name` (string, required): Short name for server

## Task Management

### todo_list
- **Description**: Creates, updates, or manages todo lists
- **Parameters**:
  - `todos` (array, required): List of todo items with id, content, status, priority

## Skill System

### skill
- **Description**: Invokes a skill for detailed instructions
- **Parameters**:
  - `SkillName` (string, required): Name of skill to invoke

## Memory System

### create_memory
- **Description**: Saves context to persistent memory database
- **Parameters**:
  - `Title` (string, required): Descriptive title
  - `Content` (string, required): Memory content
  - `CorpusNames` (array, required): Workspace corpus names
  - `Tags` (array, optional): Tags to associate
  - `Action` (enum, required): create, update, or delete
  - `Id` (string, optional): ID for update/delete
  - `UserTriggered` (boolean, required): User explicitly requested

## Notebook Tools

### read_notebook
- **Description**: Reads and parses Jupyter notebook file
- **Parameters**:
  - `AbsolutePath` (string, required): Absolute path to .ipynb file

### edit_notebook
- **Description**: Replaces cell content in Jupyter notebook
- **Parameters**:
  - `absolute_path` (string, required): Path to .ipynb file
  - `new_source` (string, required): New cell content
  - `cell_number` (integer, optional): 0-indexed cell number
  - `cell_id` (string, optional): Target cell ID
  - `edit_mode` (enum, optional): replace or insert
  - `cell_type` (enum, optional): code or markdown (for insert)

## Process Management

### command_status
- **Description**: Checks status of terminal command by ID
- **Parameters**:
  - `CommandId` (string, required): Process ID of command
  - `OutputCharacterCount` (integer, required): Characters to view
  - `WaitDurationSeconds` (integer, optional): Wait time for completion

### read_terminal
- **Description**: Reads contents of a terminal by process ID
- **Parameters**:
  - `ProcessID` (string, required): Process ID
  - `Name` (string, required): Terminal name

## Resource Tools

### list_resources
- **Description**: Lists available resources from MCP server
- **Parameters**:
  - `ServerName` (string, required): MCP server name

### read_resource
- **Description**: Retrieves resource contents
- **Parameters**:
  - `ServerName` (string, required): MCP server name
  - `Uri` (string, required): Resource identifier

## Content Viewing

### view_content_chunk
- **Description**: Views specific chunk of web/knowledge base document
- **Parameters**:
  - `document_id` (string, required): Document ID
  - `position` (integer, required): Chunk position

---

**Total Tools Available**: ~40+ tools across multiple categories

**Note**: These are the tools I have access to in this conversation. I see their schemas (names, descriptions, parameters) and can invoke them when needed for your tasks.
