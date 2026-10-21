// Build "Deephaven as an Application Framework" (structured pptxgenjs deck).
//   node build_deck.js            -> deck/Deephaven as an Application Framework.pptx
const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");
const sharp = require("sharp");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const fa = require("react-icons/fa");

const SKILL = "C:\\Users\\tc-ma\\AppData\\Roaming\\Claude\\local-agent-mode-sessions\\skills-plugin\\8153a082-4ad3-4594-a9cc-b03af06b5a2c\\94127047-04f8-4d18-9212-088b5b97d374\\skills\\pptx";
const { applyTheme } = require(path.join(SKILL, "scripts", "apply_theme.js"));
const ASSETS = path.join(__dirname, "assets");
const OUT = path.join(__dirname, "Deephaven as an Application Framework.pptx");

// Colours carry meaning across the deck: blue = engine, orange = our code,
// green = sources, amber = caution. They match the diagrams in the docs.
const THEME = {
  name: "Deephaven Runtime",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "17212B", lt1: "FFFFFF", dk2: "0F3D5E", lt2: "EEF2F6",
    accent1: "2F6FDB", accent2: "E8743B", accent3: "2E9E6A", accent4: "E0A526",
    accent5: "5F6F82", accent6: "8A5CC2", hlink: "2F6FDB", folHlink: "5F6F82",
  },
};
const HEX = THEME.colors;

const W = 13.333, H = 7.5, MX = 0.6, CW = W - 2 * MX; // content width 12.13
const TOP = 1.45, BOTTOM = 6.85;

async function iconPng(Icon, color) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Icon, { size: 256, color: "#" + color }));
  const buf = await sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

// Diagram screenshots carry their own title; crop it off (the slide title states the message).
async function diagram(name, cropTop) {
  const file = path.join(ASSETS, name + ".png");
  const meta = await sharp(file).metadata();
  const buf = await sharp(file).extract({ left: 0, top: cropTop, width: meta.width, height: meta.height - cropTop - 8 }).png().toBuffer();
  const m2 = await sharp(buf).metadata();
  return { data: "image/png;base64," + buf.toString("base64"), ratio: m2.width / m2.height };
}

function fit(img, box) { // largest w,h of the image's ratio inside box, centred on the box's x-axis if asked
  let w = box.w, h = w / img.ratio;
  if (h > box.h) { h = box.h; w = h * img.ratio; }
  const x = box.align === "center" ? box.x + (box.w - w) / 2 : box.x;
  return { x, y: box.y, w, h };
}

