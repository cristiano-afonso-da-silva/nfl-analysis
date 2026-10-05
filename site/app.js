const SHORT_LABELS = {
  passing_yards: "Pass Yds",
  passing_tds: "Pass TD",
  interceptions: "INT",
  rushing_yards: "Rush Yds",
  receptions: "Receptions",
  receiving_yards: "Rec Yds",
  longest_reception: "Long Rec",
  anytime_touchdown: "Anytime TD",
};
const MARKET_ORDER = Object.keys(SHORT_LABELS);
const DATA = window.HIT_RATE_DATA;

const state = {
  week: null,
  q: "",
  team: "",
  status: "",
  markets: new Set(),
  open: new Set(),
};

const $ = (sel) => document.querySelector(sel);
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const weekData = () => DATA.weeks.find((w) => w.week === state.week);
function gameLabel(g) {
  return g.season === DATA.season ? `Week ${g.week}` : `${g.season} Week ${g.week}`;
}

function formatKickoff(game) {
  if (!game.gameday) return "TBD";
  const [y, m, d] = game.gameday.split("-").map(Number);
  const day = new Date(y, m - 1, d).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  if (!game.gametime) return day;
  const [hh, mm] = game.gametime.split(":").map(Number);
  return `${day} · ${((hh + 11) % 12) + 1}:${String(mm).padStart(2, "0")} ${hh >= 12 ? "PM" : "AM"} ET`;
}

window.headshotFallback = (img) => {
  const div = document.createElement("div");
  div.className = "headshot initials";
  div.textContent = img.dataset.initials || "";
  img.replaceWith(div);
};

function headshot(p) {
  const ini = esc(p.player.split(/\s+/).slice(0, 2).map((s) => s[0]).join(""));
  if (!p.headshot) return `<div class="headshot initials">${ini}</div>`;
  const src = p.headshot.replace("/upload/f_auto,q_auto/", "/upload/c_fill,g_face,w_96,h_96,f_auto,q_auto/");
  return `<img class="headshot" src="${esc(src)}" alt="" loading="lazy" data-initials="${ini}" onerror="headshotFallback(this)">`;
}

/* ---------- Tracking: lines still at 100% since the first week ---------- */

function lineCount(week) {
  return week.games.reduce((n, g) => n + g.props.length, 0);
}

function renderTracking() {
  const first = DATA.weeks[0];
  const current = lineCount(weekData());
  const start = lineCount(first);
  const share = Math.min(100, Math.round((100 * current) / start));
  const gamesBefore = state.week - 1;
  $("#tracking").innerHTML = `
    <div class="tracking">
      <p class="section-label">Lines still at 100% going into Week ${state.week}</p>
      <div class="tracking-number">${current}<span class="of">/ ${start} lines in Week ${first.week} · ${share}%</span></div>
      <p class="tracking-desc">Week ${first.week} started with ${start} lines. Going into Week ${state.week}, ${current} lines have hit in every game the player played this season (Week 1${gamesBefore > 1 ? `–${gamesBefore}` : ""}). A game the player missed doesn't count against his line.</p>
      <div class="progress"><div style="width:${share}%"></div></div>
    </div>`;
}

/* ---------- Week picker & filters ---------- */

function renderWeekPicker() {
  const available = new Set(DATA.weeks.map((w) => w.week));
  const buttons = [];
  for (let week = 1; week <= DATA.total_weeks; week++) {
    const enabled = available.has(week);
    const reason = week === 1 ? "No games played yet to look back on" : "Available once the previous week is played";
    buttons.push(`
      <button class="week-btn ${week === state.week ? "active" : ""}" data-week="${week}" ${enabled ? "" : `disabled title="${reason}"`}>
        <span class="wk-label">Week</span>
        <span class="wk-num">${week}</span>
      </button>`);
  }
  $("#week-picker").innerHTML = buttons.join("");
}

