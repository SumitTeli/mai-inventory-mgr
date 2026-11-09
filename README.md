# MAI Inventory Manager
This is a custom inventory manager for the [Medical Aid Initiative at UCLA](https://www.maiatucla.org/). 

## Note
This repository has recently been migrated from gitlab. It has not been touched in a while. PRs are welcome!

## Development

### Setting up your environment
Python 3.12 is required.

Create and activate a virtual environment, then install dependencies:
```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Testing
You can run directly on your local system:
```
./run_website.sh
```

### Machine API
A small JSON API under `/api/v1` for the ScanBase scanning app (UCLA Health Materials Management). It is off unless `MAI_API_KEY` is set. See [API.md](API.md).