async function main() {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.author = "Taylor";
  pres.title = "Deephaven as an Application Framework";
  pres.subject = "How the Deephaven runtime behaves, tested on Community 42.6";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = pres.SchemeColor;

  // ---- layouts --------------------------------------------------------------
  const footer = { text: { text: "Deephaven as an application framework \u00b7 tested on Community 42.6",
    options: { x: MX, y: 7.02, w: 9, h: 0.3, fontSize: 10, color: C.accent5, margin: 0 } } };
  const slideNumber = { x: W - MX - 0.6, y: 7.02, w: 0.6, h: 0.3, fontSize: 10, color: C.accent5, align: "right" };
  const slideNumberDark = { x: W - MX - 0.6, y: 7.02, w: 0.6, h: 0.3, fontSize: 10, color: C.background2, align: "right" };

  pres.defineSlideMaster({
    title: "TITLE_DARK", background: { color: C.text2 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.05, w: 11.7, h: 1.6, fontSize: 46, bold: true, color: C.background1, align: "left", valign: "bottom", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 3.85, w: 11.2, h: 1.1, fontSize: 22, color: C.background2, valign: "top", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "meta", type: "body", x: 0.8, y: 5.95, w: 8, h: 0.5, fontSize: 14, color: C.background2, margin: 0 }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "SECTION_DARK", background: { color: C.text2 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.55, w: 11.7, h: 1.2, fontSize: 40, bold: true, color: C.background1, align: "left", valign: "bottom", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 3.95, w: 11.2, h: 0.9, fontSize: 20, color: C.background2, valign: "top", margin: 0 }, text: "" } },
    ],
    slideNumber: slideNumberDark,
  });
  pres.defineSlideMaster({
    title: "CONTENT", background: { color: C.background1 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.38, w: CW, h: 0.85, fontSize: 30, bold: true, color: C.text2, align: "left", valign: "middle", margin: 0 }, text: "" } },
      footer,
    ],
    slideNumber,
  });
  pres.defineSlideMaster({
    title: "CLOSING_DARK", background: { color: C.text2 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.45, w: CW, h: 0.85, fontSize: 32, bold: true, color: C.background1, align: "left", valign: "middle", margin: 0 }, text: "" } },
    ],
    slideNumber: slideNumberDark,
  });

  // ---- shared pieces --------------------------------------------------------
  const ICON = {
    graph: await iconPng(fa.FaProjectDiagram, "FFFFFF"), layers: await iconPng(fa.FaLayerGroup, "FFFFFF"),
    clock: await iconPng(fa.FaClock, "FFFFFF"), sitemap: await iconPng(fa.FaSitemap, "FFFFFF"),
    warn: await iconPng(fa.FaExclamationTriangle, "FFFFFF"), redo: await iconPng(fa.FaRedoAlt, "FFFFFF"),
    ghost: await iconPng(fa.FaGhost, "FFFFFF"), power: await iconPng(fa.FaPowerOff, "FFFFFF"),
    check: await iconPng(fa.FaCheckCircle, HEX.accent3), cross: await iconPng(fa.FaTimesCircle, HEX.accent2),
    plug: await iconPng(fa.FaPlug, "FFFFFF"), stream: await iconPng(fa.FaStream, "FFFFFF"),
    thread: await iconPng(fa.FaCodeBranch, "FFFFFF"), door: await iconPng(fa.FaDoorOpen, "FFFFFF"),
  };
  const IMG = {
    space: await diagram("space", 72), anatomy: await diagram("worker_anatomy", 72),
    barrage: await diagram("barrage", 72), clocks: await diagram("two_clocks", 64),
    time: await diagram("time", 64), cycle: await diagram("cycle", 72),
    embedded: await diagram("embedded", 64), hosting: await diagram("hosting", 64),
    hybrid: await diagram("hybrid", 72), ui: await diagram("ui_routes", 72),
  };

  const card = (s, o) => s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: o.x, y: o.y, w: o.w, h: o.h, rectRadius: 0.08, objectName: o.name,
    fill: { color: o.fill || C.background2 }, line: { color: o.line || o.fill || C.background2, width: o.lineW || 0.75 },
  });
  const iconDot = (s, o) => {
    s.addShape(pres.shapes.OVAL, { x: o.x, y: o.y, w: o.d, h: o.d, fill: { color: o.color }, line: { color: o.color }, objectName: o.name + " circle" });
    s.addImage({ data: o.icon, x: o.x + o.d * 0.25, y: o.y + o.d * 0.25, w: o.d * 0.5, h: o.d * 0.5, altText: o.name + " icon", objectName: o.name + " icon" });
  };
  const text = (s, t, o) => s.addText(t, Object.assign({ isTextBox: true, margin: 0, valign: "top", fontSize: 15, color: C.text1 }, o));
  const image = (s, img, box, name) => s.addImage(Object.assign({ data: img.data, altText: name, objectName: name }, fit(img, box)));
  const stat = (s, o) => { // big number + label
    text(s, o.value, { x: o.x, y: o.y, w: o.w, h: o.vh || 0.75, fontSize: o.size || 40, bold: true, color: o.color || C.accent1, fontFace: THEME.headFontFace, valign: "bottom", objectName: o.name + " value" });
    text(s, o.label, { x: o.x, y: o.y + (o.vh || 0.75) + 0.05, w: o.w, h: o.lh || 0.7, fontSize: o.lsize || 14, color: C.text1, objectName: o.name + " label" });
  };
  const content = (section, title, notes) => {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
    s.addText(title, { placeholder: "title" });
    if (notes) s.addNotes(notes);
    return s;
  };
  const divider = (section, title, body, notes) => {
    const s = pres.addSlide({ masterName: "SECTION_DARK", sectionTitle: section });
    s.addText(title, { placeholder: "title" });
    s.addText(body, { placeholder: "body" });
    if (notes) s.addNotes(notes);
    return s;
  };
  const tableOpts = (o) => Object.assign({ fontSize: 12, fontFace: THEME.bodyFontFace, color: HEX.dk1, valign: "middle", margin: [0.05, 0.08, 0.05, 0.08],
    border: { type: "solid", pt: 0.75, color: "C9D3DE" } }, o);
  const head = (cells) => cells.map((t) => ({ text: t, options: { bold: true, color: HEX.lt1, fill: { color: HEX.dk2 } } }));

  // ===========================================================================
  pres.addSection({ title: "Overview" });
  {
    const s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Overview" });
    s.addText("Deephaven as an Application Framework", { placeholder: "title" });
    s.addText("How the runtime really behaves across components, from startup to shutdown, and what that means for where our code should live", { placeholder: "body" });
    s.addText("Taylor \u00b7 October 2026 \u00b7 every claim tested on Deephaven Community 42.6", { placeholder: "meta" });
    s.addNotes("Purpose: share what we learned building and probing Deephaven applications, and propose where application code should live on the plant. Everything marked verified was observed in a test in our repo; Enterprise points come from Deephaven's documentation.");
  }
  {
    const s = content("Overview", "The short answer", "Four messages. One: Deephaven is a declarative dataflow engine, not an event loop. Two: a worker has one Python namespace and publishes what is named in it. Three: the biggest discovery is that the clock does not have to be Deephaven's. Four: place work by its shape.");
    const items = [
      { icon: ICON.graph, color: C.accent1, head: "A declarative engine", body: "Scripts declare a graph of tables once; the update graph keeps it current, one consistent ~1 s cycle at a time." },
      { icon: ICON.layers, color: C.accent3, head: "One namespace, published", body: "Console commands, run_script and app-mode scripts share one global scope; every exportable name is a field clients can open." },
      { icon: ICON.clock, color: C.accent2, head: "The clock can be ours", body: "An event-driven update graph advances only when our code calls requestRefresh(): one call, one checkpoint." },
      { icon: ICON.sitemap, color: C.text2, head: "Place work by its shape", body: "Table work in PQs; stateful applications beside them as a subprocess, a thread-hosted service or a client." },
    ];
    items.forEach((it, i) => {
      const x = MX + (i % 2) * (CW / 2 + 0.15), y = TOP + 0.1 + Math.floor(i / 2) * 2.65, w = CW / 2 - 0.15, h = 2.45;
      card(s, { x, y, w, h, name: `message ${i + 1}` });
      iconDot(s, { x: x + 0.35, y: y + 0.4, d: 0.8, color: it.color, icon: it.icon, name: `message ${i + 1}` });
      text(s, it.head, { x: x + 1.4, y: y + 0.4, w: w - 1.7, h: 0.5, fontSize: 21, bold: true, color: C.text2, fontFace: THEME.headFontFace, objectName: `message ${i + 1} title` });
      text(s, it.body, { x: x + 1.4, y: y + 1.0, w: w - 1.7, h: 1.25, fontSize: 16, objectName: `message ${i + 1} body` });
    });
  }
  {
    const s = content("Overview", "How we know: every claim traces to a test", "We built a mock market-making book twice, once with deephaven.ui and once in React, then ran a ladder of experiments and probes. The ledger file lists each verified fact with the test behind it. Nine claims we made early on turned out to be wrong and are corrected in the appendix.");
    const stats = [
      { value: "39", label: "verified facts in the ledger, each with its test or source", color: C.accent1 },
      { value: "9", label: "earlier claims corrected by later tests", color: C.accent2 },
      { value: "2", label: "UI routes built on one server: deephaven.ui and React", color: C.accent3 },
      { value: "3", label: "ways to host Deephaven next to our framework, all run", color: C.text2 },
    ];
    stats.forEach((st, i) => stat(s, { x: MX + i * (CW / 4), y: 1.5, w: CW / 4 - 0.4, value: st.value, label: st.label, color: st.color, size: 66, vh: 1.2, lh: 0.95, lsize: 16, name: `stat ${i + 1}` }));
    card(s, { x: MX, y: 4.3, w: CW, h: 2.0, name: "method box" });
    text(s, [
      { text: "The evidence", options: { bold: true, fontSize: 17, color: C.text2, breakLine: true } },
      { text: "A ladder of experiments (lifecycle, declarative DAG, listener hooks, multi-feed checkpoints), probes of scopes, fields and tickets, runtime probes (executors, an event-driven clock, Deephaven on a thread, Deephaven as a subprocess), and an introspection module run against a live worker.", options: { fontSize: 15, breakLine: true } },
      { text: "Community 42.6 in Docker and as the pip server natively on Windows. Enterprise behaviour comes from Deephaven's documentation and is marked as such.", options: { fontSize: 15, italic: true, color: C.accent5 } },
    ], { x: MX + 0.35, y: 4.5, w: CW - 0.7, h: 1.65, paraSpaceAfter: 4, objectName: "method text" });
  }

  // ===========================================================================
  pres.addSection({ title: "The runtime in space" });
  divider("The runtime in space", "1   The runtime in space", "What lives inside one worker, how it is named, and how clients and other workers reach it",
    "First the static picture: the parts of a worker and the boundaries between them.");
  {
    const s = content("The runtime in space", "Everything happens inside one worker process",
      "Read top to bottom: inputs feed the update graph and outputs hang off it. By default there is one periodic graph; code can add an event-driven one. The global scope and field registry are the naming layer. Below them are the threads that actually run code, and at the bottom one port that every client uses. Dashed orange is code we run outside the engine's control.");
    image(s, IMG.space, { x: MX, y: TOP - 0.05, w: 6.6, h: BOTTOM - TOP + 0.05 }, "Diagram: one worker with inputs, update graph, outputs, scopes, threads and port");
    const pts = [
      { icon: ICON.stream, color: C.accent3, head: "Inputs feed one graph", body: "Time tables, Kafka, files, input tables, Python feeds and Barrage subscriptions all become source nodes." },
      { icon: ICON.thread, color: C.accent2, head: "Our threads are guests", body: "Engine threads run cycles and listeners; any thread we start needs an execution context handed to it." },
      { icon: ICON.door, color: C.accent1, head: "One port for everyone", body: "The IDE, deephaven.ui, React apps, Python clients and other workers all come through port 10000." },
    ];
    pts.forEach((p, i) => {
      const y = TOP + 0.15 + i * 1.75;
      iconDot(s, { x: 7.65, y, d: 0.7, color: p.color, icon: p.icon, name: `point ${i + 1}` });
      text(s, p.head, { x: 8.6, y: y - 0.02, w: 4.1, h: 0.45, fontSize: 19, bold: true, color: C.text2, objectName: `point ${i + 1} title` });
      text(s, p.body, { x: 8.6, y: y + 0.45, w: 4.1, h: 1.1, fontSize: 15, objectName: `point ${i + 1} body` });
    });
  }
  {
    const s = content("The runtime in space", "A worker publishes fields; clients reach them through tickets",
      "Fields are the worker's interface: named, typed objects from every application, including the scope application. Clients never see Python variables, only tickets. Export tickets are the unnamed objects a session creates, such as a sorted grid. Shared tickets die with the session that published them; bind_table makes a durable name instead.");
    image(s, IMG.anatomy, { x: MX, y: TOP, w: 7.3, h: 4.8 }, "Diagram: global scope, application-mode apps, field registry, client sessions and engine inside one worker");
    const rows = [head(["Ticket", "Bytes", "Lives until"]),
      ["Scope", "s/<name>", "the name is unbound"],
      ["Application", "a/<app>/f/<field>", "the app drops it"],
      ["Export", "e + 4-byte number", "released or session ends"],
      ["Shared", "h + 16 random bytes", "the publisher's session ends"]];
    s.addTable(rows, tableOpts({ x: 8.2, y: TOP + 0.1, w: 4.53, colW: [1.15, 1.75, 1.63], fontSize: 12, rowH: 0.42, objectName: "ticket table" }));
    card(s, { x: 8.2, y: 4.05, w: 4.53, h: 2.05, fill: C.background2, name: "fields facts" });
    text(s, [
      { text: "Tested", options: { bold: true, color: C.text2, fontSize: 16, breakLine: true } },
      { text: "Underscore names are published too", options: { bullet: true, breakLine: true } },
      { text: "Two apps may use the same field name", options: { bullet: true, breakLine: true } },
      { text: "bind_table outlives the binding session", options: { bullet: true, breakLine: true } },
      { text: "A shared ticket dies with its publisher", options: { bullet: true } },
    ], { x: 8.45, y: 4.2, w: 4.1, h: 1.8, fontSize: 15, paraSpaceAfter: 4, objectName: "fields facts text" });
  }
  {
    const s = content("The runtime in space", "Live tables travel as change sets, not copies",
      "Barrage is Arrow Flight extended for ticking data: a snapshot, then each cycle's added, removed, modified and shifted rows. The consumer replays those onto its own copy, so it ticks too. Every grid in both of our UIs is a Barrage viewport subscription.");
    image(s, IMG.barrage, { x: MX, y: TOP, w: CW, h: 3.6, align: "center" }, "Diagram: producer worker, Barrage messages and consumer copy");
    const cs = [
      { head: "Viewports", body: "Subscribe to rows 0\u201349 of two columns; only visible, changed values travel." },
      { head: "One message, one step", body: "Each message is a coherent update-graph step on the producer, never half a cycle." },
      { head: "Coalescing", body: "A slow subscriber gets several cycles merged into one message, not a backlog." },
    ];
    cs.forEach((c, i) => {
      const x = MX + i * (CW / 3 + 0.05), w = CW / 3 - 0.1;
      card(s, { x, y: 5.2, w, h: 1.55, name: `barrage ${i + 1}` });
      text(s, c.head, { x: x + 0.25, y: 5.32, w: w - 0.5, h: 0.4, fontSize: 17, bold: true, color: C.accent1, objectName: `barrage ${i + 1} title` });
      text(s, c.body, { x: x + 0.25, y: 5.75, w: w - 0.5, h: 0.9, fontSize: 14, objectName: `barrage ${i + 1} body` });
    });
  }
  {
    const s = content("The runtime in space", "Across workers, each side keeps its own clock",
      "A table shared between PQs is a Barrage subscription, so it ticks on the consumer's clock. Inside one worker, a join is consistent at every step; across workers, each side is consistent with itself. We saw the same thing locally: resolving a dh+plain URI created a Barrage source node, even pointing at the same server.");
    image(s, IMG.clocks, { x: MX, y: TOP + 0.2, w: 8.1, h: 4.6 }, "Diagram: producer and consumer clocks with a Barrage message between them");
    card(s, { x: 9.0, y: TOP + 0.2, w: 3.73, h: 1.75, fill: C.text2, name: "latency card" });
    text(s, [
      { text: "Cross-worker latency", options: { bold: true, color: C.background1, fontSize: 17, breakLine: true } },
      { text: "producer wait + network + consumer wait", options: { color: C.background1, fontSize: 20, fontFace: THEME.headFontFace } },
    ], { x: 9.25, y: TOP + 0.38, w: 3.25, h: 1.45, paraSpaceAfter: 6, objectName: "latency text" });
    text(s, [
      { text: "Enterprise (docs)", options: { bold: true, color: C.text2, breakLine: true } },
      { text: "pq://RiskEngine/scope/positions", options: { breakLine: true } },
      { text: " ", options: { fontSize: 6, breakLine: true } },
      { text: "Community (tested)", options: { bold: true, color: C.text2, breakLine: true } },
      { text: "dh+plain://host:port/app/<id>/field/<name>", options: { breakLine: true } },
      { text: " ", options: { fontSize: 6, breakLine: true } },
      { text: "Resolving either adds a Barrage source node to the consumer's graph, even when it points at the same server.", options: { italic: true, color: C.accent5 } },
    ], { x: 9.0, y: 3.85, w: 3.73, h: 2.9, fontSize: 14, objectName: "uri notes" });
  }

  // ===========================================================================
  pres.addSection({ title: "The runtime in time" });
  divider("The runtime in time", "2   The runtime in time", "Startup, steady-state cycles and shutdown, across every thread and process",
    "Now the same application over time: what runs once, what runs every cycle, and how it ends.");
  {
    const s = content("The runtime in time", "Startup builds the graph once; then each cycle drives it",
      "Read a column top to bottom for one moment. The update graph starts cycling before the app scripts finish. Clients can connect only after the port opens. Rows from our thread wait for the next tick, flow through the graph, and reach clients as one delta. Shutdown is only as orderly as our own cleanup.");
    image(s, IMG.time, { x: MX, y: TOP - 0.05, w: 9.6, h: BOTTOM - TOP + 0.05 }, "Swimlane diagram: startup, steady state and shutdown across process, threads, clients and subprocess");
    const notes = [
      { head: "Once", body: "config, plugins, Python, app scripts, then the port opens", color: C.accent1 },
      { head: "Every tick", body: "refresh sources, propagate, run listeners, publish deltas", color: C.accent3 },
      { head: "At the end", body: "stop events, stop listeners, flush sinks, close sessions", color: C.accent2 },
    ];
    notes.forEach((n, i) => {
      const y = TOP + 0.15 + i * 1.75;
      text(s, n.head, { x: 10.45, y, w: 2.3, h: 0.45, fontSize: 19, bold: true, color: n.color, objectName: `phase ${i + 1} title` });
      text(s, n.body, { x: 10.45, y: y + 0.45, w: 2.3, h: 1.15, fontSize: 14, objectName: `phase ${i + 1} body` });
    });
  }
  {
    const s = content("The runtime in time", "Each cycle is one consistent checkpoint",
      "Every cycle refreshes all sources, propagates changes in dependency order, and publishes one step. Our listeners run inside the propagate step, so a slow one delays every table on that graph. Measured: ticks half a second apart were processed in pairs. Rows pushed from Python waited up to a second. One merged listener saw all three feeds at once.");
    image(s, IMG.cycle, { x: MX, y: TOP, w: CW, h: 4.3, align: "center" }, "Diagram: idle, refresh sources, propagate, complete");
    const st = [
      { value: "~1 s", label: "default cycle; ticks 0.5 s apart arrived in pairs", color: C.accent1 },
      { value: "\u2264 1,000 ms", label: "rows pushed from Python waited for the next cycle", color: C.accent2 },
      { value: "1 callback", label: "per cycle, with ~4 quotes, 4\u20135 orders, 1\u20132 signals", color: C.accent3 },
    ];
    st.forEach((x, i) => stat(s, { x: MX + i * (CW / 3), y: 5.75, w: CW / 3 - 0.3, value: x.value, label: x.label, color: x.color, size: 28, vh: 0.5, lh: 0.55, lsize: 14, name: `cycle stat ${i + 1}` }));
  }
  {
    const s = content("The runtime in time", "The clock can be ours: an event-driven update graph",
      "This is the finding that matters most for our framework. We built an event-driven update graph from Python, put a feed and a listener on it, and pushed three rows. For a second and a half nothing happened. One requestRefresh delivered all three as a single step: A equals 600, the sum of 100, 200 and 300. Our synchronizer decides when a checkpoint happens; Deephaven makes it consistent.");
    const steps = [
      { head: "Push three rows", body: "A: 100, 200, 300", foot: "1.5 s idle: still step 2, 0 callbacks", fill: C.background2, color: C.text2 },
      { head: "requestRefresh()", body: "our checkpoint", foot: "one call from our code", fill: C.accent2, color: C.background1 },
      { head: "One step", body: "1 callback: A = 600", foot: "step 3: all three pushes together", fill: C.background2, color: C.text2 },
      { head: "Again", body: "A 5, B 7 + refresh", foot: "step 4: 1 more callback", fill: C.background2, color: C.text2 },
    ];
    const bw = 2.6, gap = (CW - 4 * bw) / 3;
    steps.forEach((st, i) => {
      const x = MX + i * (bw + gap), y = TOP + 0.2;
      card(s, { x, y, w: bw, h: 2.05, fill: st.fill, name: `clock step ${i + 1}` });
      text(s, st.head, { x: x + 0.2, y: y + 0.18, w: bw - 0.4, h: 0.5, fontSize: 19, bold: true, color: st.color, fontFace: THEME.headFontFace, objectName: `clock step ${i + 1} title` });
      text(s, st.body, { x: x + 0.2, y: y + 0.75, w: bw - 0.4, h: 0.6, fontSize: 16, bold: true, color: st.color, objectName: `clock step ${i + 1} body` });
      text(s, st.foot, { x: x + 0.2, y: y + 1.35, w: bw - 0.4, h: 0.55, fontSize: 13, color: st.color, objectName: `clock step ${i + 1} note` });
      if (i < 3) s.addShape(pres.shapes.LINE, { x: x + bw + 0.08, y: y + 1.02, w: gap - 0.16, h: 0, line: { color: HEX.accent5, width: 2, endArrowType: "triangle" }, objectName: `clock arrow ${i + 1}` });
    });
    card(s, { x: MX, y: 4.0, w: 7.75, h: 2.75, fill: "F4F6F8", line: "D5DCE4", name: "code card" });
    const code = [
      "ug  = EventDrivenUpdateGraph.newBuilder(\"synchronizer_clock\").build()",
      "ctx = ExecutionContext(j_exec_ctx=",
      "          get_exec_ctx().j_exec_ctx.withUpdateGraph(ug))",
      "with ctx:",
      "    feed, pub = table_publisher(\"sync_feed\", cols,",
      "                    update_graph=UpdateGraph(j_update_graph=ug))",
      "    sums = feed.agg_by([agg.sum_(\"Qty\")], by=\"Sym\")",
      "    listen(sums, on_checkpoint)",
      "pub.add(rows)        # x3: nothing moves on its own",
      "ug.requestRefresh()  # our checkpoint",
    ];
    text(s, code.map((line, i) => ({ text: line, options: i < code.length - 1 ? { breakLine: true } : {} })),
      { x: MX + 0.25, y: 4.15, w: 7.3, h: 2.5, fontFace: "Courier New", fontSize: 11, color: C.text1, valign: "middle", objectName: "code text" });
    text(s, [
      { text: "What it buys a framework", options: { bold: true, fontSize: 18, color: C.text2, breakLine: true } },
      { text: "Checkpoints on our cadence, not a fixed second", options: { bullet: true, breakLine: true } },
      { text: "Engine-consistent joins and aggregations at each one", options: { bullet: true, breakLine: true } },
      { text: "Listeners that fire exactly once per checkpoint", options: { bullet: true, breakLine: true } },
      { text: "Tested on Community 42.6; whether PQs allow it is a vendor question", options: { italic: true, color: C.accent5, fontSize: 13 } },
    ], { x: 8.75, y: 4.05, w: 3.98, h: 2.7, fontSize: 15, paraSpaceAfter: 6, objectName: "clock benefits" });
  }
  {
    const s = content("The runtime in time", "Threads: only some carry a real execution context",
      "Every table operation runs under an execution context: query scope, compiler, update graph, auth. Contexts are per thread. The script session and the thread that started the server have the real one. On our own threads, get_exec_ctx returns a static-only context, and building a ticking table fails. We measured exactly that on the host's main thread.");
    const rows = [head(["Thread", "Runs", "Execution context"]),
      ["Thread that starts the server", "startup, application-mode scripts", "real (systemic)"],
      ["Script session (serial)", "console and run_script commands", "real (systemic)"],
      ["Update threads", "cycles, propagation, our listeners", "engine"],
      ["Server executors", "submit_task work on JVM threads", "server"],
      [{ text: "Our threads", options: { bold: true, color: HEX.accent2 } }, "feeds, timers, an asyncio loop", { text: "static-only until we pass one in", options: { bold: true, color: HEX.accent2 } }],
      ["Our subprocesses", "anything", "none: client access only"]];
    s.addTable(rows, tableOpts({ x: MX, y: TOP + 0.1, w: 7.9, colW: [2.55, 2.85, 2.5], fontSize: 13, rowH: 0.55, objectName: "thread table" }));
    card(s, { x: 8.85, y: TOP + 0.1, w: 3.88, h: 3.85, fill: "FBF3E2", line: HEX.accent4, lineW: 1.25, name: "context warning" });
    iconDot(s, { x: 9.1, y: TOP + 0.3, d: 0.6, color: C.accent4, icon: ICON.warn, name: "context warning" });
    text(s, [
      { text: "Measured", options: { bold: true, fontSize: 17, color: C.text2, breakLine: true } },
      { text: "get_exec_ctx() on the host's main thread \u2192 static-only \u2192 UpdateGraphConflictException", options: { breakLine: true } },
      { text: " ", options: { breakLine: true, fontSize: 6 } },
      { text: "Fix", options: { bold: true, fontSize: 17, color: C.text2, breakLine: true } },
      { text: "Capture the context where it is real (inside run_script, or on the server's thread), pass it in, and enter it with ", options: {} },
      { text: "with ctx:", options: { fontFace: "Courier New" } },
    ], { x: 9.1, y: TOP + 1.0, w: 3.4, h: 2.85, fontSize: 15, objectName: "context warning text" });
  }
  {
    const s = content("The runtime in time", "Python listeners are the costliest nodes in the graph",
      "From the engine's own performance log for experiments 2 to 4. The two Python listeners cost about 195 milliseconds per interval each, against 80 for the costliest Java operation and 3 to 36 for the rest. Table logic belongs in the query language; Python belongs at the edges.");
    const cats = ["ex4 synchronizer", "ex3 SignalTracker", "update_by (rolling)", "ex2_trades update", "ex2_vwap agg_by", "ex4_orders feed", "ex2_bars agg_by", "natural_join", "time_table 0.1 s"];
    const py = [197.1, 195.0, 0, 0, 0, 0, 0, 0, 0];
    const jv = [0, 0, 80.5, 36.0, 26.0, 21.2, 19.2, 10.0, 4.2];
    s.addChart(pres.charts.BAR, [
      { name: "Python listener", labels: cats, values: py },
      { name: "Java table operation", labels: cats, values: jv },
    ], {
      x: MX, y: TOP, w: 8.4, h: 5.3, barDir: "bar", barGrouping: "stacked", catAxisOrientation: "maxMin",
      chartColors: [HEX.accent2, HEX.accent1], showLegend: true, legendPos: "b", legendFontSize: 12, legendFontFace: "+mn-lt",
      showValue: false, catAxisLabelFontSize: 12, valAxisLabelFontSize: 11, catAxisLabelColor: HEX.dk1, valAxisLabelColor: HEX.accent5,
      catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", valAxisTitle: "engine ms per interval (~1 min)", showValAxisTitle: true,
      valAxisTitleFontSize: 11, valAxisTitleColor: HEX.accent5, valGridLine: { color: "DDE3EA", size: 0.75 }, catGridLine: { style: "none" },
      valAxisMinVal: 0, valAxisMaxVal: 200, valAxisMajorUnit: 50, showTitle: false, objectName: "cost chart",
    });
    stat(s, { x: 9.4, y: TOP + 0.3, w: 3.3, value: "~195 ms", label: "per interval for each Python listener", color: C.accent2, size: 36, vh: 0.7, lh: 0.6, name: "python cost" });
    stat(s, { x: 9.4, y: TOP + 2.0, w: 3.3, value: "3\u201336 ms", label: "for most Java operations; 80 ms for rolling update_by", color: C.accent1, size: 36, vh: 0.7, lh: 0.8, name: "java cost" });
    text(s, "Python in a listener holds the GIL on the update thread, so its cost lands on every table in that cycle.", { x: 9.4, y: TOP + 3.85, w: 3.3, h: 1.4, fontSize: 14, italic: true, color: C.accent5, objectName: "cost note" });
  }
  {
    const s = content("The runtime in time", "Lifecycle bugs fail silently in a long-lived worker",
      "Each of these happened to us. In a worker that lives all day and is shared, they are worse than in a process we own, because nothing reports them and only a restart clears them.");
    const rows = [
      { icon: ICON.warn, color: C.accent4, head: "A listener that throws stops for good", body: "One traceback, then silence; feeds keep flowing and the worker looks healthy. Wrap every hook and record failures." },
      { icon: ICON.redo, color: C.accent1, head: "Re-running setup stacks listeners", body: "Rebinding the handle does not stop the old one; outputs were written twice. Stop the previous handle first." },
      { icon: ICON.ghost, color: C.accent6, head: "Leaked tasks outlive their code", body: "Old asyncio loops read the next run's stop flag from a global and ran forever. Pass lifecycle objects in explicitly." },
      { icon: ICON.power, color: C.accent2, head: "Shutdown is a hard stop", body: "No Python shutdown hook; on Windows terminate() killed the server with exit 1. Flush and clean up on request, before stopping." },
    ];
    rows.forEach((r, i) => {
      const y = TOP + 0.05 + i * 1.33;
      iconDot(s, { x: MX, y: y + 0.05, d: 0.75, color: r.color, icon: r.icon, name: `pitfall ${i + 1}` });
      text(s, r.head, { x: MX + 1.05, y, w: 10.9, h: 0.45, fontSize: 19, bold: true, color: C.text2, objectName: `pitfall ${i + 1} title` });
      text(s, r.body, { x: MX + 1.05, y: y + 0.45, w: 10.9, h: 0.75, fontSize: 15, objectName: `pitfall ${i + 1} body` });
    });
  }

  // ===========================================================================
  pres.addSection({ title: "Hosting and placement" });
  divider("Hosting and placement", "3   Hosting and placement", "Where our framework and Deephaven each run, and what every choice costs",
    "With the runtime understood, the practical question: how should our framework and Deephaven fit together?");
  {
    const s = content("Hosting and placement", "Three ways to combine our framework with Deephaven",
      "We tested all three. Putting the framework inside a worker gives up the main loop and shares everything. Hosting Deephaven on a thread of our own process keeps our loop and lets our synchronizer step an event-driven graph directly, but shares one interpreter and our globals. A subprocess gives full isolation for one network hop.");
    const rows = [head(["", "Framework inside a worker", "Deephaven on a thread of ours", "Deephaven as a subprocess or service"]),
      [{ text: "Owns the main loop", options: { bold: true } }, "Deephaven", "Us", "Us"],
      [{ text: "Checkpoints", options: { bold: true } }, "~1 s cycle or an event-driven graph", "Event-driven graph our synchronizer steps", "Snapshots and subscriptions"],
      [{ text: "Data path", options: { bold: true } }, "In-process", "In-process, no network hop", "Network: Barrage"],
      [{ text: "Python interpreter", options: { bold: true } }, "Shared with the engine", "Shared: listener lag doubled under load", "Separate"],
      [{ text: "Failure domain", options: { bold: true } }, "Shared", "Shared", "Separate"],
      [{ text: "Console exposure", options: { bold: true } }, "Our code lives in the worker scope", "Our __main__ is the console scope", "Only what we publish"],
      [{ text: "Restart", options: { bold: true } }, "A new worker", "Only with our process", "Restart the subprocess"],
      [{ text: "On the plant", options: { bold: true } }, "A PQ", "Not applicable", "A client of PQs"]];
    s.addTable(rows, tableOpts({ x: MX, y: TOP + 0.05, w: CW, colW: [2.2, 3.31, 3.31, 3.31], fontSize: 13, rowH: 0.58, objectName: "hosting table" }));
  }
  {
    const s = content("Hosting and placement", "Embedded: Deephaven on our thread, stepped by our clock",
      "Deephaven does not insist on the main thread. The pip server started on a background thread in 9.4 seconds while our asyncio loop kept running, at about half speed. Tables and listeners worked in-process with the context handed over from the server's thread. The costs: a shared interpreter, our module globals open to console clients, and one server per process.");
    image(s, IMG.embedded, { x: MX, y: TOP + 0.1, w: 7.4, h: 5.2 }, "Diagram: our process with main thread, dh-service thread, engine graphs and port");
    const st = [
      { value: "9.4 s", label: "to start on a background thread; clients connected normally", color: C.accent1 },
      { value: "36.6 \u2192 74.8 ms", label: "median listener lag, idle vs. host burning CPU in Python", color: C.accent4 },
      { value: "1", label: "server per process: a second start() is refused", color: C.accent2 },
      { value: "__main__", label: "is the console scope: a client modified our state", color: C.accent2 },
    ];
    st.forEach((x, i) => stat(s, { x: 8.4, y: TOP + 0.05 + i * 1.33, w: 4.33, value: x.value, label: x.label, color: x.color, size: 26, vh: 0.5, lh: 0.65, lsize: 14, name: `embedded stat ${i + 1}` }));
  }
  {
    const s = content("Hosting and placement", "As a subprocess: isolation for one network hop",
      "Our host process started a second server as a subprocess, deployed logic with run_script, and read results at three checkpoints on its own clock while a worker pool ran unrelated computation. Counts arrive in whole engine cycles, so they step unevenly against our clock. On Windows terminate is a hard kill, so shut down by request.");
    image(s, IMG.hosting, { x: MX, y: TOP - 0.05, w: 6.3, h: BOTTOM - TOP + 0.05 }, "Diagram: algorithm process hosting the Deephaven server as a subprocess");
    const st = [
      { value: "10.9 s", label: "from launch to a connected client session", color: C.accent1 },
      { value: "6 \u2192 21 \u2192 26", label: "per-symbol counts at our 1.5 s checkpoints: whole engine cycles", color: C.accent3 },
      { value: "exit 1", label: "Windows terminate() is a hard kill: stop gracefully by request", color: C.accent2 },
      { value: "1 port", label: "is the whole boundary between the two runtimes", color: C.text2 },
    ];
    st.forEach((x, i) => stat(s, { x: 7.4, y: TOP + 0.05 + i * 1.33, w: 5.33, value: x.value, label: x.label, color: x.color, size: 26, vh: 0.5, lh: 0.65, lsize: 14, name: `subprocess stat ${i + 1}` }));
  }
  {
    const s = content("Hosting and placement", "On the plant: table work in PQs, stateful apps beside them",
      "The recommended layout. Shared, table-shaped work runs in PQs that subscribe to each other. The stateful framework keeps its own runtime and pulls only the results it acts on. The test: is the app mostly table operations, or mostly other work with some table data?");
    image(s, IMG.hybrid, { x: MX, y: TOP + 0.05, w: 8.6, h: 5.2 }, "Diagram: three PQs on the plant and the event framework as a co-located client");
    card(s, { x: 9.45, y: TOP + 0.05, w: 3.28, h: 3.75, fill: C.text2, name: "decision card" });
    text(s, [
      { text: "The one-question test", options: { bold: true, fontSize: 18, color: C.background1, breakLine: true } },
      { text: " ", options: { fontSize: 6, breakLine: true } },
      { text: "Mostly table operations?", options: { bold: true, color: C.background1, breakLine: true } },
      { text: "Run it as a PQ.", options: { color: C.background2, breakLine: true } },
      { text: " ", options: { fontSize: 6, breakLine: true } },
      { text: "Mostly other work with some table data?", options: { bold: true, color: C.background1, breakLine: true } },
      { text: "Run it beside the plant as a client, a subprocess service or a thread-hosted engine.", options: { color: C.background2 } },
    ], { x: 9.7, y: TOP + 0.3, w: 2.8, h: 3.35, fontSize: 15, paraSpaceAfter: 2, objectName: "decision text" });
  }
  {
    const s = content("Hosting and placement", "We can inventory a running app without its source",
      "Our introspection module runs inside a worker, through any client with console access. It reports the field registry, scope objects by kind, the update graphs with per-node cost, listeners against the handles that can stop them, nodes no name leads to (client exports or leaks), and Python threads. It cannot see what a listener does inside its Python code.");
    const can = ["Every exposed field and its type, across all apps", "Scope objects by kind, underscore names included", "Every update graph, including event-driven ones",
      "Nodes with per-interval cost and dependencies", "Listeners vs. the handles that can stop them", "Unnamed nodes: client exports or leaks", "Python threads, libraries, executors"];
    const cannot = ["What a listener does inside its Python code", "Edges for nodes created before the ancestors log opened", "Ports and memory on Windows (read from /proc)"];
    text(s, "What the report shows", { x: MX, y: TOP, w: 6.6, h: 0.5, fontSize: 19, bold: true, color: C.text2, objectName: "can title" });
    can.forEach((t, i) => {
      s.addImage({ data: ICON.check, x: MX, y: TOP + 0.65 + i * 0.66, w: 0.34, h: 0.34, altText: "check", objectName: `can icon ${i + 1}` });
      text(s, t, { x: MX + 0.5, y: TOP + 0.62 + i * 0.66, w: 6.1, h: 0.45, fontSize: 15, objectName: `can ${i + 1}` });
    });
    text(s, "What it cannot", { x: 7.6, y: TOP, w: 5.1, h: 0.5, fontSize: 19, bold: true, color: C.text2, objectName: "cannot title" });
    cannot.forEach((t, i) => {
      s.addImage({ data: ICON.cross, x: 7.6, y: TOP + 0.65 + i * 0.66, w: 0.34, h: 0.34, altText: "cross", objectName: `cannot icon ${i + 1}` });
      text(s, t, { x: 8.1, y: TOP + 0.62 + i * 0.66, w: 4.6, h: 0.45, fontSize: 15, objectName: `cannot ${i + 1}` });
    });
    card(s, { x: 7.6, y: 4.35, w: 5.13, h: 1.5, fill: "FBF3E2", line: HEX.accent4, lineW: 1.25, name: "ancestors ask" });
    text(s, [
      { text: "One ask of every PQ author", options: { bold: true, fontSize: 16, color: C.text2, breakLine: true } },
      { text: "Open perfmon.update_performance_ancestors_log() at the top of the startup script, so the full graph can be drawn later.", options: { fontSize: 15 } },
    ], { x: 7.85, y: 4.5, w: 4.65, h: 1.25, objectName: "ancestors ask text" });
  }

  // ===========================================================================
  pres.addSection({ title: "Next steps" });
  {
    const s = pres.addSlide({ masterName: "CLOSING_DARK", sectionTitle: "Next steps" });
    s.addText("Decisions and next steps", { placeholder: "title" });
    s.addNotes("Four concrete steps. The pilot is the most important: one real algorithm, run with an event-driven clock, hosted both on a thread and as a subprocess, measured on latency, isolation and operational risk.");
    const steps = [
      { n: "1", head: "Adopt the placement rule", body: "Table work in PQs; stateful apps beside them. Exceptions argued case by case." },
      { n: "2", head: "Pave the road for client apps", body: "One approved container template, CI pipeline and service-account connection." },
      { n: "3", head: "Pilot one real algorithm", body: "Event-driven clock; thread-hosted vs. subprocess; measure latency, isolation, risk." },
      { n: "4", head: "Ask the vendor in writing", body: "Event-driven graphs in PQs, isolation, health checks, shutdown hooks, console attach." },
    ];
    const bw = 2.85, gap = (CW - 4 * bw) / 3;
    steps.forEach((st, i) => {
      const x = MX + i * (bw + gap);
      s.addShape(pres.shapes.OVAL, { x, y: 1.85, w: 0.9, h: 0.9, fill: { color: C.accent2 }, line: { color: C.accent2 }, objectName: `step ${st.n} circle` });
      text(s, st.n, { x, y: 1.85, w: 0.9, h: 0.9, fontSize: 30, bold: true, color: C.background1, align: "center", valign: "middle", fontFace: THEME.headFontFace, objectName: `step ${st.n} number` });
      text(s, st.head, { x, y: 3.0, w: bw, h: 0.9, fontSize: 20, bold: true, color: C.background1, fontFace: THEME.headFontFace, objectName: `step ${st.n} title` });
      text(s, st.body, { x, y: 3.95, w: bw, h: 1.7, fontSize: 15, color: C.background2, objectName: `step ${st.n} body` });
    });
    text(s, "Repo: deephaven-compare \u00b7 ledger: VERIFIED_FACTS.md \u00b7 companion docs: Findings and Guidance, Concepts, Anatomy", { x: MX, y: 6.35, w: CW, h: 0.4, fontSize: 13, color: C.background2, italic: true, objectName: "references" });
  }

  // ===========================================================================
  pres.addSection({ title: "Appendix" });
  {
    const s = content("Appendix", "Appendix: nine earlier claims our tests corrected",
      "For credibility: these are claims we made before testing, and what the tests showed.");
    const rows = [head(["Earlier claim", "What the tests showed"]),
      ["App-mode scripts need `global` to reach the console scope", "Not on Community 42.6 Python: they run in the global scope"],
      ["An underscore keeps a name private", "Underscore names are published as fields"],
      ["Export tickets look like e/<n>", "e followed by a 4-byte binary number"],
      ["A shared ticket can outlive its publisher", "It dies with the publishing session"],
      ["One clock per worker", "One by default; more can be added, including event-driven"],
      ["No built-in Solace or kdb connector", "Enterprise has Solace streaming import (docs); no kdb connector known"],
      ["Unknown whether PQ scripts can come from Git", "Enterprise supports Git-sourced PQ scripts (docs)"],
      ["Native Windows is unsupported", "The pip server runs with three workarounds"],
      ["get_exec_ctx() works on any thread", "Only on a thread that already holds a real context"]];
    s.addTable(rows, tableOpts({ x: MX, y: TOP, w: CW, colW: [5.6, 6.53], fontSize: 13, rowH: 0.5, objectName: "corrections table" }));
  }

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
}

main().catch((e) => { console.error(e); process.exit(1); });
