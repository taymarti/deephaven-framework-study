"""Run 05_introspection.py on the server; save DOT graphs and print summaries locally.

  python examples/dump_graph.py            -> examples/ex3_graph.dot, examples/ex4_graph.dot
"""
import pandas as pd
from pydeephaven import Session

pd.set_option("display.width", 200)
pd.set_option("display.max_colwidth", 60)

s = Session(host="localhost", port=10000, auth_type="Anonymous")
try:
    with open("examples/05_introspection.py", encoding="utf-8") as f:
        s.run_script(f.read())
    s.run_script(
        "from deephaven import new_table, perfmon\n"
        "from deephaven.column import string_col\n"
        "ex5_dot_tbl = new_table([string_col('Name', ['ex3', 'ex4']), string_col('Dot', [\n"
        "    perfmon.ancestor_dot(ex5_id_ex3, ex5_upl, ex5_ancestors),\n"
        "    perfmon.ancestor_dot(ex5_id_ex4, ex5_upl, ex5_ancestors)]), string_col('Svg', [\n"
        "    perfmon.ancestor_svg(ex5_id_ex3, ex5_upl, ex5_ancestors),\n"
        "    perfmon.ancestor_svg(ex5_id_ex4, ex5_upl, ex5_ancestors)])])\n"
        "ex5_anc_size = new_table([string_col('Rows', [str(ex5_ancestors.size)])])\n"
    )
    print("ancestors log rows:", s.open_table("ex5_anc_size").to_arrow().to_pandas().Rows[0])
    print(s.open_table("ex5_ancestors").to_arrow().to_pandas().head(8).to_string(index=False))
    for _, row in s.open_table("ex5_dot_tbl").to_arrow().to_pandas().iterrows():
        path = f"examples/{row.Name}_graph.dot"
        with open(path, "w", encoding="utf-8") as f:
            f.write(row.Dot)
        with open(f"examples/{row.Name}_graph.svg", "w", encoding="utf-8") as f:
            f.write(row.Svg)
        print(f"wrote {path} (+ .svg): {row.Dot.count('->')} edges, {row.Dot.count('label')} nodes")
    hot = s.open_table("ex5_hot").to_arrow().to_pandas()
    hot["Description"] = hot["Description"].str.slice(0, 60)
    print("\nHottest nodes:\n" + hot.to_string(index=False))
finally:
    s.close()
