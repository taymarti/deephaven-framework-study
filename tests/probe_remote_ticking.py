"""
Can a local Community app get a TICKING table from a remote Deephaven server?

Remote: any server on localhost:10000 with ticking tables (here the dhapp demo:
  .venv-server/Scripts/python server/run_server.py --app-dir examples/mm_app.d).
Local: this script, an embedded server on DH_PORT (default 10007).

  A  barrage_session(...).subscribe(b"s/<name>")   a remote scope table, ticking locally
  B  pydeephaven shapes it remotely (filter, view), publishes it under a shared
     ticket, and the local server subscribes to that ticket: only the shaped rows travel
  C  local tables built on the remote ones tick too (they are ordinary nodes)
  D  what happens to B when the pydeephaven session closes (shared tickets die with it)

Run:  .venv-server/Scripts/python tests/probe_remote_ticking.py
"""
import json
import os
import pathlib
import time

OUT = pathlib.Path(__file__).with_name("probe_remote_ticking.json")
REMOTE_HOST, REMOTE_PORT = os.environ.get("REMOTE_HOST", "localhost"), int(os.environ.get("REMOTE_PORT", "10000"))
R = {}


def jvm_args() -> list:
    args = ["-Xmx1g", "-DAuthHandlers=io.deephaven.auth.AnonymousAuthenticationHandler"]
    if os.name == "nt":
        jh = pathlib.Path(os.environ["JAVA_HOME"])
        for d in (jh / "bin", jh / "bin" / "server"):
            os.environ["PATH"] = f"{d}{os.pathsep}{os.environ['PATH']}"
            os.add_dll_directory(str(d))
        args += ["-Dweb.storage.layout.directory=layouts", "-Dweb.storage.notebook.directory=notebooks"]
    return args


def check(name, fn):
    try:
        R[name] = {"ok": True, "result": fn()}
        print("PASS", name, json.dumps(R[name]["result"], default=str)[:500], flush=True)
    except Exception as e:  # noqa: BLE001
        R[name] = {"ok": False, "error": " | ".join(str(e).splitlines()[:4])[:600]}
        print("FAIL", name, R[name]["error"], flush=True)


def sizes(t, n=4, dt=1.0):
    out = []
    for _ in range(n):
        out.append(t.size)
        time.sleep(dt)
    return out


def main() -> None:
    from deephaven_server import Server
    Server(port=int(os.environ.get("DH_PORT", "10007")), jvm_args=jvm_args()).start()

    from deephaven import agg
    from deephaven.barrage import barrage_session

    bs = barrage_session(host=REMOTE_HOST, port=REMOTE_PORT, auth_type="Anonymous")
    state = {}

    def direct():
        orders = bs.subscribe(b"s/mm_orders")
        state["orders"] = orders
        s = sizes(orders)
        assert orders.is_refreshing and s[-1] > s[0], s
        return {"is_refreshing": orders.is_refreshing, "rows_each_second": s}
    check("A_barrage_subscribe_scope_ticket", direct)

    def derived():
        local = state["orders"].agg_by([agg.count_("N"), agg.sum_("OrderQty")], by="Sym")
        from deephaven.pandas import to_pandas
        before = local.size
        n0 = int(to_pandas(local)["N"].sum())
        n1, waited = n0, 0
        while n1 == n0 and waited < 15:  # orders arrive only when a target flips
            time.sleep(1)
            waited += 1
            n1 = int(to_pandas(local)["N"].sum())
        assert n1 > n0, (n0, n1)
        return {"symbols": before, "orders_counted_then": n0, "orders_counted_later": n1, "seconds_waited": waited}
    check("C_local_graph_on_remote_table_ticks", derived)

    def shaped():
        from pydeephaven import Session
        from pydeephaven.ticket import SharedTicket
        s = Session(host=REMOTE_HOST, port=REMOTE_PORT, auth_type="Anonymous")
        remote = s.open_table("mm_orders").where("Sym == `AAPL`").view(["Timestamp", "Sym", "OrderQty", "FillPx"])
        ticket = SharedTicket.random_ticket()
        s.publish_table(ticket, remote)  # the shaping ran on the REMOTE server
        aapl = bs.subscribe(ticket.bytes)
        state["pyd"], state["aapl"], state["ticket"] = s, aapl, ticket
        sz = sizes(aapl, n=4, dt=1.5)
        cols = [c.name for c in aapl.columns]
        from deephaven.pandas import to_pandas
        syms = set(to_pandas(aapl)["Sym"])
        assert cols == ["Timestamp", "Sym", "OrderQty", "FillPx"] and syms <= {"AAPL"} and sz[-1] >= sz[0], (cols, syms, sz)
        return {"columns": cols, "symbols_received": sorted(syms), "rows_each_1.5s": sz}
    check("B_pydeephaven_shaped_shared_ticket", shaped)

    def after_close():
        aapl, s = state["aapl"], state["pyd"]
        before = sizes(aapl, n=3, dt=2.0)
        s.close()
        time.sleep(1)
        try:
            after = sizes(aapl, n=5, dt=2.0)
            failed = bool(aapl.j_table.isFailed())
        except Exception as e:  # noqa: BLE001
            after, failed = f"error: {e}"[:200], True
        # a NEW subscription to the dead ticket should fail if the ticket died with its publisher
        try:
            bs.subscribe(state["ticket"].bytes)
            resubscribe = "succeeded"
        except Exception as e:  # noqa: BLE001
            resubscribe = "failed: " + str(e).splitlines()[0][:150]
        return {"rows_every_2s_before_close": before, "rows_every_2s_after_close": after,
                "table_failed": failed, "new_subscription_after_close": resubscribe}
    check("D_shared_ticket_after_pydeephaven_session_closes", after_close)

    R["summary"] = f"{sum(v['ok'] for v in R.values())}/{len(R)} passed"
    OUT.write_text(json.dumps(R, indent=2, default=str), encoding="utf-8")
    print(R["summary"])
    os._exit(0)


if __name__ == "__main__":
    main()
