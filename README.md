# SciFiBrowser

Scientific file browser based on Bluesky Tiled and `pyTEMlib`.

It serves scientific files from `/Users/austin/Desktop/Projects` through a local Tiled GUI.

```bash
uv sync
uv run scifibrowser serve --register --watch --verbose
```

Then browse locally at:

```text
http://127.0.0.1:8000/ui/
```

The custom Tiled adapter uses:

```python
import pyTEMlib.file_tools as ft

dset = ft.open_file(path)
```

Each sidpy dataset in that dictionary is exposed as a child array in Tiled.

`--watch` uses a SciFiBrowser refresh loop instead of Tiled's built-in watcher, so a registration refresh failure will not shut down the local GUI. The default refresh interval is 300 seconds; change it with `--watch-interval 60`.

## Simple Launcher

For a no-terminal workflow, run:

```bash
uv run scifibrowser gui
```

or:

```bash
uv run scifibrowser-launcher
```

The launcher lets the user enter the IP address, choose a data folder from a dropdown, and click **Run**. It shows an indexing window while Tiled registers the selected folder, then opens the Tiled GUI in the default browser.
