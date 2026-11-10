# SECoP Node Explorer

A browser-based client for a **SECoP** (Sample Environment Communication Protocol)
node. It reads the node's `describe` report and gives you:

* every module, grouped, with a live status light (idle / warn / busy / error);
* every parameter with its description, data type, current value + unit + timestamp;
* type-aware editors for writable parameters (number / bool / enum / string / JSON);
* command execution with argument input and result display;
* live **time plots** of any numeric parameter, with CSV export;
* a raw **console** showing the full protocol traffic, with a manual send box;
* a **Node info** tab with the node properties and the full raw `describe` JSON;
* per-module filtering to keep the operational parameters in view — see
  [Hiding advanced/internal parameters](#hiding-advancedinternal-parameters).

## Files

| file | purpose |
|------|---------|
| `secop_web_client.html` | the web page — open it in a browser |
| `secop_bridge.py`       | WebSocket ⇄ TCP bridge (needed for a normal TCP SECoP node) |
| `mock_secop_node.py`    | a fake SECoP node, only for trying the page out |

## Why the bridge?

A web page cannot open a raw TCP socket, and a standard SECoP node speaks a
line-based text protocol over **plain TCP** (default port `10767`). `secop_bridge.py`
is a tiny relay: the browser talks WebSocket to the bridge, the bridge talks TCP to
the node, one SECoP line per message. It is pure Python standard library — no
`pip install`.

If your SECoP server already exposes a **native WebSocket interface** (e.g. a
Frappy `ws` interface), you don't need the bridge — use the page's
*"Direct WebSocket URL"* mode instead.

## Quick start

1. Start the bridge (leave it running):

   ```bash
   python3 secop_bridge.py --listen 127.0.0.1:1337
   ```

2. Open `secop_web_client.html` in your browser (double-click it, or serve the
   folder with `python3 -m http.server`).

3. In the page:
   * mode **Via bridge**
   * **Bridge URL**: `ws://localhost:1337`
   * **SECoP host**: where the node runs (e.g. `localhost` or an instrument PC)
   * **SECoP port**: the node's port (e.g. `10767`)
   * click **Connect**.

The page sends `*IDN?`, `describe`, then `activate`, and populates automatically.
Values update live while connected. Use the 📈 **Plot** button on any numeric
parameter to chart it against time; the **Plots** tab holds the charts.

### Bookmarking a node

The host/port prefill from the URL query string:

```
secop_web_client.html?host=instrument-pc&port=10767
```

## Try it without hardware

```bash
python3 mock_secop_node.py --port 10800      # terminal 1
python3 secop_bridge.py --listen 127.0.0.1:1337   # terminal 2
# open secop_web_client.html, connect with host=localhost port=10800
```

The mock exposes a ramping temperature controller (`ts`) and a switch (`bnc`).

## Hiding advanced/internal parameters

Some modules expose a lot of parameters that are rarely touched — internal
tuning knobs, poll intervals, and the like. The **Module** tab shows a small
filter bar above the parameter list whenever a module has any of these:

* **show advanced / internal (n)** — a checkbox, off by default. A parameter
  counts as "advanced" if the node marks it with SECoP `visibility: advanced`
  or `expert`, or — failing that — if its name starts with `_` (Frappy
  exports any parameter outside a module's standard SECoP interface with a
  leading underscore, e.g. `_tolerance`).
* **group chips** — one per distinct `group` property found on the module's
  parameters (e.g. `tuning`, `diagnostics`). Click a chip to hide/show every
  parameter in that group; a dashed, dimmed chip means the group is hidden.

Both settings are remembered (per browser, via `localStorage`) and apply
across modules, so hiding a group like `diagnostics` once hides it everywhere
it appears. They only affect what's displayed — hidden parameters still get
their `read`/`update` traffic and keep their values current for whenever you
reveal them.

## Notes / limitations

* The bridge listens on `127.0.0.1` by default. To reach it from other machines
  use `--listen 0.0.0.0:1337` (only on a trusted network — the bridge applies no
  authentication and will connect to any host:port it is asked to).
* Writes go straight to the instrument. There is no confirmation dialog on
  **Set** / **Execute** — treat it like a real control screen.
* Struct / tuple / array parameters are edited as raw JSON.
* Plot history is kept in memory only (capped at 20 000 points per parameter);
  use **CSV** to save a trace.
* Tested against the SINE2020 / SECoP v1.0 line protocol
  (`*IDN?`, `describe`, `activate`, `read`, `change`, `do`, `update`, `error_*`).
