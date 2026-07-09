function nextPowerOfTwo(n) {
  let size = 1;
  while (size < n) size *= 2;
  return size;
}

function parseTeamsFromTextarea(text) {
  return text
    .split("\n")
    .map((v) => v.trim())
    .filter(Boolean);
}

function setupByePreparation() {
  const form = document.getElementById("create-bracket-form");
  if (!form) return;

  const teamsInput = document.getElementById("teams-input");
  const prepareBtn = document.getElementById("prepare-byes");
  const summary = document.getElementById("bye-summary");
  const list = document.getElementById("bye-selector");

  function updateSummaryAndLimit(requiredByes) {
    const checked = list.querySelectorAll("input[type='checkbox']:checked").length;
    summary.textContent =
      requiredByes > 0
        ? `Bracket needs ${requiredByes} BYEs. Selected ${checked}/${requiredByes}.`
        : "No BYEs needed for this team count.";

    const checkboxes = Array.from(list.querySelectorAll("input[type='checkbox']"));
    checkboxes.forEach((cb) => {
      if (!cb.checked) cb.disabled = checked >= requiredByes && requiredByes > 0;
    });
  }

  prepareBtn.addEventListener("click", () => {
    const teams = parseTeamsFromTextarea(teamsInput.value);

    if (teams.length < 2) {
      summary.textContent = "Add at least two teams first.";
      list.innerHTML = "";
      return;
    }

    const size = nextPowerOfTwo(teams.length);
    const requiredByes = size - teams.length;

    list.innerHTML = "";
    teams.forEach((team) => {
      const id = `bye-${team.replace(/\s+/g, "-").toLowerCase()}`;
      const row = document.createElement("label");
      row.className = "bye-item";
      row.innerHTML = `<input type="checkbox" id="${id}" name="bye_teams" value="${team}"> <span>${team}</span>`;
      list.appendChild(row);
    });

    updateSummaryAndLimit(requiredByes);

    list.addEventListener(
      "change",
      () => {
        updateSummaryAndLimit(requiredByes);
      },
      { once: true }
    );

    list.onchange = () => updateSummaryAndLimit(requiredByes);
  });
}

function renderRounds(roundsBoard, rounds) {
  roundsBoard.innerHTML = "";

  rounds.forEach((round, roundIndex) => {
    const col = document.createElement("article");
    col.className = "round-column";
    col.dataset.roundIndex = String(roundIndex);

    const h = document.createElement("h3");
    h.className = "round-title";
    h.textContent = `Round ${roundIndex + 1}`;
    col.appendChild(h);

    const matchesWrap = document.createElement("div");
    matchesWrap.className = "round-matches";

    round.forEach((match, matchIndex) => {
      const m = document.createElement("div");
      m.className = "match";
      m.dataset.matchIndex = String(matchIndex);

      const top = document.createElement("button");
      top.className = `team-btn ${match.winner === match.team1 ? "winner" : ""}`.trim();
      top.textContent = match.team1 || "TBD";
      top.dataset.team = match.team1 || "";
      if (!match.team1) top.disabled = true;

      const bottom = document.createElement("button");
      bottom.className = `team-btn ${match.winner === match.team2 ? "winner" : ""}`.trim();
      bottom.textContent = match.team2 || "TBD";
      bottom.dataset.team = match.team2 || "";
      if (!match.team2 || match.team2 === "BYE") bottom.disabled = true;

      m.appendChild(top);
      m.appendChild(bottom);
      matchesWrap.appendChild(m);
    });

    col.appendChild(matchesWrap);

    roundsBoard.appendChild(col);
  });

  layoutRounds(roundsBoard);
  drawConnectors(roundsBoard);
}