function renderFilters() {
  const data = weekData();
  const teams = data.games.flatMap((g) => [g.away, g.home]).sort();
  if (!teams.includes(state.team)) state.team = "";
  $("#team-filter").innerHTML =
    `<option value="">All teams</option>` +
    teams.map((t) => `<option value="${t}" ${t === state.team ? "selected" : ""}>${esc(data.teams[t].name)}</option>`).join("");

  const present = new Set(data.games.flatMap((g) => g.props.map((p) => p.market)));
  $("#market-chips").innerHTML =
    `<button class="chip ${state.markets.size ? "" : "active"}" data-market="">All lines</button>` +
    MARKET_ORDER.filter((m) => present.has(m))
      .map((m) => `<button class="chip ${state.markets.has(m) ? "active" : ""}" data-market="${m}">${SHORT_LABELS[m]}</button>`)
      .join("");
}

function propMatches(p) {
  if (state.q && !p.player.toLowerCase().includes(state.q)) return false;
  if (state.team && p.team !== state.team) return false;
  if (state.status && p.result.status !== state.status) return false;
  if (state.markets.size && !state.markets.has(p.market)) return false;
  return true;
}

function filteredGames() {
  const filtering = state.q || state.status || state.markets.size;
  return weekData()
    .games.filter((g) => !state.team || g.away === state.team || g.home === state.team)
    .map((g) => ({ ...g, shown: g.props.filter(propMatches) }))
    .filter((g) => !filtering || g.shown.length);
}

/* ---------- Games view ---------- */

function resultCell(result) {
  const text = { hit: `✓ ${result.value}`, miss: `✗ ${result.value}`, pending: "Pending", dnp: "—" }[result.status];
  const title = result.status === "dnp" ? ` title="Did not play, doesn't count against the line"` : "";
  return `<span class="result ${result.status}"${title}>${text}</span>`;
}

function propRow(p) {
  const label = p.market === "anytime_touchdown"
    ? "Anytime Touchdown"
    : `<span class="num">${p.threshold}+</span> ${esc(p.market_label)}`;
  const history = p.games.map((g, i) => `${gameLabel(g)}: ${p.values[i]}`).join(", ");
  return `
    <div class="prop">
      <span class="prop-line">${label}</span>
      <span class="prop-values" title="${esc(history)}">${p.values.join(" · ")}</span>
      ${resultCell(p.result)}
    </div>`;
}

function teamColumn(game, team, data) {
  const players = [];
  game.shown.filter((p) => p.team === team).forEach((p) => {
    let entry = players.find((e) => e.id === p.player_id);
    if (!entry) players.push((entry = { id: p.player_id, first: p, props: [] }));
    entry.props.push(p);
  });
  const body = players.length
    ? players.map(({ first, props }) => `
        <div class="player">
          <div class="player-head">
            ${headshot(first)}
            <div>
              <div class="player-name">${esc(first.player)}</div>
              <div class="player-pos">${esc(first.position || "")}</div>
            </div>
          </div>
          ${props.map(propRow).join("")}
        </div>`).join("")
    : `<div class="empty">No lines at 100%</div>`;
  return `<div class="team-col"><p class="section-label">${esc(data.teams[team].name)}</p>${body}</div>`;
}

function isOpen(game) {
  return state.open.has(game.id) || Boolean(state.q || state.team);
}

