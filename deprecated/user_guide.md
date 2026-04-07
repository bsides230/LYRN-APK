# Professional LLM Interface v4.0 - User Guide

## Overview

The Professional LLM Interface v4.0 is a modern, clean GUI application for LLM chat with advanced job automation capabilities. Built with CustomTkinter, it features a professional dark mode interface with purple accents, replacing the previous cyberpunk styling.

## Key Features

- **Modern CustomTkinter Interface**: Professional dark theme with purple accents
- **Dynamic Folder Structure Loading**: Uses rwi.txt files for ordered content loading
- **JSON-based Settings System**: Easy configuration with GUI editor
- **Chunk-aware Job Processing**: Smart job automation without delays
- **Manual Mode with KV-preserving Replay**: Timestamp-ordered file replay
- **Performance Metrics Tracking**: Real-time tokens per second display
- **Automation Flag Management**: Prevents unintended automation resumption

## Installation & Environment Setup

### Prerequisites

1. **Python 3.8+** with the following packages:
   ```bash
   pip install customtkinter llama-cpp-python
   ```

2. **GPU Support (Optional but Recommended)**:
   - NVIDIA GPU with Vulkan drivers for optimal performance
   - The application automatically sets `LLAMA_BACKEND=vulkan`

3. **Model Files**:
   - Download your preferred LLM model in GGUF format
   - Default path: `D:/LLMs/models/Qwen.Qwen3-4B-Thinking-2507.Q4_K_M.gguf`

### File Structure

The application expects the following folder structure (all paths configurable via settings):

```
D:/LYRN/
├── static_snapshots/           # Static knowledge base
│   └── sta_rwi.txt            # File load order
├── dynamic_snapshots/          # Dynamic context
│   └── dyn_rwi.txt            # File load order
├── active_jobs/               # Job definitions
│   └── job_rwi.txt            # File load order
├── deltas/                    # System updates (optional)
├── active_chunk/              # Current conversation chunk
│   └── chunk.txt             # Active chunk content
├── chat/                      # Chat messages
├── active_keywords/           # Keyword indexes (optional)
├── active_topics/             # Topic indexes (optional)
├── global_flags/              # System flags
│   └── automation.txt        # Automation state
├── output/conversations/      # Job outputs
├── models/                    # LLM model files
└── automation/   
	├── chunk_queue.json          # Chunk processing queue
    ├── job_list.txt             # Job automation definitions
    └── job_log.json             # Per-chunk job completion log
```

## How to Launch the GUI

1. **Place Files**:
   - Save `professional_llm_gui_v4.py` and `purple-theme.json` in the same directory
   - Ensure the model file exists at the configured path

2. **Run Application**:
   ```bash
   python professional_llm_gui_v4.py
   ```

3. **First Launch**:
   - The application auto-generates `settings.json` if missing
   - Check Settings → verify model path and folder locations
   - The automation flag is automatically set to "off" on startup

## Interface Overview

### Main Layout

- **Left Sidebar**: Control panel with job automation, metrics, and system controls
- **Right Area**: Chat interface with input/output display

### Control Panel Sections

1. **Job Automation**
   - Start/Stop automation buttons
   - Manual job selection dropdown
   - Status indicators

2. **Performance Metrics**
   - KV Cache usage
   - Prompt processing stats
   - Generation speed (tokens/sec) in purple
   - Total token counts

3. **System Controls**
   - Settings configuration
   - Model reload
   - Chat clearing

4. **System Status**
   - Real-time status updates with color coding

## Manual vs Auto Job Processing

### Manual Mode (Default)

- **When**: Automation is stopped or `job_list.txt` is missing
- **Behavior**:
  - Users can manually input prompts
  - Job dropdown allows quick job insertion
  - KV-preserving replay loads `chat/` and `deltas/` files in timestamp order
  - Full conversation history is preserved for context

### Automatic Mode

- **When**: Job automation is started and `job_list.txt` exists
- **Behavior**:
  - Processes jobs sequentially without delays
  - Updates automation flag to "on"
  - Logs completed jobs to `job_log.json`
  - Triggers based on chunk transitions (not time delays)

### Switching Modes

- Use **Start Jobs** / **Stop Jobs** buttons in the control panel
- Automation state is saved to `global_flags/automation.txt`
- System automatically sets flag to "off" on startup for safety

## How job_list.txt Works

The job list file defines automated processing tasks:

### File Format

```txt
#*#job_list_start#*#
Summary Job
Keyword Extraction
Topic Analysis
Content Review
#*#job_list_end#*#

JOB_START: Summary Job
Provide a comprehensive summary of the content between ###SUMMARY_START### and ###SUMMARY_END### tags.

JOB_START: Keyword Extraction
Extract relevant keywords and phrases between ###KEYWORDS_START### and ###KEYWORDS_END### tags.

JOB_START: Topic Analysis
Identify main topics and themes between ###TOPICS_START### and ###TOPICS_END### tags.

JOB_START: Content Review
Review content for accuracy and completeness between ###REVIEW_START### and ###REVIEW_END### tags.
```

### Key Elements

- **Job List Section**: Between `#*#job_list_start#*#` and `#*#job_list_end#*#`
- **Job Definitions**: Each starts with `JOB_START: [Job Name]`
- **Processing Tags**: Use `###TAG_START###` and `###TAG_END###` format
- **Sequential Processing**: Jobs execute in listed order

