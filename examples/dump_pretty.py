"""Render readable update-graph pictures on the server and save them locally.

  python examples/dump_pretty.py   -> examples/pretty_ex3.svg, pretty_ex4.svg, pretty_all.svg
"""
from pydeephaven import Session

GRAPHS = {
    "pretty_ex3": (["ex3 SignalTracker"], "Rung 3: signal pipeline → SignalTracker callback"),
    "pretty_ex4": (["ex4 synchronizer"], "Rung 4: three feeds → one synchronizer"),
    "pretty_all": (["ex3 SignalTracker", "ex4 synchronizer", "ex2_bars"], "Rungs 2–4 together"),
}

s = Session(host="localhost", port=10000, auth_type="Anonymous")
try:
    with open("examples/pretty_graph.py", encoding="utf-8") as f:
        s.run_script(f.read())
    for var, (roots, title) in GRAPHS.items():
        # Render server-side (graphviz lives there), pass global scope for variable names.
        s.run_script(
            "from deephaven import new_table\n"
            "from deephaven.column import string_col\n"
            f"_svg = pretty_graph({roots!r}, title={title!r}, scope=globals())\n"
            f"{var}_img = pretty_graph_image({roots!r}, title={title!r}, scope=globals())\n"
            "_svg_tbl = new_table([string_col('Svg', [_svg])])\n"
        )
        svg = s.open_table("_svg_tbl").to_arrow().to_pandas().Svg[0]
        with open(f"examples/{var}.svg", "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"wrote examples/{var}.svg ({len(svg):,} bytes); in DH: {var}_img")
finally:
    s.close()
