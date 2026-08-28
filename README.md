# Quiz App Developer README

## Overview

This project is a desktop quiz application built with Python and Tkinter. It lets a user:

- choose a learning library from the local data folders under X/
- generate quiz questions from selected topics
- answer questions and receive AI-assisted evaluation
- review past quizzes and tutor through specific questions

The app is organized as a Tkinter-based UI with a thin bootstrap layer in main_app and feature modules under main_app/.

## Project Structure

- main_app/__main__.py — module entry point
- main_app/app.py — top-level app bootstrap and global error handling
- main_app/ui/ — Tkinter pages and window shell
- main_app/api_client.py — API client with GROQ/OpenRouter/custom provider support
- main_app/config.py — persisted app configuration
- main_app/evaluation_runner.py — quiz evaluation orchestration
- main_app/library_scanner.py — library tree scanning and topic selection
- X/ — example learning content and topic folders used by the app
- dev_test_agent2.py — small development script for experimenting with agent logic

## Requirements

- Python 3.10+
- Tkinter support for your Python build
- The Python package `requests`
- Optional: `opencode` if you want to use CLI bridge mode instead of direct API calls

### Linux setup

On Debian/Ubuntu-based systems, install Tkinter support if needed:

```bash
sudo apt update
sudo apt install python3-tk
```

Create and activate a virtual environment:

```bash
cd /home/favour/Desktop/Learning/Resources/virtuals_and_code/quiz_app
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install requests
```

## Running the App

From the project root:

```bash
python -m main_app
```

You can also run the app via the package entry point if available in your environment:

```bash
python main_app/__main__.py
```

## Configuration

The app stores configuration in:

```bash
~/.quiz_app/config.json
```

Key settings include:

- API provider credentials and model names
- selected learning library root
- selected topic folders
- evaluation defaults
- provider mode (`api` or `cli_bridge`)

## Development Notes

### UI flow

The main window is assembled in main_app/ui/main_window.py, and each major page lives in its own module under main_app/ui/.

### API provider behavior

The app supports:

- direct API access via GROQ/OpenRouter/custom OpenAI-compatible endpoints
- CLI bridge mode via `opencode`

When using CLI bridge mode, the app depends on `opencode` being installed and available in your PATH.

### Library data format

The quiz content is expected to live under folders such as:

```text
X/<subject>/<topic>/
```

with files such as:

- question_bank.txt
- answer_bank.txt

## Troubleshooting

- If the UI fails to start, make sure Tkinter is installed for your Python build.
- If API calls fail, verify your provider keys or switch to CLI bridge mode.
- If topics do not appear in the library selection view, confirm the folder structure under X/ matches the expected subject/topic layout.

## Useful Development Commands

```bash
# run the app
python -m main_app

# run a lightweight development script
python dev_test_agent2.py
```

## Notes

This repository currently focuses on local development and experimentation rather than packaging into a distributable app. The app is intentionally modular, so new features usually fit best as a small addition to the relevant UI page and supporting module.