## Folder Structure & Data Placement

### Core Folders

1. **static_snapshots**: Permanent knowledge base
   - Create `sta_rwi.txt` with relative paths to .txt files
   - Files load in specified order
   - Example `sta_rwi.txt`:
     ```
     core_knowledge/basics.txt
     reference/api_docs.txt
     guidelines/style_guide.txt
     ```

2. **dynamic_snapshots**: Contextual information
   - Uses `dyn_rwi.txt` for file ordering
   - May be empty - system won't fail
   - Updates based on current session

3. **active_jobs**: Current job definitions
   - Uses `job_rwi.txt` for ordering
   - Contains job-specific prompts and instructions
   - May be empty if no jobs active

4. **deltas**: Incremental updates
   - KV cache-efficient updates
   - Traits, system notices, memory updates
   - No nested folders - flat structure with timestamps

5. **active_chunk**: Current conversation context
   - Single `chunk.txt` file
   - Represents current conversation segment
   - Optional - may be empty

6. **chat**: Conversation messages
   - Flat structure with timestamp filenames
   - Format: `chat_YYYYMMDD_HHMMSS_microseconds.txt`
   - Contains user inputs and AI responses

### rwi.txt Files

**Purpose**: Control file loading order within folders
**Format**: One relative file path per line
**Example**:
```
introduction.txt
chapter_01/basics.txt
chapter_02/advanced.txt
appendix/references.txt
```

## Settings Configuration

### Via GUI Settings Panel

1. **Access**: Click "⚙ Settings" in the control panel
2. **Sections**:
   - **Model Configuration**: Path, context size, threads, GPU layers
   - **Generation Parameters**: Temperature, top_p, max tokens
   - **Directory Paths**: All folder locations

3. **Actions**:
   - **Save**: Apply changes and create backup
   - **Restore Backup**: Load previous settings from .bk file
   - **Reset to Defaults**: Use default configuration
   - **Cancel**: Discard changes

### Via Direct settings.json Edit

The settings file uses this structure:

```json
{
  "active": {
    "model_path": "D:/LLMs/models/model.gguf",
    "n_ctx": 32000,
    "n_threads": 22,
    "n_gpu_layers": 36,
    "max_tokens": 4096,
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 40,
    "stream": true
  },
  "defaults": { /* fallback values */ },
  "paths": { /* all directory paths */ }
}
```

### Backup System

- **Automatic**: Creates `.bk` backup before saving changes
- **Manual Restore**: Use "Restore Backup" button
- **Safety**: Prevents loss of working configurations

## Chunk Queue & Memory Flow

### Basic Concept

The system processes conversations in manageable "chunks" to maintain context while staying within model limits.

### Chunk Queue (chunk_queue.json)

```json
{
  "queue_index": 0,
  "queue": [
    {
      "chunk_path": "D:/Chat Memory System/chunked_15k/conversation_0001/chunk_0001.txt",
      "conversation_id": "conversation_0001", 
      "chunk_id": "chunk_0001",
      "processed": false,
      "timestamp_processed": null
    }
  ]
}
```

### Memory Flow Process

1. **Chunk Loading**: System loads current chunk from queue
2. **Context Building**: Combines static, dynamic, and chunk content
3. **Processing**: Runs jobs or handles manual interaction
4. **Logging**: Records completed jobs in `job_log.json`
5. **Advancement**: Moves to next chunk when current is complete

### Job Logging Per Chunk

```json
{
  "chunk_index": 17,
  "chunk_path": "D:/Chat Memory System/chunked_15k/conversation_0017/chunk_0001.txt",
  "jobs_performed": ["Summary Job", "Keyword Job"]
}
```

- **chunk_index**: Matches queue_index from chunk_queue.json
- **jobs_performed**: Only completed jobs listed
- **Reset**: Log clears when chunk advances

## Troubleshooting

### Common Issues

1. **Model Won't Load**:
   - Verify model path in settings
   - Check file permissions
   - Ensure sufficient RAM/VRAM

2. **Jobs Not Working**:
   - Verify `job_list.txt` exists and is properly formatted
   - Check automation flag state
   - Review job definitions for syntax errors

3. **Performance Issues**:
   - Adjust GPU layers in settings
   - Reduce context size if memory limited
   - Check thread count matches CPU cores

4. **Folder Access Errors**:
   - Verify all paths exist in settings
   - Check write permissions
   - Create missing directories manually

### Log Files & Debugging

- **Console Output**: Shows loading status and errors
- **Settings Backup**: Check `.bk` files for previous configurations
- **Job Log**: Review completed jobs in `job_log.json`
- **Automation Flag**: Check `global_flags/automation.txt` for state

## Advanced Usage

### Custom Theme Creation

1. Modify `purple-theme.json` color values
2. Use hex colors or CustomTkinter color names
3. Restart application to apply changes

### Batch Processing

1. Set up multiple chunks in queue
2. Configure appropriate jobs in `job_list.txt`
3. Start automation for sequential processing

### Integration with External Scripts

- The system maintains JSON files for external script integration
- Automation flag allows coordination with other tools
- Chat and delta folders enable external monitoring

---

## Support & Updates

For issues, suggestions, or contributions, refer to the application changelog and version history for the latest improvements and fixes.