function layoutRounds(roundsBoard) {
  const cols = Array.from(roundsBoard.querySelectorAll(".round-column"));
  if (cols.length === 0) return;

  const firstRoundMatches = cols[0].querySelectorAll(".match");
  if (firstRoundMatches.length === 0) return;

  const matchHeight = firstRoundMatches[0].offsetHeight || 78;
  const baseGap = 10;
  const titleAllowance = 36;
  const minBoardHeight = 380;

  const firstRoundHeight =
    firstRoundMatches.length * matchHeight +
    Math.max(0, firstRoundMatches.length - 1) * baseGap +
    titleAllowance;

  const boardHeight = Math.max(minBoardHeight, firstRoundHeight);
  roundsBoard.style.setProperty("--board-height", `${boardHeight}px`);

  cols.forEach((col) => {
    const matchesWrap = col.querySelector(".round-matches");
    if (!matchesWrap) return;

    const matches = matchesWrap.querySelectorAll(".match");
    const count = matches.length;
    if (count <= 1) {
      matchesWrap.style.rowGap = "0px";
      return;
    }

    const available = Math.max(0, boardHeight - titleAllowance - count * matchHeight);
    const gap = Math.max(baseGap, available / (count - 1));
    matchesWrap.style.rowGap = `${gap}px`;
  });
}

function drawConnectors(roundsBoard) {
  const existing = roundsBoard.querySelector(".connector-layer");
  if (existing) existing.remove();

  const cols = Array.from(roundsBoard.querySelectorAll(".round-column"));
  if (cols.length < 2) return;

  const width = roundsBoard.scrollWidth;
  const height = roundsBoard.scrollHeight;
  const boardRect = roundsBoard.getBoundingClientRect();

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("connector-layer");
  svg.setAttribute("width", String(width));
  svg.setAttribute("height", String(height));
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.style.width = `${width}px`;
  svg.style.height = `${height}px`;

  for (let roundIndex = 0; roundIndex < cols.length - 1; roundIndex += 1) {
    const currentMatches = Array.from(cols[roundIndex].querySelectorAll(".match"));
    const nextMatches = Array.from(cols[roundIndex + 1].querySelectorAll(".match"));

    currentMatches.forEach((matchEl, matchIndex) => {
      const nextMatch = nextMatches[Math.floor(matchIndex / 2)];
      if (!nextMatch) return;

      const fromRect = matchEl.getBoundingClientRect();
      const toRect = nextMatch.getBoundingClientRect();

      const fromX = fromRect.right - boardRect.left + roundsBoard.scrollLeft;
      const fromY = fromRect.top - boardRect.top + roundsBoard.scrollTop + fromRect.height / 2;
      const toX = toRect.left - boardRect.left + roundsBoard.scrollLeft;
      const toY = toRect.top - boardRect.top + roundsBoard.scrollTop + toRect.height / 2;
      const midX = fromX + (toX - fromX) / 2;

      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", `M ${fromX} ${fromY} L ${midX} ${fromY} L ${midX} ${toY} L ${toX} ${toY}`);
      svg.appendChild(path);
    });
  }

  roundsBoard.prepend(svg);
}

