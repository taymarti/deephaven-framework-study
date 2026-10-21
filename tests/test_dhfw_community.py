"""
Exercise every dhfw emulation on an embedded Community server.
  .venv-server/Scripts/python tests/test_dhfw_community.py
Prints PASS/FAIL per check and writes tests/test_dhfw_community.json.
"""
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = pathlib.Path(__file__).with_name("test_dhfw_community.json")
PORT = int(os.environ.get("DH_PORT", "10005"))
WORK = pathlib.Path(tempfile.mkdtemp(prefix="dhfw_"))
os.environ.update({"DHFW_DATA_ROOT": str(WORK / "data"), "DHFW_CONTROLLER_ROOT": str(WORK / "repo"),
                   "DHFW_PQ_MAP": json.dumps({"Self": "self", "Local": f"localhost:{PORT}"}),
                   "DHFW_PLANT_CORE_VERSION": "41.1"})
R = {}


def check(name, fn):
    try:
        out = fn()
        R[name] = {"ok": True, "result": out}
        print("PASS", name, out, flush=True)
    except Exception as e:  # noqa: BLE001
        R[name] = {"ok": False, "error": " | ".join(str(e).splitlines()[:3])[:400]}
        print("FAIL", name, R[name]["error"], flush=True)


def jvm_args() -> list:
    args = ["-Xmx1g", "-DAuthHandlers=io.deephaven.auth.AnonymousAuthenticationHandler"]
    if os.name == "nt":  # same workarounds as server/run_server.py
        jh = pathlib.Path(os.environ["JAVA_HOME"])
        for d in (jh / "bin", jh / "bin" / "server"):
            os.environ["PATH"] = f"{d}{os.pathsep}{os.environ['PATH']}"
            os.add_dll_directory(str(d))
        args += ["-Dweb.storage.layout.directory=layouts", "-Dweb.storage.notebook.directory=notebooks"]
    return args