function gameCard(game, data) {
  const away = data.teams[game.away];
  const home = data.teams[game.home];
  const hits = game.shown.filter((p) => p.result.status === "hit").length;
  const misses = game.shown.filter((p) => p.result.status === "miss").length;
  const [day, time] = formatKickoff(game).split(" · ");
  const center = game.final
    ? `<span class="score"><span class="${game.away_score < game.home_score ? "loser" : ""}">${game.away_score}</span> – <span class="${game.home_score < game.away_score ? "loser" : ""}">${game.home_score}</span></span><span class="game-status">Final</span>`
    : `<span class="kickoff">${esc(time || day)}</span><span class="game-status">${esc(time ? day : "")}</span>`;
  const counts = hits + misses ? ` · <span class="h">${hits} hit</span> · <span class="m">${misses} miss</span>` : "";
  const side = (team, meta, where) => `
    <span class="team-side ${where}">
      <img class="team-logo" src="${esc(team.logo)}" alt="">
      <span><span class="team-name">${esc(team.nickname)}</span><span class="team-meta">${esc(meta)}</span></span>
    </span>`;
  return `
    <article class="game ${isOpen(game) ? "open" : ""}" data-id="${esc(game.id)}">
      <button class="game-head" aria-expanded="${isOpen(game)}">
        <span class="game-banner" style="background:linear-gradient(100deg, ${esc(away.color)} 0%, ${esc(away.color)} 35%, ${esc(home.color)} 65%, ${esc(home.color)} 100%)">
          ${side(away, `${game.away_record || ""} · Away`, "away")}
          <span class="game-center">${center}</span>
          ${side(home, `Home · ${game.home_record || ""}`, "home")}
        </span>
        <span class="game-strip">
          <span class="counts">${game.shown.length} lines${counts}</span>
          <span class="toggle-hint">${isOpen(game) ? "Hide lines" : "Show lines"} <span class="chevron">▾</span></span>
        </span>
      </button>
      <div class="game-body">
        ${isOpen(game) ? teamColumn(game, game.away, data) + teamColumn(game, game.home, data) : ""}
      </div>
    </article>`;
}

function renderGames() {
  const data = weekData();
  const games = filteredGames();
  const lines = games.reduce((n, g) => n + g.shown.length, 0);
  $("#games-count").textContent = `${games.length} games · ${lines} lines`;
  $("#toggle-all").textContent = games.length && games.every(isOpen) ? "Collapse all" : "Expand all";
  $("#games").innerHTML = games.length
    ? games.map((g) => gameCard(g, data)).join("")
    : `<div class="no-results">No lines match these filters.</div>`;
}

/* ---------- Wiring ---------- */

function selectWeek(week) {
  if (!DATA.weeks.some((w) => w.week === week)) return;
  state.week = week;
  state.open.clear();
  history.replaceState(null, "", `#week-${week}`);
  renderWeekPicker();
  renderTracking();
  renderFilters();
  renderGames();
}

function bindEvents() {
  $("#week-picker").addEventListener("click", (e) => {
    const button = e.target.closest(".week-btn:not(:disabled)");
    if (button) selectWeek(Number(button.dataset.week));
  });
  $("#search").addEventListener("input", (e) => {
    state.q = e.target.value.trim().toLowerCase();
    renderGames();
  });
  $("#team-filter").addEventListener("change", (e) => {
    state.team = e.target.value;
    renderGames();
  });
  $("#status-filter").addEventListener("change", (e) => {
    state.status = e.target.value;
    renderGames();
  });
  $("#market-chips").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    const market = chip.dataset.market;
    if (!market) state.markets.clear();
    else if (state.markets.has(market)) state.markets.delete(market);
    else state.markets.add(market);
    renderFilters();
    renderGames();
  });
  $("#games").addEventListener("click", (e) => {
    const head = e.target.closest(".game-head");
    if (!head) return;
    const id = head.parentElement.dataset.id;
    if (state.open.has(id)) state.open.delete(id);
    else state.open.add(id);
    renderGames();
  });
  $("#toggle-all").addEventListener("click", () => {
    const games = filteredGames();
    if (games.every(isOpen)) state.open.clear();
    else games.forEach((g) => state.open.add(g.id));
    renderGames();
  });
}

function init() {
  if (!DATA || !DATA.weeks.length) {
    $("#games").innerHTML = `<div class="no-results">No data yet. Double-click "Update Data.command" in the project folder.</div>`;
    return;
  }
  const updated = new Date(DATA.updated_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  $("#updated").textContent = `${DATA.season} season · Updated ${updated}`;
  bindEvents();
  const fromHash = Number(location.hash.replace("#week-", ""));
  const latest = DATA.weeks[DATA.weeks.length - 1].week;
  selectWeek(DATA.weeks.some((w) => w.week === fromHash) ? fromHash : latest);
}

init();
