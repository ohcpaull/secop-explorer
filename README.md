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
* **User / Advanced / Expert** views driven by the node's SECoP `visibility`
  hints, plus per-group filtering — see
  [View levels (visibility)](#view-levels-visibility);
* controller/output pairs (Frappy `HasOutputModule` / `HasControlledBy`) grouped
  together in the sidebar — see [Linked modules](#linked-modules-controlled_by).

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

The mock exposes a ramping temperature controller (`ts`), a heater output
(`htr`) that `ts` drives while regulating, and a switch (`bnc`), with a few
`visibility` hints set so you can try the view levels below (`bnc` is hidden in
User view; `ts.ramp`, `ts.tolerance`, `ts.mode` and `ts.heater_output` each
behave differently per level). Setting `ts:target` hands `htr` to `ts`;
setting `htr:target` takes it back to manual.

## Linked modules (controlled_by)

When one module drives another — a temperature loop and its heater output,
written in Frappy with `HasOutputModule` (`output_module = Attached(...)`) on the
controller and `HasControlledBy` on the output — the sidebar shows them together
inside a faint bracket, with the driven module indented under its controller
(`↳`). Chains nest further (loop → secondary loop → heater), and an output that
several loops can drive sits under all of them. A linked module from another
`group` is moved next to its controller.

How it's discovered: Frappy doesn't put `output_module` in `describe`, but the
driven module has the standard SECoP parameter **`controlled_by`**, an enum of
`self` plus every module allowed to control it. Those names are the links, and
the parameter's live value says who is in control right now:

* the `↳` arrow turns accent-coloured when a controller is in charge, grey when
  the output is self-controlled (hover it for details);
* the module header shows `controls htr` / `controlled by ts` chips — solid when
  that link is active, dashed when not — and clicking one jumps to that module.

Modules hidden at the current view level are left out, so a link whose partner
isn't visible just shows as a normal, unbracketed row.

## View levels (visibility)

The **View** selector in the header switches between **User**, **Advanced**
and **Expert**. It follows the SECoP `visibility` property that a node can set
on any module, parameter or command.

`visibility` is a 3-character string — **one character per level, in the order
Expert, Advanced, User** — where each character is:

| char | meaning at that level |
|------|------------------------|
| `w`  | shown and writable / executable |
| `r`  | shown read-only (no **Set** editor; command button disabled) |
| `-`  | hidden |

| visibility | Expert | Advanced | User |
|------------|--------|----------|------|
| `www` (default) | writable | writable | writable |
| `wwr` | writable | writable | read-only |
| `wrr` | writable | read-only | read-only |
| `ww-` | writable | writable | hidden |
| `w--` | writable | hidden | hidden |

Details:

* No `visibility` in `describe` means `www` — Frappy doesn't export the
  default. Legacy values are mapped the same way Frappy does:
  `user`/`1` → `www`, `advanced`/`2` → `ww-`, `expert`/`3` → `w--`.
  (Frappy's auto-created IO modules are `expert`, so they only appear in
  Expert view.)
* **Module visibility caps everything inside it**: a module that is `-` at
  the current level disappears from the sidebar; one that is `r` makes all its
  parameters and commands read-only at that level.
* A parameter that is `readonly` in the protocol is never editable,
  whatever its visibility says.
* When something is hidden, the page says so ("*2 hidden in User view*" above
  the parameters, "*1 module hidden in User view*" in the sidebar), and
  read-only tags/disabled buttons have a tooltip saying which view allows the
  change.
* In **Expert** view each accessible that sets a visibility shows a `vis: …`
  tag — handy for checking a driver's configuration.
* The level is remembered per browser; bookmark a level with `?level=user`,
  `?level=advanced` or `?level=expert`.
* **It's a hint, not access control.** The server doesn't enforce visibility,
  and the raw **Console** tab can still send any command.

### Group chips

Above the parameter list there's also one chip per distinct `group` property
on the module's parameters (e.g. `tuning`, `diagnostics`). Click a chip to
hide/show every parameter in that group; a dashed, dimmed chip means the group
is hidden. Hidden groups are remembered and apply across modules.

Neither the view level nor the group chips affect communication — hidden
parameters still receive their `update`s and are current whenever you reveal
them.

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