def main() -> None:
    from deephaven_server import Server
    Server(port=PORT, jvm_args=jvm_args()).start()

    import __main__
    from deephaven import empty_table, new_table, time_table
    from deephaven.column import double_col, string_col
    from deephaven.pandas import to_pandas
    import dhfw
    from dhfw import db
    from dhfw.database import LocalDatabase, UnsupportedOnCommunity

    def quotes(date, n=6, spacing_ms=500):
        return empty_table(n).update([f"Timestamp = parseInstant(`{date}T14:30:00 UTC`) + ii * {spacing_ms}L * 1_000_000L",
                                      "Sym = ii % 2 == 0 ? `AAPL` : `MSFT`", "Px = 100.0 + ii"])

    check("runtime", lambda: dhfw.runtime())

    def historical():
        db.add_partitioned_table_schema("Market", "Quotes", "Date", quotes("2026-10-19").head(0))
        db.add_table_partition("Market", "Quotes", "2026-10-19", quotes("2026-10-19"))
        db.add_table_partition("Market", "Quotes", "2026-10-20", quotes("2026-10-20"))
        h = db.historical_table("Market", "Quotes")
        dates = sorted(set(to_pandas(h)["Date"].astype(str)))
        assert h.size == 12 and dates == ["2026-10-19", "2026-10-20"], (h.size, dates)
        return {"rows": h.size, "dates": dates, "namespaces": db.namespaces(), "tables": db.table_names("Market")}
    check("historical_table_partitioned", historical)

    def user_table():
        db.add_unpartitioned_table("Desk", "Limits", new_table([string_col("Desk", ["Tech"]), double_col("Limit", [1e6])]))
        n = db.historical_table("Desk", "Limits").size
        deleted = db.delete_unpartitioned_table("Desk", "Limits")
        try:
            db.historical_table("Desk", "Limits")
            gone = False
        except KeyError:
            gone = True
        assert n == 1 and deleted and gone
        return {"rows": n, "deleted": deleted}
    check("user_table_roundtrip", user_table)

    def live_append():
        live = db.live_table("Market", "Quotes")  # empty, with the historical schema
        before = live.size
        db.append_live_table("Market", "Quotes", "2026-10-21", quotes("2026-10-21").update("Date = `2026-10-21`"))
        time.sleep(1.5)
        assert before == 0 and live.size == 6, (before, live.size)
        return {"before": before, "after": live.size, "columns": [c.name for c in live.columns]}
    check("live_table_append", live_append)

    def logging_():
        dhfw.log_table("Audit", "Events", new_table([string_col("Msg", ["start"])]), "2026-10-21")
        ticking = time_table("PT0.2s").update("Msg = `tick`").view("Msg")
        with dhfw.log_table_incremental("Audit", "Events2", ticking, "2026-10-21"):
            time.sleep(2.5)
        time.sleep(1.2)
        a, b = db.live_table("Audit", "Events").size, db.live_table("Audit", "Events2").size
        assert a == 1 and b >= 3, (a, b)
        return {"log_table_rows": a, "incremental_rows_in_2.5s": b}
    check("system_table_logger", logging_)

    def registered():
        db.register_live("Clock", "Heartbeat", time_table("PT0.5s"))
        t = db.live_table("Clock", "Heartbeat")
        time.sleep(2.2)
        assert t.size >= 2
        return {"rows_after_2.2s": t.size}
    check("register_live_feed", registered)

    def replay():
        os.environ["DHFW_REPLAY_DATE"] = "2026-10-20"
        try:
            rdb = LocalDatabase()
            t = rdb.live_table("Market", "Quotes")
            samples = []
            for _ in range(5):
                time.sleep(1.0)
                samples.append(t.size)
            assert samples[0] < 6 and samples[-1] == 6, samples
            return {"replayed_rows_each_second": samples, "today()": dhfw.today()}
        finally:
            os.environ.pop("DHFW_REPLAY_DATE")
    check("replay_mode", replay)

    def inputs():
        proto = new_table([string_col("Desk", ["x"]), double_col("Limit", [0.0])])
        db.add_input_table_schema_from_table("Desk", "LimitsInput", proto, ["Desk"])
        it = db.input_table("Desk", "LimitsInput")
        it.add(new_table([string_col("Desk", ["Tech", "Tech"]), double_col("Limit", [1.0, 2.0])]))
        time.sleep(1.2)
        df = to_pandas(it)
        assert len(df) == 1 and df["Limit"][0] == 2.0
        return df.to_dict("records")
    check("input_table_keyed", inputs)

    def remote():
        __main__.desk_risk = new_table([string_col("Desk", ["Tech", "Semis"]), double_col("Gross", [20_833.0, 10_475.0])])
        selfsub = dhfw.remote_table("Self", "desk_risk").subscribe(filters=["Gross > 15000"])
        net = dhfw.remote_table("Local", "desk_risk").subscribe(included_columns=["Desk"])
        snap = dhfw.remote_table("Local", "desk_risk").snapshot()
        via_uri = dhfw.resolve_uri("pq://Local/scope/desk_risk")
        time.sleep(1.5)
        sizes = {"self_filtered": selfsub.size, "barrage_columns": [c.name for c in net.columns],
                 "snapshot_rows": snap.size, "pq_uri_rows": via_uri.size}
        assert sizes == {"self_filtered": 1, "barrage_columns": ["Desk"], "snapshot_rows": 2, "pq_uri_rows": 2}, sizes
        return sizes
    check("remote_table_and_pq_uri", remote)

    def controller():
        pkg = WORK / "repo" / "shared" / "risk"
        pkg.mkdir(parents=True)
        (pkg / "limits.py").write_text("DEFAULT_LIMIT = 15_000.0\n", encoding="utf-8")
        (WORK / "repo" / "setup.py").write_text("configured = True\n", encoding="utf-8")
        dhfw.meta_import("controller")
        import importlib
        mod = importlib.import_module("controller.shared.risk.limits")
        g = {}
        dhfw.exec_script("setup.py", g)
        assert mod.DEFAULT_LIMIT == 15_000.0 and g["configured"]
        return {"imported": mod.__name__, "exec_script": g["configured"]}
    check("controller_import", controller)

    check("acl_noop", lambda: dhfw.apply_acl(__main__.desk_risk, lambda t, acl: None).size)

    def unsupported():
        try:
            db.append_live_table_incremental("Market", "Quotes", "2026-10-21", None)
        except UnsupportedOnCommunity as e:
            return str(e)
        raise AssertionError("expected UnsupportedOnCommunity")
    check("unsupported_is_explicit", unsupported)

    R["summary"] = f"{sum(1 for v in R.values() if isinstance(v, dict) and v.get('ok'))}/{len(R)} passed"
    OUT.write_text(json.dumps(R, indent=2, default=str), encoding="utf-8")
    print(R["summary"])
    shutil.rmtree(WORK, ignore_errors=True)
    os._exit(0)


if __name__ == "__main__":
    main()
