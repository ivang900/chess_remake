## Fresh setup

Clone the repo:

```
git clone <repo-url>
cd chess_remake
```

### 1. Create a virtual environment

**macOS / Linux:**
```
python3 -m venv venv
```

**Windows (PowerShell or CMD):**
```
python -m venv venv
```

### 2. Activate the venv

**macOS / Linux:**
```
source venv/bin/activate
```

**Windows PowerShell:**
```
venv\Scripts\Activate.ps1
```
If PowerShell blocks the script, run this once then retry:
```
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**Windows CMD:**
```
venv\Scripts\activate.bat
```

You should see `(venv)` at the start of your prompt.

### 3. Install dependencies

```
pip install -r requirements.txt
```

## Running the game

The server runs on **one** machine. Each player runs a client — on the same machine or a different one on the same network.

### Host (the machine running the server)

Start the server, bound to all interfaces so other devices on the LAN can reach it:

```
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Leave this terminal running. If your OS firewall prompts you, allow incoming connections on port 8000.

In a **second terminal** (with the venv activated), start your client:

```
python -m client.main
```

### Second player (same network)

Clone the repo, set up the venv, and install dependencies as above. Then:

```
python -m client.main
```

The default server URI is hardcoded to the host's LAN IP, so no flag is needed on the same network.

### Overriding the server address

To point a client at a different server, use `--server`:

```
python -m client.main --server ws://<host-ip>:8000/ws
```

This is how you'd connect to a server running on a different LAN IP, a tunneled address (ngrok, Tailscale, etc.), or `localhost` if you're running both the server and the client on one machine.

### Local testing (both clients on one machine)

Open three terminals (all with the venv activated):

1. `uvicorn server.main:app --host 0.0.0.0 --port 8000`
2. `python -m client.main`
3. `python -m client.main`

The first client to connect plays white, the second plays black. They auto-pair.

## Development commands

```
pytest              # run tests
ruff check .        # lint
mypy .              # type check
```

## Project layout

- `client/` — Pygame app, rendering and input
- `server/` — FastAPI + WebSocket server, matchmaking and game sessions
- `shared/` — rules engine, move validation, Pydantic message schemas
- `tests/` — pytest suite