function setupBracketInteractions() {
  const board = document.getElementById("rounds-board");
  if (!board) return;

  const bracketId = board.dataset.bracketId;
  let rounds = JSON.parse(board.dataset.rounds || "[]");
  const undoBtn = document.getElementById("undo-pick");
  const resetBtn = document.getElementById("reset-bracket");
  const resetModal = document.getElementById("reset-modal");
  const cancelResetBtn = document.getElementById("cancel-reset");
  const confirmResetBtn = document.getElementById("confirm-reset");
  const actionFeedback = document.getElementById("action-feedback");
  const history = [];

  function setFeedback(message, state = "info") {
    if (!actionFeedback) return;
    actionFeedback.textContent = message;
    actionFeedback.dataset.state = state;
  }

  function syncUndoState() {
    if (!undoBtn) return;
    undoBtn.disabled = history.length === 0;
  }

  async function saveWinner(roundIndex, matchIndex, winner, isUndo = false) {
    const res = await fetch(`/api/brackets/${bracketId}/winner`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ round_index: roundIndex, match_index: matchIndex, winner }),
    });

    const data = await res.json();
    if (!res.ok) {
      setFeedback(data.error || "Could not update winner.", "error");
      return false;
    }

    rounds = data.rounds;
    renderRounds(board, rounds);

    const championBanner = document.getElementById("champion-banner");
    const championName = document.getElementById("champion-name");
    if (data.champion) {
      championBanner.classList.remove("hidden");
      championName.textContent = data.champion;
    } else {
      championBanner.classList.add("hidden");
      championName.textContent = "";
    }

    if (isUndo) {
      setFeedback("Undid last pick.", "success");
    } else {
      setFeedback(`Saved winner: ${winner}.`, "success");
    }

    return true;
  }

  board.addEventListener("click", async (event) => {
    const btn = event.target.closest(".team-btn");
    if (!btn || btn.disabled) return;

    const match = btn.closest(".match");
    const col = btn.closest(".round-column");
    const winner = btn.dataset.team;
    if (!winner || winner === "BYE") return;

    const roundIndex = Number(col.dataset.roundIndex);
    const matchIndex = Number(match.dataset.matchIndex);
    const previousWinner = rounds?.[roundIndex]?.[matchIndex]?.winner || null;

    if (previousWinner === winner) {
      setFeedback("That winner is already selected for this match.", "info");
      return;
    }

    const ok = await saveWinner(roundIndex, matchIndex, winner, false);
    if (!ok) return;

    history.push({ roundIndex, matchIndex, previousWinner, nextWinner: winner });
    syncUndoState();
  });

  if (undoBtn) {
    undoBtn.addEventListener("click", async () => {
      const last = history.pop();
      syncUndoState();
      if (!last) return;

      const ok = await saveWinner(last.roundIndex, last.matchIndex, last.previousWinner, true);
      if (!ok) {
        history.push(last);
        syncUndoState();
      }
    });
  }

  async function resetBracket() {
    const res = await fetch(`/api/brackets/${bracketId}/reset`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const data = await res.json();

    if (!res.ok) {
      setFeedback(data.error || "Could not reset bracket.", "error");
      return;
    }

    rounds = data.rounds;
    renderRounds(board, rounds);
    history.length = 0;
    syncUndoState();

    const championBanner = document.getElementById("champion-banner");
    const championName = document.getElementById("champion-name");
    championBanner.classList.add("hidden");
    championName.textContent = "";

    setFeedback("Bracket reset. All manual picks were cleared.", "success");
  }

  if (resetBtn && resetModal && cancelResetBtn && confirmResetBtn) {
    resetBtn.addEventListener("click", () => {
      resetModal.showModal();
    });

    cancelResetBtn.addEventListener("click", () => {
      resetModal.close();
    });

    confirmResetBtn.addEventListener("click", async () => {
      resetModal.close();
      await resetBracket();
    });
  }

  renderRounds(board, rounds);
  window.addEventListener("resize", () => {
    layoutRounds(board);
    drawConnectors(board);
  });
}

function setupShareButton() {
  const btn = document.getElementById("copy-share");
  if (!btn) return;

  btn.addEventListener("click", async () => {
    const bracketId = btn.dataset.bracketId;
    const res = await fetch(`/api/brackets/${bracketId}/share`, { method: "POST" });
    const data = await res.json();

    if (!res.ok) {
      alert(data.error || "Unable to create share link.");
      return;
    }

    try {
      await navigator.clipboard.writeText(data.share_url);
      btn.textContent = "Share Link Copied";
      const feedback = document.getElementById("action-feedback");
      if (feedback) {
        feedback.textContent = "Share link copied to clipboard.";
        feedback.dataset.state = "success";
      }
    } catch (_err) {
      prompt("Copy this share URL:", data.share_url);
    }
  });
}

setupByePreparation();
setupBracketInteractions();
setupShareButton();
