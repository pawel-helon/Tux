# Tux

Tux is a terminal-native AI assistant designed for Linux and Termux. It provides a fast, keyboard-driven interface for chatting with local or remote language models while generating commands tailored to the current system.

## Features

- TUI - Terminal User Interface
- Chat and command modes
- Local model support through Ollama
- OpenAI-compatible API support
- Linux and Termux aware prompts
- Interactive keyboard chooser

## Requirements

- Python 3.11 or newer
- An OpenAI-compatible API endpoint
- Linux or Termux

## Installation

Clone the repository:

git clone <repository-url>
cd tux
   
Install in editable mode:

python -m pip install -e .

## Configuration

Run the provisioning command:

tux provision

or create "config.toml" manually:

endpoint = "http://127.0.0.1:11434/v1"
model = "qwen2.5-coder:3b"
variant = "full"
system = "linux"

On Termux:

endpoint = "http://127.0.0.1:11434/v1"
model = "qwen2.5-coder:3b"
variant = "full"
system = "termux"
 
## Running

Start an interactive session:

tux

Ask a question:

tux ask "How do I update my system?"

Display help:

tux --help

Keyboard

The chooser supports:

Key| Action
"j"| Next option
"k"| Previous option
"Enter"| Select
"Esc"| Cancel
"Ctrl-D"| Exit

Arrow keys are supported by many terminals, although some mobile keyboards may send terminal-specific escape sequences. The "j"/"k" bindings provide consistent navigation across Linux and Termux.

## Development

Install the project in editable mode:

python -m pip install -e .

Run directly:

python -m tux.cli

or simply:

tux

## License

This project is licensed under the MIT License. See the "LICENSE" file for details.
